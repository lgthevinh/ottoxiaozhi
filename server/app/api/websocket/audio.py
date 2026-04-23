from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.audio.audio_config import AudioConstants
from app.services.audio import AudioHandler


router = APIRouter(prefix="/ws", tags=["websocket"])
audio_handler = AudioHandler()


@router.websocket("/audio/{device_mac}")
async def audio_stream(websocket: WebSocket, device_mac: str) -> None:
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_bytes()
            if data[0] == AudioConstants.PACKET_START and data[-1] == AudioConstants.PACKET_END:
                pcm_data = data[1:-1]
                audio_handler._process_audio_chunk(pcm_data)
            
    except WebSocketDisconnect:
        print("Websocket disconnected")
        
@router.websocket("/audio/verify/{device_mac}")
async def audio_verify(websocket: WebSocket, device_mac: str) -> None:
    await websocket.accept()
    try:
        while True:
            text = await websocket.receive_text()
            print(f"Received text: {text}")
            if text == "verify":
                verify_bytes = audio_handler.send_verify_audio(session_id=device_mac)
                for chunk in verify_bytes:
                    await websocket.send_bytes(chunk)
                print("Sent all verify audio chunks")
                print("Audio verification successful")
                                
    except WebSocketDisconnect:
        print("Websocket disconnected")

@router.websocket("/audio/pink/{device_mac}")
async def audio_pink(websocket: WebSocket, device_mac: str) -> None:
    await websocket.accept()
    try:
        while True:
            text = await websocket.receive_text()
            print(f"Received pink: {text}")
            if text == "pink":
                pink_bytes = audio_handler.send_pink_audio(session_id=device_mac)
                for chunk in pink_bytes:
                    await websocket.send_bytes(chunk)
                print("Sent all pink audio chunks")
                print("Audio verification successful")
                
    except WebSocketDisconnect:
        print("Websocket disconnected")