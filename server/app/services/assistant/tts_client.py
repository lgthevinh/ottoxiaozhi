from __future__ import annotations

import asyncio
import base64
import json
from typing import AsyncIterator

import websockets

from app.core.config import get_settings
from app.services.assistant.config import (
    TTS_URL,
    TTS_VOICE_ID,
    TTS_MODEL,
    TTS_OUTPUT_FORMAT,
    TTS_CHUNK_LENGTH_SCHEDULE,
)


async def synthesize(sentences: AsyncIterator[str]) -> AsyncIterator[bytes]:
    api_key = get_settings().tts_api_key
    url = (
        TTS_URL.format(voice_id=TTS_VOICE_ID)
        + f"?model_id={TTS_MODEL}&output_format={TTS_OUTPUT_FORMAT}"
    )

    async with websockets.connect(url, extra_headers={"xi-api-key": api_key}) as ws:
        # initialize connection
        await ws.send(json.dumps({
            "text": " ",
            "generation_config": {"chunk_length_schedule": TTS_CHUNK_LENGTH_SCHEDULE},
        }))

        # feed sentences from LLM, track the last one for flush
        send_queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def _feed() -> None:
            prev: str | None = None
            async for sentence in sentences:
                if prev is not None:
                    await ws.send(json.dumps({"text": prev + " "}))
                prev = sentence
            # last sentence gets flush: true
            if prev is not None:
                await ws.send(json.dumps({"text": prev + " ", "flush": True}))
            else:
                await ws.send(json.dumps({"text": " ", "flush": True}))
            await ws.send(json.dumps({"text": ""}))  # CloseConnection

        feed_task = asyncio.create_task(_feed())

        try:
            async for raw in ws:
                msg = json.loads(raw)
                if "audio" in msg and msg["audio"]:
                    yield base64.b64decode(msg["audio"])
                if msg.get("isFinal"):
                    break
        finally:
            feed_task.cancel()
