from __future__ import annotations

import asyncio
import json
import struct
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import websockets

ASSETS_DIR = Path(__file__).parent / "assets"
TEST_AUDIO = ASSETS_DIR / "Test STT_1.m4a"
OUTPUT_WAV = ASSETS_DIR / "test_response.wav"

BASE_URL = "ws://localhost:8000"
DEVICE_ID = str(uuid4())

PACKET_START = 0x01
PACKET_END = 0x03
SAMPLE_RATE = 16000
CHANNELS = 1
BITS = 16
BYTES_PER_FRAME = (BITS // 8) * CHANNELS * (SAMPLE_RATE * 20 // 1000)  # 640


def _m4a_to_pcm_frames(path: Path) -> list[bytes]:
    result = subprocess.run(
        ["ffmpeg", "-i", str(path), "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "pipe:1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    raw = result.stdout
    return [raw[i:i + BYTES_PER_FRAME] for i in range(0, len(raw) - BYTES_PER_FRAME + 1, BYTES_PER_FRAME)]


def _frame(pcm: bytes) -> bytes:
    return bytes([PACKET_START]) + pcm + bytes([PACKET_END])


def _unframe(data: bytes) -> bytes | None:
    if len(data) < 3 or data[0] != PACKET_START or data[-1] != PACKET_END:
        return None
    return data[1:-1]


def _write_wav(pcm: bytes, path: Path) -> None:
    byte_rate = SAMPLE_RATE * CHANNELS * BITS // 8
    block_align = CHANNELS * BITS // 8
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(pcm)))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, CHANNELS, SAMPLE_RATE, byte_rate, block_align, BITS))
        f.write(b"data")
        f.write(struct.pack("<I", len(pcm)))
        f.write(pcm)


async def run() -> None:
    url = f"{BASE_URL}/ws/audio/{DEVICE_ID}"
    print("=" * 60)
    print(f"E2E WebSocket test")
    print(f"Server : {url}")
    print(f"Input  : {TEST_AUDIO.name}")
    print("=" * 60)

    frames = _m4a_to_pcm_frames(TEST_AUDIO)
    print(f"[INPUT]  converted {len(frames)} PCM frames from M4A")

    pcm_received: list[bytes] = []

    async with websockets.connect(url) as ws:
        print(f"[WS]     connected")

        # signal start
        await ws.send(json.dumps({"event": "start_utterance"}))
        print(f"[WS]     sent start_utterance")

        # stream PCM frames
        for frame in frames:
            await ws.send(_frame(frame))
        print(f"[WS]     sent {len(frames)} PCM frames")

        # signal end
        await ws.send(json.dumps({"event": "end_utterance"}))
        print(f"[WS]     sent end_utterance, waiting for audio response...")

        # collect audio response until connection closes or timeout
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                if isinstance(msg, bytes):
                    pcm = _unframe(msg)
                    if pcm:
                        pcm_received.append(pcm)
                        print(f"[WS]     received PCM chunk: {len(pcm)} bytes (total: {sum(len(c) for c in pcm_received)})")
        except asyncio.TimeoutError:
            print("[WS]     timeout waiting for more audio — assuming done")
        except websockets.exceptions.ConnectionClosed:
            print("[WS]     connection closed by server")

    if not pcm_received:
        print("ERROR: no audio received")
        sys.exit(1)

    pcm_all = b"".join(pcm_received)
    duration = len(pcm_all) / (SAMPLE_RATE * CHANNELS * BITS // 8)
    print(f"\n[OUTPUT] {len(pcm_all)} bytes — {duration:.2f}s of audio")

    _write_wav(pcm_all, OUTPUT_WAV)
    print(f"[WAV]    saved → {OUTPUT_WAV}")
    print("PASS")


if __name__ == "__main__":
    asyncio.run(run())
