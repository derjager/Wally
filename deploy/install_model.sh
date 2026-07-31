#!/usr/bin/env bash
# Descarga el modelo de detección de objetos e instala TFLite.
#
#   bash deploy/install_model.sh
#
# Va aparte de setup.sh porque son ~5 MB más el runtime, y el robot funciona
# perfectamente sin detección: se puede conducir igual.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="$REPO_DIR/models"
MODEL="$MODELS_DIR/efficientdet_lite0.tflite"

# EfficientDet-Lite0, entrenado con COCO (incluye la clase `cat`). Entrada
# 320x320, ~10 fps en una Pi 4 con 4 hilos.
URL="https://storage.googleapis.com/download.tensorflow.org/models/tflite/task_library/object_detection/rpi/lite-model_efficientdet_lite0_detection_metadata_1.tflite"

mkdir -p "$MODELS_DIR"

echo "==> Runtime de TensorFlow Lite"
PIP="$REPO_DIR/.venv/bin/pip"
[[ -x "$PIP" ]] || PIP="pip"

if ! "$REPO_DIR/.venv/bin/python" -c "import tflite_runtime" 2>/dev/null; then
    # tflite-runtime tiene wheels para ARM64; en otras plataformas puede no
    # haberlos, y ahí el paquete completo de tensorflow sirve igual.
    "$PIP" install -q tflite-runtime || {
        echo "    tflite-runtime no disponible aquí; probando tensorflow"
        "$PIP" install -q tensorflow || echo "    AVISO: sin runtime, no habrá detección"
    }
fi

echo "==> Modelo de detección"
if [[ -f "$MODEL" ]]; then
    echo "    ya está en $MODEL"
else
    curl -fL --progress-bar -o "$MODEL" "$URL"
    echo "    guardado en $MODEL"
fi

cat <<EOF

Modelo instalado.

Probar sin cámara real:
  .venv/bin/python -m services.vision --sim

En la Pi, con cámara y detección:
  sudo systemctl restart wally-vision
  mosquitto_sub -t 'wally/vision/#' -v

Las clases reconocidas están en models/coco_labels.txt (80 objetos, entre
ellos 'cat'). Para seguir otra cosa, cambia track_label en config/wally.toml.

EOF
