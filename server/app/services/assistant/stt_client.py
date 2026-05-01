from __future__ import annotations

import asyncio
import base64
import json
from typing import AsyncIterator

import websockets

from app.core.config import get_settings
from app.services.audio.audio_config import AudioConstants
from app.services.assistant.config import STT_MODEL, STT_URL

_TERMINAL_ERROR_TYPES = {
    "error",
    "auth_error",
    "quota_exceeded",
    "rate_limited",
    "queue_overflow",
    "resource_exhausted",
    "session_time_limit_exceeded",
    "input_error",
    "chunk_size_exceeded",
    "insufficient_audio_activity",
    "transcriber_error",
    "unaccepted_terms",
    "commit_throttled",
}


class STTError(Exception):
    pass


async def transcribe(pcm_frames: AsyncIterator[bytes]) -> str:
    api_key = get_settings().stt_api_key
    url = (
        f"{STT_URL}"
        f"?model_id={STT_MODEL}"
        f"&audio_format=pcm_{AudioConstants.SAMPLE_RATE}"
        f"&commit_strategy=manual"
    )

    async with websockets.connect(url, extra_headers={"xi-api-key": api_key}) as ws:
        transcript: asyncio.Future[str] = asyncio.get_event_loop().create_future()

        async def _sender() -> None:
            prev: bytes | None = None
            async for pcm in pcm_frames:
                if prev is not None:
                    await ws.send(json.dumps({
                        "message_type": "input_audio_chunk",
                        "audio_base_64": base64.b64encode(prev).decode(),
                        "commit": False,
                        "sample_rate": AudioConstants.SAMPLE_RATE,
                    }))
                prev = pcm
            # send last frame with commit: true
            if prev is not None:
                await ws.send(json.dumps({
                    "message_type": "input_audio_chunk",
                    "audio_base_64": base64.b64encode(prev).decode(),
                    "commit": True,
                    "sample_rate": AudioConstants.SAMPLE_RATE,
                }))

        async def _receiver() -> None:
            async for raw in ws:
                msg = json.loads(raw)
                msg_type = msg.get("message_type")

                if msg_type == "committed_transcript":
                    transcript.set_result(msg.get("text", ""))
                    return

                if msg_type in _TERMINAL_ERROR_TYPES:
                    transcript.set_exception(STTError(msg.get("error", msg_type)))
                    return

        sender = asyncio.create_task(_sender())
        receiver = asyncio.create_task(_receiver())

        try:
            await asyncio.gather(sender, receiver)
        except Exception:
            sender.cancel()
            receiver.cancel()
            raise

        return await transcript
