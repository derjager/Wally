"""Wrapper sobre NetworkManager vía `nmcli`.

Bookworm usa NetworkManager por defecto (PLAN.md §5), así que no hacen falta
los montajes artesanales de `hostapd` + `dnsmasq` que llevan los tutoriales
antiguos: `ipv4.method shared` levanta el DHCP solo.

Una limitación física que condiciona todo el diseño: **la wifi de la Pi no
puede ser punto de acceso y cliente a la vez** sobre la misma interfaz. El
robot está en un modo o en el otro, nunca en ambos.
"""

from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger("net.nmcli")

AP_CONNECTION = "wally-ap"
AP_ADDRESS = "192.168.4.1"
DEFAULT_IFACE = "wlan0"


@dataclass(frozen=True)
class Network:
    ssid: str
    signal: int
    security: str

    @property
    def open(self) -> bool:
        return self.security in ("", "--")


@dataclass(frozen=True)
class NetStatus:
    mode: str  # "client" | "hotspot" | "disconnected"
    ssid: str | None = None
    ip: str | None = None

    @property
    def online(self) -> bool:
        return self.mode == "client" and self.ip is not None


# --------------------------------------------------------------------------
# Parsing del formato terse de nmcli
# --------------------------------------------------------------------------


def unescape(field: str) -> str:
    """Deshace el escapado con barra invertida de `nmcli -t`."""
    out: list[str] = []
    i = 0
    while i < len(field):
        if field[i] == "\\" and i + 1 < len(field):
            out.append(field[i + 1])
            i += 2
        else:
            out.append(field[i])
            i += 1
    return "".join(out)


def split_terse(line: str) -> list[str]:
    """Parte una línea de `nmcli -t` por los ':' que no están escapados.

    Los SSID pueden contener ':' —y de hecho cualquier carácter—, que nmcli
    escapa como '\\:'. Un `line.split(":")` a secas parte esos SSID por la
    mitad y corrompe la lista de redes.
    """
    fields: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            current.append(ch)
            current.append(line[i + 1])
            i += 2
            continue
        if ch == ":":
            fields.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    fields.append("".join(current))
    return [unescape(f) for f in fields]


# --------------------------------------------------------------------------
# Interfaz
# --------------------------------------------------------------------------


class NetBackend(ABC):
    @abstractmethod
    def scan(self) -> list[Network]: ...

    @abstractmethod
    def status(self) -> NetStatus: ...

    @abstractmethod
    def known_ssids(self) -> list[str]: ...

    @abstractmethod
    def connect(self, ssid: str, password: str | None) -> tuple[bool, str]: ...

    @abstractmethod
    def start_hotspot(self, ssid: str, password: str) -> tuple[bool, str]: ...

    @abstractmethod
    def stop_hotspot(self) -> None: ...

    @abstractmethod
    def forget(self, ssid: str) -> bool: ...


class NmcliBackend(NetBackend):
    """Implementación real. Requiere privilegios para modificar conexiones."""

    def __init__(self, iface: str = DEFAULT_IFACE, timeout: float = 45.0) -> None:
        self._iface = iface
        self._timeout = timeout

    def _run(self, *args: str, timeout: float | None = None) -> tuple[int, str, str]:
        cmd = ["nmcli", *args]
        try:
            p = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or self._timeout,
            )
            return (p.returncode, p.stdout.strip(), p.stderr.strip())
        except subprocess.TimeoutExpired:
            return (124, "", f"timeout ejecutando {' '.join(cmd)}")
        except FileNotFoundError:
            return (127, "", "nmcli no está instalado")

    # -- consulta --------------------------------------------------------

    def scan(self) -> list[Network]:
        # --rescan yes fuerza un barrido nuevo en lugar de devolver la caché.
        rc, out, err = self._run(
            "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes"
        )
        if rc != 0:
            log.warning("escaneo fallido: %s", err)
            return []

        best: dict[str, Network] = {}
        for line in out.splitlines():
            parts = split_terse(line)
            if len(parts) < 3 or not parts[0]:
                continue
            ssid = parts[0]
            try:
                signal = int(parts[1])
            except ValueError:
                signal = 0
            net = Network(ssid=ssid, signal=signal, security=parts[2])
            # Una misma red puede aparecer varias veces (varios AP o bandas):
            # nos quedamos con la señal más fuerte.
            if ssid not in best or signal > best[ssid].signal:
                best[ssid] = net

        return sorted(best.values(), key=lambda n: n.signal, reverse=True)

    def status(self) -> NetStatus:
        rc, out, _ = self._run("-t", "-f", "DEVICE,STATE,CONNECTION", "dev", "status", timeout=10)
        if rc != 0:
            return NetStatus(mode="disconnected")

        connection = None
        for line in out.splitlines():
            parts = split_terse(line)
            if len(parts) >= 3 and parts[0] == self._iface:
                if parts[1] != "connected":
                    return NetStatus(mode="disconnected")
                connection = parts[2]
                break

        if connection is None:
            return NetStatus(mode="disconnected")

        ip = self._ip_address()
        if connection == AP_CONNECTION:
            return NetStatus(mode="hotspot", ssid=None, ip=ip)
        return NetStatus(mode="client", ssid=connection, ip=ip)

    def _ip_address(self) -> str | None:
        rc, out, _ = self._run("-t", "-f", "IP4.ADDRESS", "dev", "show", self._iface, timeout=10)
        if rc != 0:
            return None
        for line in out.splitlines():
            if ":" in line:
                value = line.split(":", 1)[1]
                if "/" in value:
                    return value.split("/")[0]
        return None

    def known_ssids(self) -> list[str]:
        rc, out, _ = self._run("-t", "-f", "NAME,TYPE", "connection", "show", timeout=10)
        if rc != 0:
            return []
        names = []
        for line in out.splitlines():
            parts = split_terse(line)
            if len(parts) >= 2 and "wireless" in parts[1] and parts[0] != AP_CONNECTION:
                names.append(parts[0])
        return names

    # -- acciones --------------------------------------------------------

    def connect(self, ssid: str, password: str | None) -> tuple[bool, str]:
        self.stop_hotspot()

        args = ["dev", "wifi", "connect", ssid, "ifname", self._iface]
        if password:
            args += ["password", password]

        rc, _, err = self._run(*args)
        if rc == 0:
            return (True, f"conectado a {ssid}")

        # nmcli deja un perfil a medias tras un fallo de autenticación; si no
        # se borra, el siguiente intento con la contraseña correcta reutiliza
        # el perfil roto y vuelve a fallar.
        self.forget(ssid)
        return (False, err or "no se pudo conectar")

    def start_hotspot(self, ssid: str, password: str) -> tuple[bool, str]:
        self._run("connection", "delete", AP_CONNECTION, timeout=15)

        rc, _, err = self._run(
            "connection", "add",
            "type", "wifi",
            "ifname", self._iface,
            "con-name", AP_CONNECTION,
            "autoconnect", "no",
            "ssid", ssid,
        )
        if rc != 0:
            return (False, err or "no se pudo crear el perfil del AP")

        rc, _, err = self._run(
            "connection", "modify", AP_CONNECTION,
            "802-11-wireless.mode", "ap",
            "802-11-wireless.band", "bg",
            "ipv4.method", "shared",
            "ipv4.addresses", f"{AP_ADDRESS}/24",
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk", password,
        )
        if rc != 0:
            return (False, err or "no se pudo configurar el AP")

        rc, _, err = self._run("connection", "up", AP_CONNECTION)
        if rc != 0:
            return (False, err or "no se pudo levantar el AP")
        return (True, f"hotspot '{ssid}' activo en {AP_ADDRESS}")

    def stop_hotspot(self) -> None:
        self._run("connection", "down", AP_CONNECTION, timeout=15)

    def forget(self, ssid: str) -> bool:
        rc, _, _ = self._run("connection", "delete", ssid, timeout=15)
        return rc == 0


# --------------------------------------------------------------------------
# Simulación
# --------------------------------------------------------------------------


class FakeBackend(NetBackend):
    """Backend de mentira para desarrollo y pruebas.

    Simula lo incómodo del mundo real: una contraseña incorrecta falla, y
    conectarse tarda en reflejarse.
    """

    def __init__(self, networks: list[Network] | None = None) -> None:
        self.networks = networks or [
            Network("CasaDeClaudio", 82, "WPA2"),
            Network("CasaDeClaudio_5G", 71, "WPA2"),
            Network("Vecino:Raro", 44, "WPA2"),  # el ':' ejercita el parser
            Network("WifiAbierto", 30, ""),
        ]
        self.valid_password = "correcta"
        self._status = NetStatus(mode="disconnected")
        self._known: list[str] = []
        self.calls: list[str] = []

    def scan(self) -> list[Network]:
        self.calls.append("scan")
        return sorted(self.networks, key=lambda n: n.signal, reverse=True)

    def status(self) -> NetStatus:
        return self._status

    def known_ssids(self) -> list[str]:
        return list(self._known)

    def connect(self, ssid: str, password: str | None) -> tuple[bool, str]:
        self.calls.append(f"connect:{ssid}")
        known = {n.ssid: n for n in self.networks}
        if ssid not in known:
            return (False, "red no encontrada")
        if not known[ssid].open and password != self.valid_password:
            return (False, "contraseña incorrecta")
        self._status = NetStatus(mode="client", ssid=ssid, ip="192.168.1.55")
        if ssid not in self._known:
            self._known.append(ssid)
        return (True, f"conectado a {ssid}")

    def start_hotspot(self, ssid: str, password: str) -> tuple[bool, str]:
        self.calls.append("start_hotspot")
        self._status = NetStatus(mode="hotspot", ssid=ssid, ip=AP_ADDRESS)
        return (True, f"hotspot '{ssid}' activo")

    def stop_hotspot(self) -> None:
        self.calls.append("stop_hotspot")
        if self._status.mode == "hotspot":
            self._status = NetStatus(mode="disconnected")

    def forget(self, ssid: str) -> bool:
        self.calls.append(f"forget:{ssid}")
        if ssid in self._known:
            self._known.remove(ssid)
            return True
        return False


def create(sim: bool, iface: str = DEFAULT_IFACE) -> NetBackend:
    return FakeBackend() if sim else NmcliBackend(iface=iface)
