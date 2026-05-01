from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import websockets

API_KEY = os.getenv("STT_API_KEY", "")

async def try_connect(url: str, label: str) -> None:
    print(f"\n--- {label} ---")
    print(f"URL: {url}")
    try:
        async with websockets.connect(url, extra_headers={"xi-api-key": API_KEY}) as ws:
            print("Connected OK")
            # wait for first message
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"First message: {msg}")
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")

async def main() -> None:
    print(f"API key present: {'yes' if API_KEY else 'NO - missing!'}")

    await try_connect(
        "wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=scribe_v1&audio_format=pcm_16000&commit_strategy=manual",
        "full params"
    )
    await try_connect(
        "wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=scribe_v1&audio_format=pcm_16000",
        "no commit_strategy"
    )
    await try_connect(
        "wss://api.elevenlabs.io/v1/speech-to-text/realtime",
        "no params at all"
    )

if __name__ == "__main__":
    asyncio.run(main())
