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
apt-get install -y -qq python3-venv python3-dev pigpio mosquitto mosquitto-clients avahi-daemon

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
    rsync -a --delete \
        --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
        --exclude 'node_modules' --exclude 'ui/dist' \
        "$REPO_DIR/" "$INSTALL_DIR/"
fi

echo "==> Entorno virtual"
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
    python3 -m venv "$INSTALL_DIR/.venv"
fi
"$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -q -e "$INSTALL_DIR[pi]"

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo "==> Servicios systemd"
cp "$INSTALL_DIR"/deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable wally-motion

cat <<'EOF'

Instalación completa.

  Arrancar:   sudo systemctl start wally-motion
  Ver logs:   journalctl -u wally-motion -f
  Espiar bus: mosquitto_sub -t 'wally/#' -v

ANTES de conectar la batería a los motores, verifica (PLAN.md §4.6):
  1. XL4015 ajustado a 4.8V con multímetro, desconectado de todo.
  2. vcgencmd get_throttled devuelve 0x0 con la Pi alimentada.
  3. Divisores 1kΩ+2kΩ en los tres ECHO de los HC-SR04.

EOF
