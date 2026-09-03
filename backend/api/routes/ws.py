"""WebSocket live stream: system state + agent traces + telemetry source status."""

from __future__ import annotations

import asyncio
import contextlib
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.api.deps import get_platform
from backend.config import get_settings
from backend.observability import get_logger

router = APIRouter(tags=["stream"])
log = get_logger("causalguard.ws")


@router.websocket("/ws/telemetry")
async def telemetry_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    platform = get_platform(websocket)  # type: ignore[arg-type]
    interval = max(0.5, get_settings().telemetry.stream_interval_seconds)
    log.info(
        "ws client connected", extra={"client": websocket.client.host if websocket.client else "-"}
    )

    async def push() -> None:
        state = await platform.get_system_state()
        status = await platform.telemetry_status()
        await websocket.send_json(
            {
                "type": "tick",
                "ts": time.time(),
                "scenario": platform.scenario,
                "state": state,
                "telemetry_source": status.model_dump(),
                "agent_steps": platform.agent_traces()[-12:],
            }
        )

    async def listen() -> None:
        # Allow the client to force an immediate refresh or change nothing.
        while True:
            msg = await websocket.receive_text()
            if msg.strip().lower() in ("refresh", "ping", "now"):
                await push()

    try:
        await push()
        listener = asyncio.create_task(listen())
        try:
            while True:
                await asyncio.sleep(interval)
                await push()
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
    except WebSocketDisconnect:
        log.info("ws client disconnected")
    except Exception as exc:
        log.warning("ws stream error", extra={"error": str(exc)})
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
