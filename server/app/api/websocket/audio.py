from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.audio import iter_asset_frames
from app.services.assistant.session_handler import SessionHandler


router = APIRouter(prefix="/ws", tags=["websocket"])


@router.websocket("/audio/{device_id}")
async def audio_stream(websocket: WebSocket, device_id: UUID) -> None:
    await websocket.accept()
    handler = SessionHandler(ws=websocket, device_id=device_id)
    await handler.run()


@router.websocket("/audio/verify/{device_mac}")
async def audio_verify(websocket: WebSocket, device_mac: str) -> None:
    await websocket.accept()
    try:
        while True:
            text = await websocket.receive_text()
            if text == "verify":
                for frame in iter_asset_frames("verify"):
                    await websocket.send_bytes(frame)

    except WebSocketDisconnect:
        pass


@router.websocket("/audio/pink/{device_mac}")
async def audio_pink(websocket: WebSocket, device_mac: str) -> None:
    await websocket.accept()
    try:
        while True:
            text = await websocket.receive_text()
            if text == "pink":
                for frame in iter_asset_frames("pink"):
                    await websocket.send_bytes(frame)

    except WebSocketDisconnect:
        pass
