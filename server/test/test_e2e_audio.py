from __future__ import annotations

import asyncio
import json
import struct
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.core.config as _config_mod
_config_mod.get_settings.cache_clear()

from app.services.assistant.session_handler import SessionHandler
from app.services.audio.audio_config import AudioConstants
from app.services.audio.audio_handler import frame_pcm, unframe
import app.repositories.sessions as sessions_mod

ASSETS_DIR = Path(__file__).parent / "assets"
TEST_AUDIO = ASSETS_DIR / "Test STT_1.m4a"
OUTPUT_WAV = ASSETS_DIR / "test_response.wav"


def _m4a_to_pcm_frames(path: Path) -> list[bytes]:
    result = subprocess.run(
        [
            "ffmpeg", "-i", str(path),
            "-f", "s16le",
            "-ar", str(AudioConstants.SAMPLE_RATE),
            "-ac", str(AudioConstants.CHANNELS),
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    raw = result.stdout
    frame_size = AudioConstants.BYTES_PER_SAMPLE
    return [raw[i:i + frame_size] for i in range(0, len(raw) - frame_size + 1, frame_size)]


def _pcm_to_wav(pcm_data: bytes, output_path: Path) -> None:
    sample_rate = AudioConstants.SAMPLE_RATE
    channels = AudioConstants.CHANNELS
    bits = AudioConstants.BITS_PER_SAMPLE
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    data_size = len(pcm_data)
    chunk_size = 36 + data_size

    with open(output_path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", chunk_size))
        f.write(b"WAVE")
        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))           # chunk size
        f.write(struct.pack("<H", 1))            # PCM format
        f.write(struct.pack("<H", channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits))
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm_data)


class RecordingWebSocket:
    """MockWebSocket that unframes and collects all received PCM bytes."""

    def __init__(self, messages: list) -> None:
        self._inbox = iter(messages)
        self._pcm_chunks: list[bytes] = []

    async def receive(self) -> dict:
        try:
            return next(self._inbox)
        except StopIteration:
            raise RuntimeError("inbox exhausted")

    async def send_bytes(self, data: bytes) -> None:
        pcm = unframe(data)
        if pcm:
            self._pcm_chunks.append(pcm)

    def collected_pcm(self) -> bytes:
        return b"".join(self._pcm_chunks)


def _patch_db() -> None:
    sessions_mod.get_last_memory = lambda device_id: None
    sessions_mod.create_session = lambda device_id: uuid4()
    sessions_mod.get_recent_turns = lambda session_id, limit: []
    sessions_mod.save_turn = lambda *a, **kw: None
    sessions_mod.get_all_turns = lambda session_id: []
    sessions_mod.close_session = lambda *a, **kw: None


async def test_e2e_audio() -> None:
    print("=" * 60)
    print("E2E: WebSocket → STT → LLM → TTS → WAV file")
    print("=" * 60)

    frames = _m4a_to_pcm_frames(TEST_AUDIO)
    print(f"[INPUT]  {TEST_AUDIO.name} → {len(frames)} PCM frames")

    messages = (
        [{"text": json.dumps({"event": "start_utterance"})}]
        + [{"bytes": frame_pcm(f)} for f in frames]
        + [{"text": json.dumps({"event": "end_utterance"})}]
    )

    ws = RecordingWebSocket(messages)
    handler = SessionHandler(ws=ws, device_id=uuid4())

    try:
        await handler.run()
    except RuntimeError:
        pass  # inbox exhausted

    pcm = ws.collected_pcm()
    print(f"[OUTPUT] received {len(pcm)} PCM bytes ({len(pcm) / (AudioConstants.SAMPLE_RATE * 2):.2f}s of audio)")

    if not pcm:
        print("ERROR: no audio received from pipeline")
        sys.exit(1)

    _pcm_to_wav(pcm, OUTPUT_WAV)
    print(f"[WAV]    saved to {OUTPUT_WAV}")
    print("PASS")


async def main() -> None:
    _patch_db()
    await test_e2e_audio()


if __name__ == "__main__":
    asyncio.run(main())
