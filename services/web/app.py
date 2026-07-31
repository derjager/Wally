"""wally-web: webapp de teleoperación.

Tres responsabilidades:
  - WebSocket `/ws/control`: joystick del navegador → MQTT `cmd/drive`
  - `/stream.mjpeg`: frames de memoria compartida → navegador
  - WebSocket `/ws/telemetry`: estado del robot → panel

Solo se sirve en la red local (PLAN.md §5). No hay autenticación: cualquiera
en la wifi puede conducir el robot. Es aceptable para una red doméstica, y es
lo que habría que revisar antes de exponerlo por Tailscale.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from common import topics
from common.bus import Bus
from common.config import Config
from common.framebus import FrameReader
from services.web.control import parse_joystick

log = logging.getLogger("web")

UI_DIST = Path(__file__).resolve().parent.parent.parent / "ui" / "dist"
MJPEG_BOUNDARY = "wallyframe"


class RobotState:
    """Última telemetría conocida, alimentada desde MQTT."""

    def __init__(self) -> None:
        self.motion: dict[str, Any] = {}
        self.sensors: dict[str, Any] = {}
        self.net: dict[str, Any] = {}
        self.networks: list[dict[str, Any]] = []
        self.detections: list[dict[str, Any]] = []
        self.cat: dict[str, Any] = {}
        self.updated = 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "motion": self.motion,
            "sensors": self.sensors,
            "detections": self.detections,
            "cat": self.cat,
            "age_s": round(time.monotonic() - self.updated, 2) if self.updated else None,
        }


def create_app(cfg: Config, bus: Bus | None = None) -> FastAPI:
    state = RobotState()
    frames = FrameReader(name=cfg.vision.frame_shm)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        frames.close()

    app = FastAPI(title="Wally", docs_url=None, redoc_url=None, lifespan=lifespan)

    if bus is not None:
        def on_motion(payload: dict[str, Any]) -> None:
            state.motion = payload
            state.updated = time.monotonic()

        def on_sensors(payload: dict[str, Any]) -> None:
            state.sensors = payload
            state.updated = time.monotonic()

        def on_net(payload: dict[str, Any]) -> None:
            state.net = payload

        def on_networks(payload: dict[str, Any]) -> None:
            state.networks = payload.get("networks", [])

        def on_detections(payload: dict[str, Any]) -> None:
            state.detections = payload.get("detections", [])
            state.updated = time.monotonic()

        def on_cat(payload: dict[str, Any]) -> None:
            state.cat = payload

        bus.subscribe(topics.STATE_MOTION, on_motion)
        bus.subscribe(topics.STATE_SENSORS, on_sensors)
        bus.subscribe(topics.NET_STATUS, on_net)
        bus.subscribe(topics.NET_NETWORKS, on_networks)
        bus.subscribe(topics.VISION_DETECTIONS, on_detections)
        bus.subscribe(topics.VISION_CAT, on_cat)

    # -- control ---------------------------------------------------------

    @app.websocket("/ws/control")
    async def ws_control(ws: WebSocket) -> None:
        await ws.accept()
        peer = ws.client.host if ws.client else "?"
        log.info("control conectado desde %s", peer)
        commands = 0
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue

                if msg.get("type") == "estop":
                    if bus is not None:
                        bus.publish(topics.CMD_ESTOP, {"engaged": bool(msg.get("engaged", True))})
                    log.warning("parada de emergencia desde %s: %s", peer, msg.get("engaged"))
                    continue

                if msg.get("type") == "servo":
                    if bus is not None:
                        payload = {
                            k: v for k, v in msg.items() if k in ("arm_left", "arm_right")
                        }
                        if payload:
                            bus.publish(topics.CMD_SERVO, payload)
                    continue

                cmd = parse_joystick(msg)
                if cmd is None:
                    continue
                if bus is not None:
                    bus.publish(topics.CMD_DRIVE, cmd.as_payload())
                commands += 1
        except WebSocketDisconnect:
            log.info("control desconectado (%s, %d comandos)", peer, commands)
        except Exception:
            log.exception("error en el websocket de control")
        finally:
            # No se publica una parada aquí a propósito: dejar de hablar ya
            # detiene al robot vía watchdog, y un publish final podría llegar
            # después de que otro cliente tomara el control.
            pass

    # -- telemetría ------------------------------------------------------

    @app.websocket("/ws/telemetry")
    async def ws_telemetry(ws: WebSocket) -> None:
        await ws.accept()
        period = 1.0 / cfg.web.telemetry_hz
        try:
            while True:
                await ws.send_json(state.snapshot())
                await asyncio.sleep(period)
        except (WebSocketDisconnect, RuntimeError):
            pass

    # -- vídeo -----------------------------------------------------------

    async def mjpeg_stream():
        period = 1.0 / cfg.web.mjpeg_fps
        last_seq = -1
        idle_logged = False
        while True:
            item = frames.read()
            if item is None:
                if not idle_logged:
                    log.info("sin frames disponibles (¿wally-vision está corriendo?)")
                    idle_logged = True
                await asyncio.sleep(0.5)
                continue
            idle_logged = False

            seq, jpeg = item
            if seq != last_seq:
                last_seq = seq
                yield (
                    f"--{MJPEG_BOUNDARY}\r\n"
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg)}\r\n\r\n"
                ).encode() + jpeg + b"\r\n"
            await asyncio.sleep(period)

    @app.get("/stream.mjpeg")
    async def stream() -> StreamingResponse:
        return StreamingResponse(
            mjpeg_stream(),
            media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/snapshot.jpg")
    async def snapshot():
        item = frames.read()
        if item is None:
            return {"error": "sin frames"}
        return StreamingResponse(iter([item[1]]), media_type="image/jpeg")

    # -- API -------------------------------------------------------------

    @app.get("/api/state")
    async def api_state() -> dict[str, Any]:
        return state.snapshot()

    # -- red -------------------------------------------------------------
    #
    # wally-web solo hace de mensajero: wally-net corre como root y es quien
    # toca NetworkManager. Así la webapp, expuesta a la red, no necesita
    # privilegios.

    @app.get("/api/net/status")
    async def net_status() -> dict[str, Any]:
        return state.net or {"mode": "unknown"}

    @app.get("/api/net/networks")
    async def net_networks() -> dict[str, Any]:
        return {"networks": state.networks}

    @app.post("/api/net/scan")
    async def net_scan() -> dict[str, Any]:
        if bus is not None:
            bus.publish(topics.CMD_NET_SCAN, {})
        return {"ok": True}

    @app.post("/api/net/connect")
    async def net_connect(body: dict[str, Any]) -> dict[str, Any]:
        ssid = str(body.get("ssid", "")).strip()
        if not ssid:
            return {"ok": False, "error": "falta el ssid"}
        if bus is not None:
            bus.publish(
                topics.CMD_NET_CONNECT,
                {"ssid": ssid, "password": body.get("password", "")},
            )
        # La conexión tarda y corta la red actual: el cliente debe sondear
        # /api/net/status, no esperar aquí una respuesta que quizá no llegue.
        return {"ok": True, "pending": True}

    @app.post("/api/net/hotspot")
    async def net_hotspot() -> dict[str, Any]:
        if bus is not None:
            bus.publish(topics.CMD_NET_HOTSPOT, {})
        return {"ok": True}

    @app.post("/api/net/forget")
    async def net_forget(body: dict[str, Any]) -> dict[str, Any]:
        ssid = str(body.get("ssid", "")).strip()
        if ssid and bus is not None:
            bus.publish(topics.CMD_NET_FORGET, {"ssid": ssid})
        return {"ok": bool(ssid)}

    @app.get("/api/health")
    async def api_health() -> dict[str, Any]:
        age = frames.age_s()
        return {
            "ok": True,
            "video": frames.read() is not None,
            # Si crece sin parar, wally-vision está vivo pero no captura.
            "video_age_s": round(age, 2) if age is not None else None,
            "watchdog_ms": cfg.motion.watchdog_ms,
            "control_hz": cfg.web.control_hz,
        }

    # -- UI --------------------------------------------------------------

    if UI_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(UI_DIST / "index.html")
    else:
        @app.get("/")
        async def index_missing() -> dict[str, str]:
            return {
                "error": "la UI no está compilada",
                "fix": "cd ui && npm install && npm run build",
            }

    return app
