"""Topics MQTT de Wally. Única fuente de verdad para todos los servicios."""

# Comandos entrantes
CMD_DRIVE = "wally/cmd/drive"  # {"left": -1..1, "right": -1..1}
CMD_SERVO = "wally/cmd/servo"  # {"arm_left": 0..180, "arm_right": 0..180}
CMD_ESTOP = "wally/cmd/estop"  # {"engaged": bool}
CMD_SAY = "wally/cmd/say"
CMD_MOOD = "wally/cmd/mood"
CMD_MODE = "wally/cmd/mode"

# Estado publicado
STATE_MOTION = "wally/state/motion"
STATE_SENSORS = "wally/state/sensors"
STATE_BATTERY = "wally/state/battery"

# Visión
VISION_DETECTIONS = "wally/vision/detections"
VISION_CAT = "wally/vision/cat"

# Disponibilidad (Last Will and Testament)
SYS_ONLINE = "wally/sys/online/{service}"


def online_topic(service: str) -> str:
    return SYS_ONLINE.format(service=service)
