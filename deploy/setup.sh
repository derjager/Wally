#!/usr/bin/env bash
# Instalación de Wally en Raspberry Pi OS Bookworm 64-bit.
#
#   sudo bash deploy/setup.sh
#
# Idempotente: se puede volver a ejecutar sin romper nada.

set -euo pipefail

INSTALL_DIR=/opt/wally
SERVICE_USER=wally
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "Ejecuta con sudo." >&2
    exit 1
fi

echo "==> Paquetes del sistema"
apt-get update -qq
apt-get install -y -qq python3-venv python3-dev pigpio mosquitto mosquitto-clients \
    avahi-daemon rsync
# picamera2 se instala por apt, no por pip: depende de libcamera compilado
# contra el sistema y pip no puede construirlo.
apt-get install -y -qq python3-picamera2 --no-install-recommends

echo "==> pigpiod y mosquitto"
systemctl enable --now pigpiod
systemctl enable --now mosquitto

echo "==> Usuario de servicio"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi
# gpio: acceso a los pines. video: acceso a la cámara, para las fases siguientes.
usermod -aG gpio,video,audio "$SERVICE_USER"

echo "==> Código en $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
if [[ "$REPO_DIR" != "$INSTALL_DIR" ]]; then
    # ui/dist SÍ se copia: si compilaste la UI en tu equipo, esto la trae y la
    # Pi no necesita npm.
    rsync -a --delete \
        --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
        --exclude 'node_modules' \
        "$REPO_DIR/" "$INSTALL_DIR/"
fi

echo "==> Entorno virtual"
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
    # --system-site-packages para que picamera2 (instalado por apt) sea
    # visible dentro del venv.
    python3 -m venv --system-site-packages "$INSTALL_DIR/.venv"
fi
"$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -q -e "$INSTALL_DIR[pi]"

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo "==> Interfaz web"
if command -v npm >/dev/null 2>&1; then
    (cd "$INSTALL_DIR/ui" && npm install --silent && npm run build)
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/ui"
elif [[ -d "$INSTALL_DIR/ui/dist" ]]; then
    echo "    npm no está, pero ui/dist ya viene compilado."
else
    echo "    AVISO: sin npm y sin ui/dist. Compila la UI en tu equipo"
    echo "    (cd ui && npm install && npm run build) y vuelve a desplegar."
fi

echo "==> NetworkManager"
# wally-net lo necesita para el hotspot de configuración. En Bookworm ya viene
# activo por defecto, pero una imagen antigua actualizada puede seguir con
# dhcpcd.
if ! systemctl is-enabled NetworkManager >/dev/null 2>&1; then
    echo "    AVISO: NetworkManager no está activo. wally-net no podrá crear"
    echo "    el hotspot. Actívalo con: sudo raspi-config -> Advanced -> Network Config"
fi

echo "==> Servicios systemd"
cp "$INSTALL_DIR"/deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable wally-motion wally-vision wally-web wally-net

cat <<'EOF'

Instalación completa.

  Arrancar:   sudo systemctl start wally-motion wally-vision wally-web wally-net
  Ver logs:   journalctl -u wally-motion -f
  Espiar bus: mosquitto_sub -t 'wally/#' -v
  Webapp:     http://wally.local:8080

PRIMERA PUESTA EN MARCHA
  Si no hay wifi configurada, Wally levanta la red 'Wally-Setup'
  (contraseña por defecto: wally1234 — cámbiala en config/wally.toml).
  Conéctate a ella y abre http://192.168.4.1:8080 para elegir tu wifi.

ANTES de conectar la batería a los motores, verifica (PLAN.md §4.6):
  1. XL4015 ajustado a 4.8V con multímetro, desconectado de todo.
  2. vcgencmd get_throttled devuelve 0x0 con la Pi alimentada.
  3. Divisores 1kΩ+2kΩ en los tres ECHO de los HC-SR04.

La primera vez, prueba la webapp con el robot SUSPENDIDO (orugas al aire).

EOF
