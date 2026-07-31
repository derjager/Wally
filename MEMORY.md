# MEMORY.md

Contexto del proyecto para retomar el trabajo sin reconstruirlo desde cero.
Registra lo que **no** se deduce leyendo el código: por qué las cosas son como
son, qué se descartó y qué falta.

**Actualizar al cerrar cada fase.** Última actualización: 2026-07-31, fin de la
Fase 6. **Las seis fases de software están escritas; falta todo el hardware.**

---

## 1. Qué es Wally

Robot de orugas sobre Raspberry Pi 4 con visión, cara expresiva en pantalla,
voz y control desde una webapp por wifi. Proyecto personal de Claudio, en
español.

Documentos: [PLAN.md](PLAN.md) es el diseño (hardware, energía, conexionado);
[README.md](README.md) es la guía de instalación y operación.

## 2. Hardware

| Componente | Detalle |
|---|---|
| Cómputo | Raspberry Pi 4 Model B 4 GB · Raspberry Pi OS Bookworm 64-bit · SD 64 GB |
| Tracción | Chasis Tamiya 70108 + gearbox de 2 motores **FA-130 (3V nominales)** |
| Driver | SparkFun TB6612FNG dual |
| Cámara | OV5647 con LEDs IR |
| Pantalla | **3.5" HDMI, 480×320**, por micro-HDMI. Táctil sin conectar |
| Brazos | 2 servos |
| Sensores | 4× HC-SR04 (se usan 3: frontal + dos diagonales a 35°) |
| Batería | LiPo 2S 7.4V 5500 mAh 35C |
| Audio | Jack 3.5 mm. Solo salida, **no hay micrófono** |

### Energía

Dos rieles con masa común:
- **Lógica**: BEC del usuario (RC) → Pi 4 + pantalla
- **Potencia**: XL4015 ajustado a **4.8 V** → TB6612 `VM` + servos

4.8 V es el voltaje estándar de servos RC; para los motores, el TB6612 pierde
~0.5 V internos y el tope de duty al 60 % deja ~2.6 V efectivos, justo bajo los
3 V nominales del FA-130.

**Componentes en camino** (a 2026-07-31): XL4015, alarma de voltaje LiPo,
fusible 10 A, condensadores, resistencias para los divisores.

### Pendiente de verificar en el hardware físico

- Si los LEDs IR de la cámara son conmutables por GPIO, automáticos con LDR, o
  siempre encendidos. Si no son conmutables, sale GPIO24 del mapa.
- Que el BEC sea switching y dé ≥3 A (un lineal o de 1–2 A no sirve para la Pi 4).
- Resolución nativa real de la pantalla (se asumió 480×320).
- Adaptador micro-HDMI → HDMI.

## 3. Decisiones cerradas — no re-litigar

| Tema | Decisión | Motivo |
|---|---|---|
| GPIO | **pigpio** (`pigpiod`) | PWM por DMA, 1 µs. Servos sin jitter. Estable en Pi 4 |
| Bus | **MQTT** (mosquitto local) | Desacopla servicios, depurable con `mosquitto_sub` |
| Backend | FastAPI + uvicorn | WebSocket de control + REST |
| Frontend | React + Vite + TypeScript | Compilado a estáticos que sirve FastAPI |
| Vídeo | MJPEG sobre HTTP | Simple, ~150 ms. WebRTC quedaría para v2 |
| TTS | Piper | Neural, offline, español, tiempo real en Pi 4 |
| Cara | Pygame a framebuffer (KMSDRM), **pixel art** | Render a 160×106 escalado por factor **entero** (×3) |
| Expresiones | Geometría interpolable, **no sprites** | Permite transiciones suaves sin dibujar fotogramas; sin binarios en el repo |
| pygame | **`pygame-ce`**, no `pygame` | Mismo API; es el fork mantenido y publica wheels para Python nuevo (el original no compila en 3.14) |
| Red | NetworkManager (`nmcli`) | Nativo en Bookworm, `ipv4.method shared` da DHCP solo |
| Detección | **EfficientDet-Lite0** (COCO) por TFLite | ~10 fps en Pi 4 con 4 hilos; incluye la clase `cat` |
| Detección de la gata | Clase `cat` de COCO, sin entrenar | **No hay otros gatos**; no hace falta identificación individual |
| Inferencia | **Hilo aparte**, a 5 fps frente a 15 de captura | Detectar cuesta ~100 ms; en el mismo bucle el vídeo iría a trompicones |
| Overlay | Dibujado **en el servidor**, antes de comprimir | El frame ya se codificaba; sale gratis y vale para `/snapshot.jpg` |
| Arbitraje manual/autónomo | Marca `src` en `cmd/drive` + cesión de 3 s | Mover el joystick basta para tomar el control; no hay que cambiar de modo a mano |
| Alcance | Solo LAN | Sin acceso remoto. Sin autenticación en la webapp |
| Voz | Solo hablar | No hay micrófono. Nada de reconocimiento de voz por ahora |

**Descartado:** ROS 2 (sobredimensionado, pesado de instalar en Raspberry Pi
OS); navegador en modo kiosk para la cara (competiría por CPU con la visión).

## 4. Invariantes de seguridad

No debilitar ninguno sin una razón muy buena. Cada uno tiene pruebas.

1. **Tope de duty al 60 %**, aplicado al convertir a duty físico (no al
   comando): es propiedad de la salida, no de la petición.
2. **Watchdog de 500 ms** en `wally-motion`. Arranca *frenado* y solo se libera
   cuando llegan comandos. Un payload malformado **no** cuenta como señal de vida.
3. **E-stop por `STBY`**: corta el TB6612 por hardware, sin pasar por el PWM.
4. **Nadie "mantiene" el último comando.** Ni el navegador ni `wally-web`. Dejar
   de hablar *es* la señal de parada.
5. **Al cerrarse el WebSocket no se publica una parada**: podría llegar después
   de que otro cliente tomara el control y frenarlo a media maniobra.
6. **Un fallo de conexión wifi siempre recupera el hotspot.** Sin red y sin AP el
   robot queda inalcanzable y habría que sacarle la SD.
7. **El ultrasonido no detecta a la gata** — el pelaje absorbe el sonido. Su
   detección viene solo de la cámara.
8. **La presencia se filtra con histéresis asimétrica** (3 detecciones para
   aparecer, 12 ausencias para desaparecer). Sin ella el robot reaccionaría al
   ruido del detector veinte veces en diez segundos.
9. **Los servicios opcionales degradan, no fallan.** Sin Piper el robot se
   queda mudo; sin modelo TFLite, ciego de reconocimiento. Ninguno de los dos
   impide arrancar: un robot teleoperable sigue siendo útil.
10. **Perseguir a la gata frena por tamaño de la caja en la imagen**, jamás por
    los sensores de distancia, y va más despacio que patrullando.
11. **Si `wally-brain` muere, deja de publicar y el watchdog frena.** Por eso
    corre sin prioridad elevada: degradar así es lo correcto.

## 5. Bugs encontrados y por qué el código es así

Cuatro fallos reales que costó encontrar. Si alguien "simplifica" estas partes,
vuelven.

**Rampa asimétrica — criterio por signo, no por magnitud.**
`abs(target) < abs(current)` fallaba al invertir marcha desde el máximo
(`current=1.0`, `target=-1.0`: ambas magnitudes valen 1). Trataba la frenada
como aceleración y usaba la tasa lenta. El criterio correcto es
`current * delta < 0`. Como efecto secundario encadena solo las dos fases de una
inversión: frena rápido hasta cero, acelera despacio hacia el otro lado.

**Frames por mmap, no por `multiprocessing.shared_memory`.**
Su `resource_tracker` hace unlink del segmento al terminar cualquier proceso que
lo haya abierto, **incluidos los que solo leen**. Con `Restart=always`, cada
reinicio de `wally-web` destruía el buffer de `wally-vision`, que seguía
escribiendo en memoria huérfana: vídeo perdido hasta reiniciar ambos. Los tests
unitarios no lo detectaban porque escritor y lector vivían en el mismo proceso.

**`Bus.start()` espera la conexión.**
`connect_async()` retorna al instante y paho **descarta en silencio** lo que se
publica sin conexión. El estado retenido que los servicios publican al arrancar
se perdía. Síntoma: te conectas a `Wally-Setup`, abres la webapp y la pantalla de
configuración no sabe que está en modo hotspot. Añadido también
`Bus.on_connected()` para republicar tras reconectar, porque los retenidos viven
en el broker y un reinicio de mosquitto los borra.

**El motivo del fallo de red se preservaba mal.**
Al fallar la conexión wifi se vuelve al hotspot, pero `_start_hotspot()` limpiaba
el error. El usuario metía mal la contraseña y reintentaba a ciegas. De ahí el
parámetro `keep_error`.

**La cara arrancaba dormida.**
`_last_activity` empezaba en `0.0`, pero `time.monotonic()` ya lleva rato
corriendo cuando arranca el proceso, así que la resta superaba el umbral de
inactividad de golpe. Ahora es `None` hasta la primera actualización. Cuidado
con cualquier marca de tiempo inicializada a cero contra un reloj monotónico:
el mismo error puede repetirse en otros servicios.

**La cola de voz descartaba lo nuevo en vez de lo viejo.**
Al desbordar buscaba la víctima con `reversed(range(...))`, que da el índice más
alto, es decir el más reciente. Lo relevante es lo último que pasó.

**`numpy` no estaba declarado como dependencia.**
Pillow no lo arrastra, y hasta la Fase 5 nadie lo importaba. Al pasar los
frames como arrays, `wally-vision` moría al primer fotograma. En la Pi habría
funcionado por accidente, porque `picamera2` sí lo instala — el fallo solo
aparecía en el portátil.

**Las salidas de TFLite se identifican por forma, no por posición.**
El orden de los tensores de salida varía entre versiones del modelo. Asumir
posiciones fijas es la causa habitual de que un modelo nuevo devuelva cajas
donde se esperaban puntuaciones. Se detectan por su forma, y clases y
puntuaciones se distinguen porque estas últimas siempre están en [0, 1].

**Girar junto a una pared podía acabar raspando.**
La fase de giro solo se interrumpía por `turn_timeout_s` (3.5 s). Si al girar
una esquina se acercaba por debajo de `backup_mm`, el robot seguía girando y
rozando durante segundos. Ahora la fase TURN comprueba también la distancia
mínima y pasa a retroceder. Lo encontró la prueba extremo a extremo, no las
unitarias: hacía falta la secuencia obstáculo → giro → acercarse.

**En simulación, `wally-motion` publica `state/sensors` con valores
aleatorios.** Al montar escenarios de prueba para brain, esas lecturas pisan
las inyectadas a mano y el comportamiento parece errático. En el robot real
solo hay una fuente de sensores, así que no es un problema; pero es el primer
sitio donde mirar si una prueba de navegación sale no determinista.

## 6. Estado por fases

| Fase | Estado |
|---|---|
| 0 · Energía y bancada | ⏳ Esperando componentes |
| 1 · `wally-motion` | ✅ Código y pruebas. **Sin validar con hardware** |
| 2 · `wally-web` + teleoperación | ✅ Probado extremo a extremo con procesos reales |
| 3 · `wally-net` | ✅ Probado extremo a extremo con mosquitto real |
| 4 · `wally-face` + `wally-voice` | ✅ Probado extremo a extremo. Cara verificada visualmente |
| 5 · Visión (detección) | ✅ Probado extremo a extremo. Overlay verificado visualmente |
| 6 · `wally-brain` (autonomía) | ✅ Probado extremo a extremo. **Constantes sin afinar** |

168 pruebas, todas sin hardware.

**El software está completo; el robot no existe todavía.** Nada se ha ejecutado
nunca sobre la Pi: ni un motor ha girado, ni la cámara ha capturado un frame
real, ni la cara se ha visto en la pantalla. Todo lo verificado ha sido con
backends simulados.

### Verificado extremo a extremo

- vision → `/dev/shm` → web → MJPEG: 11 frames distintos en 3 s
- Reinicio de `wally-web` sin romper el vídeo de `wally-vision`
- Flujo de red completo: arranque en hotspot → escaneo → contraseña incorrecta
  (vuelve al AP conservando el error) → contraseña correcta → cliente → vuelta
  al AP bajo demanda
- Un SSID con `:` sobrevive al parser de nmcli y al viaje por MQTT
- Cadena de ánimos de la cara sobre MQTT real:
  `idle → happy` (comandado) `→ alert` (obstáculo) `→ teleop` (movimiento)
  `→ grumpy` (e-stop)
- Los ocho ánimos renderizados a PNG y revisados a ojo. La primera versión se
  veía tosca — rectángulos planos, `curious` ilegible — y se rehízo añadiendo
  brillo en el ojo, esquinas achaflanadas y asimetría entre ojos.
- Cadena de visión completa: detector → MQTT → telemetría de la webapp y cara.
  Tres transiciones de presencia en un ciclo, `idle → happy` al aparecer la
  gata, y `offset_x` publicado para que la Fase 6 pueda girar hacia ella.
- Overlay renderizado a JPEG y revisado a ojo: caja naranja para la gata, azul
  para el resto, etiquetas legibles.
- Navegación autónoma contra broker real: avanza con el camino libre, gira
  hacia el lado más despejado ante un obstáculo, retrocede si está muy pegado,
  calla mientras alguien usa el joystick, retoma al soltarlo, y gira hacia la
  gata saludándola una sola vez.

## 7. Convenciones del proyecto

- **Todo en español**: código, comentarios, commits, nombres de pruebas.
- **Cada servicio tiene modo simulación** (`--sim`) y funciona sin su hardware.
- Todos aceptan `--no-mqtt` para arrancar aislados.
- Los backends se eligen con una función `create(sim=...)` por módulo.
- Los comentarios explican **por qué**, no qué hace el código.
- Las pruebas nombran el comportamiento esperado, no la función que ejercitan.

## 8. Estructura

```
common/       bus MQTT, config (TOML), framebus (mmap), topics, logging
services/
  motion/     GPIO, motores, servos, HC-SR04, watchdog
  vision/     camera · detector (TFLite) · tracker (histéresis) · overlay
  web/        FastAPI, WebSocket, MJPEG, proxy de red
  net/        nmcli, máquina de estados de red
  face/       expressions (geometría) · render (pygame) · state (reglas)
  voice/      tts (backends) · queue (prioridad y anti-repetición)
  brain/      behaviors (lógica pura) · service (modos y arbitraje)
ui/           React + Vite (compilar antes de desplegar)
config/       wally.toml
models/       coco_labels.txt versionado; el .tflite se descarga
assets/       voices/ (modelos Piper, no versionados)
deploy/       setup.sh, install_voice.sh, install_model.sh + units systemd
tools/        drive_test.py
tests/        168 pruebas
```

La separación se repite en los tres servicios con lógica interesante:
`face/state.py` no importa pygame y `brain/behaviors.py` no importa MQTT, así
que las reglas y los temporizadores se prueban sin abrir una pantalla ni
levantar un broker.

## 9. Al retomar

1. Leer este archivo y el estado de fases.
2. `.venv/bin/python -m pytest` — deben pasar 168.

**No queda software pendiente por escribir. Lo que queda es el robot.** En este
orden:

1. **Fase 0 — energía.** Ajustar el XL4015 a 4.8 V desconectado de todo,
   verificar que el BEC es switching y da ≥3 A, cablear con los divisores en
   los ECHO, y comprobar `vcgencmd get_throttled` a `0x0` con motores al
   máximo. Sin esto, nada de lo demás importa.
2. **Validar la Fase 1** con el robot suspendido: sentido de giro de cada
   oruga, watchdog al cerrar la pestaña, botón de parada.
3. **Afinar `[brain]`** con el robot en el suelo. La tabla de ajustes está en
   la sección D4 del README.
4. Verificar los pendientes de hardware de la sección 2 de este archivo.

Al desplegar: compilar la UI en el portátil (`cd ui && npm run build`) antes de
sincronizar, para que la Pi no necesite npm.

Preferencia del usuario: planificar mediante preguntas concretas antes de
escribir código.
