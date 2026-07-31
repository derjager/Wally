# Wally

Robot de orugas sobre Raspberry Pi 4: visión, cara expresiva, voz y control web.

El diseño completo — hardware, energía, diagrama de conexión y fases — está en
**[PLAN.md](PLAN.md)**.

## Estado

| Fase | Estado |
|---|---|
| 0 · Energía y bancada | Esperando componentes |
| 1 · `wally-motion` | **Código listo**, pendiente de validar con hardware |
| 2 · Teleoperación web | — |
| 3 · Hotspot y red | — |
| 4 · Cara y voz | — |
| 5 · Visión | — |
| 6 · Autonomía | — |

## Desarrollo sin hardware

Todo `wally-motion` corre en un portátil con un backend de GPIO simulado, así
que la lógica de seguridad se valida antes de que exista el robot.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/python -m pytest                        # 20 pruebas, sin hardware
.venv/bin/python tools/drive_test.py --sim        # secuencia de maniobras
.venv/bin/python tools/drive_test.py --sim --watchdog
.venv/bin/python -m services.motion --sim --no-mqtt
```

## En la Raspberry Pi

```bash
sudo bash deploy/setup.sh
sudo systemctl start wally-motion
journalctl -u wally-motion -f
mosquitto_sub -t 'wally/#' -v          # espiar el bus
```

**Antes de conectar la batería a los motores**, sigue el orden de encendido de
[PLAN.md §4.6](PLAN.md). En particular: ajusta el XL4015 a 4.8V con multímetro
mientras está desconectado de todo, y monta los divisores 1kΩ+2kΩ en los tres
pines ECHO.

## Arquitectura

Servicios independientes bajo systemd, comunicados por MQTT local. Un fallo en
visión no puede dejar los motores encendidos.

```
wally-motion   Único proceso con acceso a GPIO. Motores, servos, sensores
wally-vision   Dueño exclusivo de la cámara
wally-face     Cara pixel art en la pantalla
wally-voice    TTS con Piper
wally-brain    Máquina de estados de comportamiento
wally-web      FastAPI: webapp, WebSocket, streaming
wally-net      Hotspot y configuración de red
```

### Seguridad

Tres capas independientes, en orden de cercanía al hardware:

1. **Tope de duty al 60 %** — los motores FA-130 son de 3V y el riel entrega
   4.8V. El tope se aplica al convertir a duty físico, no al comando.
2. **Watchdog de 500 ms** — sin `cmd/drive` fresco, el robot frena. Cubre red
   caída, pestaña cerrada y servicios muertos.
3. **Parada de emergencia por `STBY`** — lleva el pin de habilitación del
   TB6612 a nivel bajo, cortando ambos canales sin depender del PWM.

Las pruebas de `tests/test_watchdog.py` cubren estas garantías. Si fallan, el
robot puede quedar en marcha tras perder la red.

## Comandos MQTT

```bash
# Avanzar (hay que repetirlo: el watchdog frena a los 500 ms)
mosquitto_pub -t wally/cmd/drive -m '{"left":0.5,"right":0.5}'

# Parada de emergencia
mosquitto_pub -t wally/cmd/estop -m '{"engaged":true}'
mosquitto_pub -t wally/cmd/estop -m '{"engaged":false}'

# Brazos
mosquitto_pub -t wally/cmd/servo -m '{"arm_left":90,"arm_right":45}'
```
