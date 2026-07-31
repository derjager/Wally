"""Topics MQTT de Wally. Única fuente de verdad para todos los servicios."""

# Comandos entrantes
CMD_DRIVE = "wally/cmd/drive"  # {"left": -1..1, "right": -1..1}
CMD_SERVO = "wally/cmd/servo"  # {"arm_left": 0..180, "arm_right": 0..180}
CMD_ESTOP = "wally/cmd/estop"  # {"engaged": bool}
CMD_SAY = "wally/cmd/say"  # {"text": "...", "priority": "normal|urgent"}
CMD_MOOD = "wally/cmd/mood"  # {"mood": "...", "hold_s": 3.0}
CMD_MODE = "wally/cmd/mode"
CMD_LOOK = "wally/cmd/look"  # {"x": -1..1, "y": -1..1} hacia dónde mira

# Estado publicado
STATE_MOTION = "wally/state/motion"
STATE_SENSORS = "wally/state/sensors"
STATE_BATTERY = "wally/state/battery"
# La cara lo usa para animar la boca mientras habla.
STATE_SPEAKING = "wally/state/speaking"
STATE_MOOD = "wally/state/mood"

# Visión
VISION_DETECTIONS = "wally/vision/detections"
VISION_CAT = "wally/vision/cat"

# Red. El estado va retenido para que la webapp lo tenga nada más suscribirse,
# sin esperar al siguiente ciclo.
NET_STATUS = "wally/net/status"
NET_NETWORKS = "wally/net/networks"
CMD_NET_SCAN = "wally/cmd/net/scan"
CMD_NET_CONNECT = "wally/cmd/net/connect"
CMD_NET_HOTSPOT = "wally/cmd/net/hotspot"
CMD_NET_FORGET = "wally/cmd/net/forget"

# Disponibilidad (Last Will and Testament)
SYS_ONLINE = "wally/sys/online/{service}"


def online_topic(service: str) -> str:
    return SYS_ONLINE.format(service=service)
