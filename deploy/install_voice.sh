#!/usr/bin/env bash
# Descarga Piper y una voz en español.
#
#   bash deploy/install_voice.sh
#
# Va aparte de setup.sh porque son ~70 MB de descarga y el robot funciona
# perfectamente sin voz. Se puede ejecutar después, cuando apetezca.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VOICES_DIR="$REPO_DIR/assets/voices"

# Catálogo completo en https://huggingface.co/rhasspy/piper-voices
VOICE="es_ES-davefx-medium"
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium"

mkdir -p "$VOICES_DIR"

echo "==> Piper"
if ! command -v piper >/dev/null 2>&1; then
    if [[ -d "$REPO_DIR/.venv" ]]; then
        "$REPO_DIR/.venv/bin/pip" install -q piper-tts
    else
        pip install --user -q piper-tts
    fi
fi

echo "==> Voz $VOICE"
for ext in onnx onnx.json; do
    dest="$VOICES_DIR/$VOICE.$ext"
    if [[ -f "$dest" ]]; then
        echo "    $VOICE.$ext ya está"
        continue
    fi
    echo "    descargando $VOICE.$ext"
    curl -fL --progress-bar -o "$dest" "$BASE/$VOICE.$ext"
done

echo "==> Reproductor de audio"
if ! command -v aplay >/dev/null 2>&1; then
    echo "    instalando alsa-utils"
    sudo apt-get install -y -qq alsa-utils
fi

cat <<EOF

Voz instalada en $VOICES_DIR

Probar:
  .venv/bin/python -m services.voice --say "Hola, soy Wally"

Si no se oye nada, elige la salida de audio (jack 3.5 mm es la tarjeta 'Headphones'):
  aplay -l
  sudo raspi-config  ->  System Options  ->  Audio

EOF
