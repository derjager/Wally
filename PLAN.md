# Wally — Plan de proyecto

Robot con orugas, visión, cara expresiva y control web sobre Raspberry Pi 4.

---

## 1. Inventario de hardware

| Componente | Modelo | Notas |
|---|---|---|
| Cómputo | Raspberry Pi 4 Model B, 4 GB | Raspberry Pi OS Bookworm 64-bit, SD 64 GB |
| Tracción | Chasis Tamiya 70108 + gearbox de 2 motores | Motores FA-130: **3V nominales**, rango 1.5–3V |
| Driver motores | SparkFun TB6612FNG (dual) | 1.2 A continuos / 3.2 A pico por canal |
| Cámara | OV5647 con módulo IR | Vía CSI. Stack libcamera / Picamera2 |
| Pantalla | **3.2" SPI táctil, 320×240**, modelo **MPI3201** (ILI9341) | Se monta directo sobre el header de 40 pines. **Táctil conectado** (ver §8) |
| Brazos | 2 × servo | PWM 50 Hz vía pigpio, a 4.8V |
| Audio | Jack 3.5 mm de la Pi | Solo salida (sin micrófono en v1) |
| Sensores | **3 × HC-SR04** | ECHO a 5V: divisor resistivo obligatorio. Había un 4º de repuesto, pero sus pines (GPIO9/11) se los quedó la pantalla SPI (§3) |
| Energía | **LiPo 2S 7.4V 5500mAh 35C** | 8.4V cargada, corte a 6.6V. Ver §2 |

---

## 2. Árbol de energía

**El riesgo nº1 del proyecto.** Los motores FA-130 son de **3V**. La LiPo 2S entrega 8.4V a plena carga: conectarla directo a `VM` del TB6612 los quema.

Batería: **LiPo 2S, 7.4V nominales (8.4V cargada), 5500 mAh, 35C.** Capacidad de descarga muy holgada; el cuello de botella es la regulación, no la batería.

**Dos rieles con masa común:**

```
                 ┌──────────────────────────────────────┐
   LiPo 2S ─┬─── │ UBEC 5V / 5A     → Pi 4 + pantalla   │  RIEL LÓGICA
   8.4→6.6V │    └──────────────────────────────────────┘
            │    ┌──────────────────────────────────────┐
            └─── │ XL4015 ajustable → TB6612 VM         │  RIEL POTENCIA
                 │ fijado a 4.8V    → 2 servos          │
                 └──────────────────────────────────────┘
                          masa común obligatoria
```

**Por qué 4.8V en el riel de potencia:** es el voltaje estándar de servos RC (rango 4.8–6V). Para los motores, el TB6612 pierde ~0.5V internos → llegan ~4.3V, que con el cap de duty al 60 % dan **~2.6V efectivos**, justo por debajo de los 3V nominales del FA-130. Un solo regulador sirve a ambos consumidores.

### ⚠️ Verificar el BEC antes de conectarlo a la Pi

Hay un BEC de RC disponible, pero **no todos sirven para alimentar una Pi 4**. Busca en su etiqueta el amperaje y si es lineal o switching:

| Tipo de BEC | Destino |
|---|---|
| **Switching, ≥ 4A** | Riel de lógica: Pi 4 + pantalla. Es el plan óptimo |
| **Switching, 3A** | Justo. Sirve para la Pi si la pantalla se alimenta por su propio USB |
| **Switching, < 2A** o **lineal** | Solo para los servos. Hace falta un UBEC 5A aparte para la Pi |

La Pi 4 puede pedir picos de 3A ella sola. Un BEC lineal disipa la diferencia de voltaje en calor y no sostiene esa corriente: provoca undervoltage y reinicios.

### Lista de compra

| Item | Modelo / búsqueda | Aprox. |
|---|---|---|
| Buck lógica | El **BEC** existente si cumple; si no, **UBEC 5V/5A** | USD 8 |
| Buck potencia | **XL4015 5A ajustable** — "XL4015 5A DC-DC step down adjustable" | USD 4 |
| Alarma LiPo | Alarma de voltaje 1-8S con buzzer | USD 2 |
| Protección | Fusible 10A + interruptor ≥10A (o XT60) | — |
| Filtrado | Cap 1000 µF/16V (potencia) + 470 µF/16V (lógica) | — |
| Cableado | Silicona AWG16-18 para el tramo batería → bucks | — |

> **❌ No usar LM2596.** Su especificación de 3A asume disipación ideal; en la práctica entrega 1.5–2A estables y provocará undervoltage permanente en la Pi 4.

**Ajustar el XL4015 a 4.8V con multímetro ANTES de conectar motores o servos.**

Salvaguardas de software:
- **Cap de duty cycle al 60 %** en `wally-motion`, incluso con el buck ya regulado. Doble red.
- **Rampa de aceleración**: nunca 0 → 100 % instantáneo. Evita el pico de calado (~2.2 A) que satura el TB6612.
- Corte por batería baja: la LiPo 2S no debe bajar de **6.6V** (3.3V/celda). La alarma es la red física; el software añade aviso vía cara y voz.

Monitorización de batería: la Pi no tiene ADC. Con un **ADS1115** por I2C (GPIO2/3, ya libres) + divisor resistivo se obtiene telemetría real. Sin él, v1 funciona con la alarma física y estimación por tiempo.

---

## 3. Mapa de pines (BCM)

La pantalla nueva es SPI y se monta **directo sobre el header de 40 pines**,
así que ocupa esos GPIO **se use el táctil o no** — a diferencia de la HDMI
original, aquí no hay forma de evitarlo. Esto obligó a mover 2 funciones que
chocaban con el pinout real de esta pantalla.

> ✅ **Pinout confirmado.** Modelo: **MPI3201** ("3.2inch RPi Display",
> LCDWIKI), controlador **ILI9341**, táctil resistivo **XPT2046**. Tabla de
> pines tomada del datasheet oficial del fabricante (`3.2inch_RPi_Display_V1.0.pdf`,
> rev1.0) — ya no es una estimación. El instalador confirmado es
> `goodtft/LCD-show` (`sudo ./LCD32-show`), ver README C10.

```
PANTALLA SPI 3.2" MPI3201 — pinout confirmado (BCM, header 1-26 completo)
  SPI0   SCLK → GPIO11 (p23)   MOSI → GPIO10 (p19)   MISO → GPIO9 (p21)
         LCD_CS  → GPIO8 (p24, CE0)     TOUCH_CS → GPIO7 (p26, CE1)
  LCD    DC(RS) → GPIO24 (p18)   RST → GPIO25 (p22)
  TOUCH  IRQ → GPIO17 (p11)
  Sin pin de backlight: no usa GPIO18 ni ningún otro GPIO para el LED —
  el datasheet marca ese pin como NC. Confirma que GPIO18 queda libre.

RESERVADO
  GPIO2  SDA  ─ I2C: ADS1115 (batería) y futuros sensores ToF
  GPIO3  SCL  ─ ídem
  GPIO0/1     ─ EEPROM HAT (no usar)

TB6612FNG
  PWMA → GPIO12       AIN1 → GPIO20       AIN2 → GPIO21
  PWMB → GPIO13       BIN1 → GPIO16       BIN2 → GPIO26
  STBY → GPIO19        (antes GPIO25 — se lo quedó RST de la pantalla)
  VCC  → 3.3V (lógica)        VM → riel de potencia (4.8V)

SERVOS (pigpio, 50 Hz) — alimentados del riel de potencia a 4.8V
  Brazo izquierdo  → GPIO18   (sin cambios: la pantalla no usa este pin)
  Brazo derecho    → GPIO23

HC-SR04 ×3  (VCC a 5V; cada ECHO vía divisor 1kΩ+2kΩ)
  Frontal          TRIG → GPIO4    ECHO → GPIO15   (antes GPIO17 — IRQ táctil)
  Diagonal izq 35° TRIG → GPIO5    ECHO → GPIO27
  Diagonal der 35° TRIG → GPIO6    ECHO → GPIO22
  (4º de repuesto: retirado del mapa — sus pines, GPIO9/11, pasaron a SPI0)

CÁMARA IR (opcional, ver §10)
  LEDs IR → expansor GPIO por I2C (MCP23017 o similar), no GPIO24 nativo:
            ese pin se lo quedó el DC de la pantalla. Es una señal digital
            lenta (habilita/deshabilita un transistor), así que un expansor
            I2C es viable aquí — a diferencia de STBY, los servos o los ECHO,
            que si no van por GPIO nativo pierden precisión de temporización.
            NO conectar los LEDs directo a un GPIO/expansor: superan los
            16 mA por pin, sigue haciendo falta el 2N2222 (§4.4).

GPIO14 (antes UART TX de depuración) → libre. GPIO15 (RX) pasó al ECHO
frontal, así que la consola serie ya no está disponible completa.
```

> ⚠️ **Bloqueo mecánico, no solo eléctrico.** La MPI3201 mide 84.91×56.54 mm
> — prácticamente el tamaño de la propia Pi — y su conector de 26 pines va
> soldado a un costado, así que al insertarla el cuerpo de la placa queda
> por encima de **todo** el header de 40 pines, no solo de los 8 pines que
> usa eléctricamente (GPIO7/8/9/10/11/17/24/25). Los demás GPIO (motores,
> servos, ECHO izq./der., etc.) siguen siendo válidos en el mapa, pero para
> cablearlos con jumpers normales sin pelear con la pantalla por encima
> conviene un **cable de extensión GPIO (ribbon/breakout de 40 pines)**:
> saca los 40 pines a un lugar accesible del chasis, la pantalla se conecta
> a ese breakout en vez de directo a la Pi, y el resto del cableado de
> §4.5 se hace ahí sin estorbos. No resuelve los conflictos eléctricos de
> arriba (esos son inevitables, la señal es la misma sin importar dónde se
> acceda a ella) — solo el problema de espacio físico para soldar/enchufar.

> ⚠️ **HC-SR04: el pin ECHO emite 5V** contra un GPIO de 3.3V. Requiere divisor resistivo (1 kΩ + 2 kΩ) en cada ECHO, sin excepción. Es la causa más común de Raspberry Pis dañadas en robótica.

**Disparo secuencial round-robin** a ~15 Hz totales (5 Hz por sensor). Disparar los tres a la vez provoca crosstalk: el eco de uno lo lee otro.

> ⚠️ **El ultrasonido no detecta a la gata.** El pelaje absorbe el ultrasonido en lugar de reflejarlo. Su detección viene exclusivamente de la cámara, y `wally-brain` no debe confiar en los HC-SR04 para evitar atropellarla.

---

## 4. Diagrama de conexión

### 4.1 Distribución de energía

```
                      ┌────────────────────┐
                      │  LiPo 2S 7.4V      │
                      │  5500 mAh · 35C    │
                      └──┬──────────────┬──┘
                         │ +            │ −
                    [Fusible 10A]       │
                         │              │
                    [Interruptor]       │        ┌──────────────┐
                         │              │        │ Alarma LiPo  │
                         │              │        │ → al puerto  │
                         │              │        │   de balance │
                         │              │        └──────────────┘
          ┌──────────────┴───┐          │
          │                  │          │
     ┌────┴──────┐    ┌──────┴─────┐    │
     │    BEC    │    │  XL4015    │    │
     │  5V / ≥4A │    │  → 4.8V    │    │
     └────┬──────┘    └──────┬─────┘    │
          │ 5V               │ 4.8V     │
     [Cap 470µF]        [Cap 1000µF]    │
          │                  │          │
          │                  ├──→ TB6612  VM        │
          ├──→ Pi 4  (5V)    ├──→ Servo izq (rojo)  │
          └──→ HC-SR04 VCC   ├──→ Servo der (rojo)  │
                             │                      │
   ══════════════════ MASA COMÚN ═══════════════════┘
   LiPo− · BEC− · XL4015− · Pi GND · TB6612 GND ·
   servos GND · HC-SR04 GND  →  todos unidos
```

La pantalla ya no aparece como rama aparte: al montarse sobre el header toma
3.3V/5V de ahí mismo, no de un cable propio.

> **La masa común no es opcional.** Sin ella las señales lógicas del TB6612 y los ECHO de los ultrasónicos flotan y el comportamiento se vuelve errático e irreproducible.

> **Al alimentar la Pi por los pines 5V del header se evita su polifusible de protección.** Es práctica habitual, pero **nunca conectes a la vez el USB-C y el riel de 5V del GPIO.**

### 4.2 TB6612FNG

```
        TB6612FNG                          Motores Tamiya
   ┌──────────────────────┐
   │ VM   ← 4.8V (XL4015) │
   │ VCC  ← 3.3V (Pi p.1) │
   │ GND  ← masa común    │
   │ STBY ← GPIO19 (p.35) │
   │                      │
   │ PWMA ← GPIO12 (p.32) │      AO1 ──→ ┐ Motor
   │ AIN1 ← GPIO20 (p.38) │      AO2 ──→ ┘ IZQUIERDO
   │ AIN2 ← GPIO21 (p.40) │
   │                      │
   │ PWMB ← GPIO13 (p.33) │      BO1 ──→ ┐ Motor
   │ BIN1 ← GPIO16 (p.36) │      BO2 ──→ ┘ DERECHO
   │ BIN2 ← GPIO26 (p.37) │
   └──────────────────────┘
```

`STBY` debe ir a nivel alto para que el driver funcione. Llevarlo a bajo es la parada de emergencia por hardware: corta ambos motores de inmediato, sin depender del PWM.

### 4.3 Divisor de voltaje para cada ECHO — obligatorio

```
   HC-SR04 ECHO (5V) ──[1 kΩ]──┬──→ GPIO de la Pi
                               │
                            [2 kΩ]
                               │
                              GND

   Vout = 5V × 2kΩ / (1kΩ + 2kΩ) = 3.33V  ✓
```

Uno por sensor: **tres divisores en total**. El TRIG sí se conecta directo (la Pi emite 3.3V y el HC-SR04 lo lee como nivel alto sin problema).

### 4.4 LEDs IR — solo si resultan conmutables

GPIO24 se lo quedó el `DC` de la pantalla (§3), así que la base del 2N2222 va
por un canal del expansor I2C en vez de un GPIO nativo — la señal es
digital lenta (habilita/deshabilita el transistor), así que el expansor no
introduce ningún problema de temporización aquí.

```
              +5V
               │
          [LEDs IR]
               │
               C
  EXPANSOR ─[1kΩ]─ B    2N2222
   (I2C)         E
               │
              GND
```

Nunca conectar los LEDs directo a un GPIO/expansor: superan los 16 mA que tolera el pin.

### 4.5 Tabla de conexión punto a punto

| Desde | Pin BCM | Pin físico | Hacia |
|---|---|---|---|
| Pi | 3.3V | 1 | TB6612 `VCC` |
| Pi | GPIO12 | 32 | TB6612 `PWMA` |
| Pi | GPIO20 | 38 | TB6612 `AIN1` |
| Pi | GPIO21 | 40 | TB6612 `AIN2` |
| Pi | GPIO13 | 33 | TB6612 `PWMB` |
| Pi | GPIO16 | 36 | TB6612 `BIN1` |
| Pi | GPIO26 | 37 | TB6612 `BIN2` |
| Pi | GPIO19 | 35 | TB6612 `STBY` |
| Pi | GPIO18 | 12 | Servo izquierdo (señal) |
| Pi | GPIO23 | 16 | Servo derecho (señal) |
| Pi | GPIO4 | 7 | HC-SR04 frontal `TRIG` |
| Pi | GPIO15 | 10 | HC-SR04 frontal `ECHO` **vía divisor** |
| Pi | GPIO5 | 29 | HC-SR04 izquierdo `TRIG` |
| Pi | GPIO27 | 13 | HC-SR04 izquierdo `ECHO` **vía divisor** |
| Pi | GPIO6 | 31 | HC-SR04 derecho `TRIG` |
| Pi | GPIO22 | 15 | HC-SR04 derecho `ECHO` **vía divisor** |
| Pi | Expansor I2C | — | Base del 2N2222 (LEDs IR) vía 1kΩ |
| Pi | GND | 6, 9, 14, 20, 25, 30, 34, 39 | Masa común |

Además de lo anterior, el bloque SPI0/DC/RST/IRQ de §3 (GPIO7, 8, 9, 10, 11,
17, 24, 25) queda ocupado eléctricamente por la pantalla, que se monta
directo sobre el header de 40 pines — a diferencia de la HDMI original, ya
**no** es una conexión aparte. Su cuerpo también cubre mecánicamente el
resto del header (ver aviso de §3 sobre el cable de extensión GPIO). Solo la
cámara OV5647 (cable plano al puerto **CSI/CAMERA**) y el audio (**jack de
3.5 mm**) siguen sin pasar por el header en absoluto.

### 4.6 Orden de encendido para las primeras pruebas

1. XL4015 **desconectado de todo**: ajustar a 4.8V con multímetro y verificar.
2. Verificar la salida del BEC con multímetro (debe dar 5.0–5.2V bajo carga).
3. Conectar solo la Pi. Comprobar que arranca sin avisos de undervoltage: `vcgencmd get_throttled` debe devolver `0x0`.
4. Añadir el TB6612 **sin motores**. Verificar los niveles lógicos.
5. Conectar los motores con la Pi **alimentada aparte**, para aislar un posible brownout.
6. Solo entonces, unificar en la batería.

---

## 5. Stack tecnológico

| Capa | Elección | Justificación |
|---|---|---|
| Lenguaje | Python 3.11 | Nativo en Bookworm, todo el ecosistema Pi |
| GPIO / PWM | **pigpio** (`pigpiod`) | PWM por DMA, resolución 1 µs, servos sin jitter. Estable en Pi 4 |
| Cámara | **Picamera2** | Único stack soportado en Bookworm para OV5647 |
| Inferencia | **TFLite Runtime** + MobileNet-SSD / EfficientDet-Lite0 | 8–12 FPS a 320×320 con 4 hilos. COCO incluye `cat` |
| Backend | **FastAPI + uvicorn** | WebSocket de control + REST de configuración |
| Video | **MJPEG sobre HTTP** | ~150 ms de latencia, trivial de implementar. WebRTC en v2 |
| Frontend | **React + Vite + TypeScript** | Compilado a estáticos, servido por FastAPI |
| Bus interno | **MQTT (mosquitto local)** | Desacopla servicios; depurable con `mosquitto_sub` |
| TTS | **Piper** | Neural, offline, voces en español, tiempo real en Pi 4 |
| Cara | **Pygame** en framebuffer | Sin escritorio. Pixel art escalado nearest-neighbor |
| Red | **NetworkManager (`nmcli`)** | Nativo en Bookworm, gestiona AP y perfiles sin hacks |
| Supervisión | **systemd** | Un unit por servicio, reinicio automático, logs en journald |

**Descartado:** ROS 2 (sobredimensionado y pesado de instalar en Raspberry Pi OS), navegador en modo kiosk para la cara (competiría por CPU con la visión).

---

## 6. Arquitectura de servicios

Procesos independientes bajo systemd. Un fallo en visión **no puede** dejar los motores encendidos.

```
wally-motion   Único proceso que toca GPIO. Motores, servos, watchdog
wally-vision   Dueño exclusivo de la cámara. Detecciones → MQTT, frames → /dev/shm
wally-face     Pygame a pantalla completa. Suscrito a estados de ánimo
wally-voice    Cola TTS con Piper
wally-brain    Máquina de estados: idle / patrol / follow_cat / teleop
wally-web      FastAPI: webapp, WebSocket, streaming MJPEG, configuración
wally-net      Hotspot ↔ cliente wifi
```

Los frames de vídeo **no viajan por MQTT**: `wally-vision` los escribe en memoria compartida (`/dev/shm`) y `wally-web` los lee de ahí. Evita copias innecesarias.

### Topics MQTT

```
wally/cmd/drive          {"left": -1.0..1.0, "right": -1.0..1.0}
wally/cmd/servo          {"arm_left": 0..180, "arm_right": 0..180}
wally/cmd/say            {"text": "...", "priority": "normal|urgent"}
wally/cmd/mood           {"mood": "idle|happy|curious|alert|sleepy"}
wally/cmd/mode           {"mode": "idle|patrol|follow_cat|teleop"}

wally/state/motion       {"left_pwm":.., "right_pwm":.., "stalled": bool}
wally/state/sensors      {"front_mm":.., "left_mm":.., "right_mm":..}
wally/state/battery      {"volts":.., "pct":..}
wally/vision/detections  [{"label":"cat","conf":0.87,"bbox":[x,y,w,h]}]
wally/vision/cat         {"present": bool, "bbox":[..], "conf":..}
```

### Seguridad: dead-man switch

`wally-motion` **frena si no recibe un `cmd/drive` en 500 ms**. Se cayó el wifi, se cerró la pestaña del navegador, murió `wally-brain` → el robot se detiene. En modo autónomo, `wally-brain` refresca el comando periódicamente aunque no cambie.

Se implementa en la Fase 1, no al final. Es la primera línea de defensa contra un robot descontrolado.

---

## 7. Estructura del repositorio

```
wally/
├── PLAN.md
├── pyproject.toml
├── common/              bus MQTT, config, tipos compartidos
├── services/
│   ├── motion/  vision/  face/  voice/  brain/  web/  net/
├── ui/                  React + Vite
├── models/              .tflite
├── assets/
│   ├── sprites/         pixel art de la cara
│   └── voices/          modelos Piper
├── deploy/
│   ├── systemd/         units
│   └── setup.sh         instalación en la Pi
└── tools/               calibración y pruebas de banco
```

---

## 8. La cara: pixel art retro

Pantalla **3.2" SPI táctil a 320×240**, modelo **MPI3201** (ILI9341 + táctil XPT2046), montada directo sobre el header de 40 pines (sin adaptador ni cable de vídeo aparte).

La baja resolución juega a favor: **renderizo a 160×120 y escalo ×2 con nearest-neighbor**, factor exacto para llenar el panel sin franjas negras (antes era 160×106 ×3 sobre los 480×320 de la HDMI, de aspecto distinto). Píxeles nítidos y cuadrados, coste de CPU casi nulo.

**El táctil sí se conecta**, y con eso cambia la razón de ser de la sección anterior: ya no hay forma de "ahorrarse" esos GPIO montando la pantalla — se pierden se use el táctil o no, así que aprovecharlo no cuesta pines extra. Se usan dos gestos que **no requieren calibrar coordenadas** (solo miden cuánto duró el contacto, no dónde):

- **Toque corto** (<0.6 s): cicla el modo `idle → patrol → follow_cat`, publicando `wally/cmd/mode` (lo mismo que ya consume `wally-brain`).
- **Toque largo** (≥3 s): fuerza el hotspot de red (`wally/cmd/net/hotspot`) — es el botón físico para volver al modo AP que quedaba pendiente en §9.

> **Fricción esperada:** el driver se instala con `goodtft/LCD-show`
> (`sudo ./LCD32-show`, ver README C10), fuera del árbol mainline de
> Raspberry Pi OS — no es un ajuste de `config.txt` como la HDMI.
> Presupuestar una sesión completa para dejarla operativa, y confirmar tras
> instalar si el framebuffer resultante es `/dev/fb0` o `/dev/fb1` (§10).

Estados de ánimo con sprites animados:

| Estado | Disparador |
|---|---|
| `idle` | Reposo. Parpadeo ocasional, micro-movimientos |
| `happy` | Detectó a la gata |
| `curious` | Detectó algo que no reconoce |
| `alert` | Obstáculo cercano o calado de motor |
| `sleepy` | Sin actividad prolongada, o batería baja |
| `teleop` | Bajo control manual |

Pygame escribe directo al framebuffer con SDL, sin escritorio corriendo. Ahorra ~300 MB de RAM y CPU que necesita la visión.

---

## 9. Fases

| # | Fase | Entregable | Depende de |
|---|---|---|---|
| **0** | Energía y bancada | Cableado medido. La Pi no se reinicia con motores al máximo | Componentes en camino |
| **1** | `wally-motion` | ✅ **Código escrito y probado en simulación.** Pendiente de validar con hardware | Fase 0 |
| **2** | `wally-web` + teleoperación | ✅ **Código escrito y probado extremo a extremo.** Joystick y vídeo en el navegador | Fase 1 |
| **3** | `wally-net` | ✅ **Código escrito y probado extremo a extremo** con broker real. Hotspot y configuración de wifi desde la webapp | Fase 2 |
| **4** | `wally-face` + `wally-voice` | ✅ **Código escrito y probado extremo a extremo.** Cara pixel art con 8 ánimos y voz en español | — |
| **5** | `wally-vision` | Detección de objetos y de la gata | — |
| **6** | `wally-brain` | ✅ **Código escrito y probado extremo a extremo.** Patrulla, evita obstáculos y sigue a la gata. Las constantes de navegación quedan pendientes de afinar con el robot montado | Fases 1, 5, sensores |

La **Fase 2 es el primer hito real**: a partir de ahí ya tienes un robot que conduces desde el móvil, y todo lo demás se añade sobre algo que funciona.

### Detalle de la Fase 3 (hotspot)

Al arrancar, `wally-net` comprueba si hay un perfil wifi conocido:
- **Sí** → conecta como cliente. Accesible en `http://wally.local` (mDNS vía Avahi).
- **No, o falla tras 30 s** → levanta AP `Wally-Setup` con `nmcli`. El usuario se conecta, entra a `http://192.168.4.1`, elige red e introduce contraseña. El servicio guarda el perfil y reinicia en modo cliente.

Comando web para forzar el retorno al modo AP si cambias de router, más el toque largo (≥3 s) en la pantalla como botón físico equivalente (§8) — ambos publican `wally/cmd/net/hotspot`.

---

## 10. Pendientes antes de empezar

**Comprar:** UBEC 5V/5A, XL4015 ajustable, alarma de voltaje LiPo, fusible 10A, interruptor, condensadores, resistencias 1kΩ y 2kΩ (×6, para los divisores), transistor 2N2222.

El pinout de la pantalla (§3) y su instalador (`goodtft/LCD-show`, README
C10) ya están confirmados por el datasheet oficial del fabricante — dejan de
ser un pendiente. Sigue quedando por verificar:

**Verificar en el hardware que ya tienes:**

1. Si tras correr `LCD32-show` el framebuffer de la pantalla queda en
   `/dev/fb0` o `/dev/fb1` (`ls /dev/fb*`) — ajustar `fb_device` en
   `config/wally.toml` según lo que aparezca (default actual: `/dev/fb0`).
2. Que el táctil quede calibrado/legible como evento de SDL (`FINGERDOWN` o
   `MOUSEBUTTONDOWN`, ver `services/face/__main__.py`) — los gestos de §8 no
   necesitan calibrar coordenadas, así que basta con que el toque se
   detecte, no con que la posición sea exacta.
3. **LEDs IR de la cámara** — determinar la variante:
   - ¿Salen cables sueltos además del plano CSI? → alimentación separada, **controlables por GPIO** (vía expansor I2C, ver §3/§4.4).
   - ¿Hay una píldora transparente en la placa (LDR)? → automáticos por luz ambiente, sin control por software.
   - Prueba: enciende la cámara a oscuras y mira los LEDs con la cámara de un móvil (el IR se ve como violeta tenue).

Si los IR resultan no conmutables, se elimina esa fila del mapa y la cara nocturna pierde el control de iluminación — sin impacto en el resto del plan. Si resultan conmutables, hace falta el expansor GPIO por I2C (MCP23017 o similar) mencionado en §3 — ya disponible.

### Mejora opcional de sensores

Los 3 HC-SR04 bastan para "detente si hay algo delante". Si en la Fase 6 la navegación resulta torpe, la migración natural es a **VL53L1X** (~USD 5): ToF láser, hasta 4m, I2C sobre los mismos 2 pines para todos los sensores, 3.3V nativo (sin divisores), cono estrecho y 50 Hz. El código abstrae el sensor tras una interfaz `RangeSensor`, así que el cambio es local.

Escalones superiores si el proyecto crece: **TF-Luna** (LiDAR 8m, solo frontal, ~USD 20) o **RPLIDAR A1** (360°, ~USD 100, habilita SLAM y navegación por mapa).

---

## 11. Riesgos identificados

| Riesgo | Mitigación |
|---|---|
| Motores quemados por sobretensión (8.4V vs 3V nominales) | XL4015 a 4.8V + cap de duty al 60 % en software |
| Brownout de la Pi al arrancar motores | Rieles separados (UBEC / XL4015) + condensadores de bulk |
| GPIO dañado por ECHO de 5V del HC-SR04 | Divisores 1kΩ+2kΩ en los 3 ECHO, sin excepción |
| LiPo arruinada por sobredescarga | Alarma física de voltaje + corte por software a 6.6V |
| Crosstalk entre ultrasónicos | Disparo secuencial round-robin, nunca simultáneo |
| **Atropellar a la gata** (el ultrasonido no la detecta) | Detección solo por cámara; velocidad reducida en modo `follow_cat` |
| Visión satura la CPU y ahoga el control | Procesos separados + `nice` favorable a `wally-motion` |
| `LCD32-show` mapea la consola a un framebuffer distinto al asumido (`/dev/fb0`) | `fb_device` es config, no código (`wally.toml`); confirmar con `ls /dev/fb*` tras instalar (§10) |
| El cuerpo de la MPI3201 (tamaño casi igual a la Pi) estorba para cablear el resto del header | Cable de extensión GPIO / breakout, ver aviso de §3 |
| `goodtft/LCD-show` (fuera del árbol mainline) deja de mantenerse o no instala limpio en una Bookworm futura | Presupuestar una sesión, igual que antes con los timings HDMI; el pinout ya está documentado en §3 aunque haya que instalar el driver a mano |
| Robot descontrolado por pérdida de red | Dead-man switch de 500 ms desde la Fase 1 |
| Corrupción de SD por cortes de energía | `fsck` en arranque; considerar overlay de solo lectura en producción |
