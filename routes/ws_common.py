"""
Shared WebSocket helpers for streaming state and video, plus a simple command
endpoint. Usable by both backend and Pi roles; payload shape depends on the
event_state provided.
"""

import asyncio
import json

try:
    from websockets.exceptions import ConnectionClosed  # type: ignore
    import websockets  # type: ignore
except ImportError as exc:  # pragma: no cover - optional dependency
    raise ImportError(
        "websockets package is required for the WebSocket servers. "
        "Install with: pip install websockets"
    ) from exc

# Universal state WebSocket server
async def start_state_ws(
    payload_builder,
    *,
    host: str = "0.0.0.0",
    port: int = 8765,
    interval: float = 0.2,
):
    async def handler(websocket):  # noqa: ANN001
        await _state_stream(websocket, interval, payload_builder)

    print(f"[router] WebSocket serving state on ws://{host}:{port}")
    async with websockets.serve(handler, host, port):
        await asyncio.Future()  # run forever


async def _state_stream(websocket, interval: float, payload_builder) -> None:
    try:
        while True:
            try:
                payload = payload_builder()
            except Exception:
                payload = None
            if payload is not None:
                try:
                    await websocket.send(json.dumps(payload))
                except ConnectionClosed:
                    break
                except Exception as exc:
                    print(f"[router] State WS send failed: {exc}")
                    break
            await asyncio.sleep(interval)
    except ConnectionClosed:
        return

# Function for backend bridging to frontend video WS
async def start_video_ws(
    get_jpeg_callable,
    host: str = "0.0.0.0",
    port: int = 8890,
    interval: float = 0.1,
    send_timeout: float = 0.2,
):
    async def handler(websocket):
        while True:
            jpg = get_jpeg_callable()
            if jpg:
                try:
                    await asyncio.wait_for(websocket.send(jpg), timeout=send_timeout)
                except asyncio.TimeoutError:
                    # Drop frame if client is slow; do not accumulate lag.
                    continue
                except Exception:
                    break
            await asyncio.sleep(interval)

    print(f"[router] WebSocket video on ws://{host}:{port}")
    async with websockets.serve(handler, host, port, max_size=None):
        await asyncio.Future()
