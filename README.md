# Wally

Robot de orugas sobre Raspberry Pi 4: visión, cara expresiva, voz y control web.

El diseño completo — hardware, energía, diagrama de conexión y fases — está en
**[PLAN.md](PLAN.md)**.

## Estado

| Fase | Estado |
|---|---|
| 0 · Energía y bancada | Esperando componentes |
| 1 · `wally-motion` | **Código listo**, pendiente de validar con hardware |
| 2 · Teleoperación web | **Código listo**, probado extremo a extremo en simulación |
| 3 · Hotspot y red | — |
| 4 · Cara y voz | — |
| 5 · Visión (detección) | — |
| 6 · Autonomía | — |

## Desarrollo sin hardware

Todos los servicios corren en un portátil con backends simulados, así que la
lógica de seguridad se valida antes de que exista el robot.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
(cd ui && npm install && npm run build)

.venv/bin/python -m pytest                        # 45 pruebas, sin hardware
```

Para conducir en el navegador, tres terminales:

```bash
.venv/bin/python -m services.vision --sim         # cámara sintética
.venv/bin/python -m services.motion --sim         # motores simulados
.venv/bin/python -m services.web                  # http://localhost:8080
```

Los dos primeros funcionan sin broker MQTT (añade `--no-mqtt`), pero para que
el joystick mueva algo hace falta mosquitto corriendo:

```bash
brew install mosquitto && brew services start mosquitto   # macOS
sudo apt install mosquitto                                # Linux
```

Solo motores y sensores, sin navegador:

```bash
.venv/bin/python tools/drive_test.py --sim
.venv/bin/python tools/drive_test.py --sim --watchdog
```

## En la Raspberry Pi

```bash
sudo bash deploy/setup.sh
sudo systemctl start wally-motion wally-vision wally-web
journalctl -u wally-motion -f
mosquitto_sub -t 'wally/#' -v          # espiar el bus
```

Webapp en `http://wally.local:8080`. **La primera vez, prueba con el robot
suspendido y las orugas al aire.**

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

Cuatro capas independientes, en orden de cercanía al hardware:

1. **Tope de duty al 60 %** — los motores FA-130 son de 3V y el riel entrega
   4.8V. El tope se aplica al convertir a duty físico, no al comando.
2. **Watchdog de 500 ms** — sin `cmd/drive` fresco, el robot frena. Cubre red
   caída, pestaña cerrada y servicios muertos.
3. **Parada de emergencia por `STBY`** — lleva el pin de habilitación del
   TB6612 a nivel bajo, cortando ambos canales sin depender del PWM.
4. **El navegador nunca "mantiene" un comando** — el joystick vuelve al centro
   al soltar, al ocultarse la pestaña y al perder el foco; y `wally-web` no
   reenvía el último valor por su cuenta. Dejar de hablar *es* la señal de
   parada.

Las pruebas de `tests/test_watchdog.py` y `tests/test_web_control.py` cubren
estas garantías. Si fallan, el robot puede quedar en marcha tras perder la red.

### Vídeo

`wally-vision` es el único proceso con acceso a la cámara y publica los frames
en `/dev/shm/wally_frame` mediante un seqlock; `wally-web` los lee y los sirve
como MJPEG. No pasan por MQTT: a 15 fps serían ~1 MB/s de serialización inútil.

Deliberadamente **no** se usa `multiprocessing.shared_memory`: su
`resource_tracker` hace unlink del segmento cuando termina cualquier proceso
que lo haya abierto, incluidos los que solo leen. Con `Restart=always`, cada
reinicio de `wally-web` dejaba a `wally-vision` escribiendo en un buffer
huérfano. Está cubierto por
`test_un_lector_que_termina_no_destruye_el_buffer`.

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

## Diagnóstico

```bash
curl http://wally.local:8080/api/health
```

`video_age_s` distingue los dos fallos que se parecen: si es `null` no hay
buffer (`wally-vision` nunca arrancó); si crece sin parar, el servicio está
vivo pero dejó de capturar.

| Síntoma | Dónde mirar |
|---|---|
| La webapp carga pero no hay imagen | `systemctl status wally-vision` |
| El joystick no mueve nada | ¿`mosquitto` corriendo? `mosquitto_sub -t 'wally/#' -v` |
| Se mueve a tirones | Wifi débil: si el intervalo entre comandos supera 500 ms, el watchdog frena a cada rato |
| Una oruga va al revés | `invert = true` en `config/wally.toml`, no recablear |
| Arranca y se reinicia solo | Brownout. Revisar el árbol de energía de PLAN.md §4.1 |
