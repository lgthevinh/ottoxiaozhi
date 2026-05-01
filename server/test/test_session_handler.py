from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

# load env and clear settings cache before any app imports touch get_settings()
from dotenv import load_dotenv
load_dotenv()

import app.core.config as _config_mod
_config_mod.get_settings.cache_clear()

from app.services.assistant.session_handler import SessionHandler
from app.services.audio.audio_config import AudioConstants
from app.services.audio.audio_handler import frame_pcm
import app.repositories.sessions as sessions_mod

ASSETS_DIR = Path(__file__).parent / "assets"
TEST_AUDIO = ASSETS_DIR / "Test STT_1.m4a"


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


class MockWebSocket:
    def __init__(self, messages: list) -> None:
        self._inbox = iter(messages)
        self.sent_bytes: list[bytes] = []

    async def receive(self) -> dict:
        try:
            return next(self._inbox)
        except StopIteration:
            raise RuntimeError("inbox exhausted")

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)
        print(f"  [DEVICE] received PCM chunk: {len(data)} bytes")


def _patch_db() -> None:
    """Patch only DB calls — STT/LLM/TTS use real clients."""
    sessions_mod.get_last_memory = lambda device_id: None
    sessions_mod.create_session = lambda device_id: uuid4()
    sessions_mod.get_recent_turns = lambda session_id, limit: []
    sessions_mod.save_turn = lambda *a, **kw: None
    sessions_mod.get_all_turns = lambda session_id: []
    sessions_mod.close_session = lambda *a, **kw: None


async def test_full_turn_e2e() -> None:
    print("=" * 60)
    print("E2E TEST: full turn with real STT, LLM, TTS")
    print("=" * 60)

    frames = _m4a_to_pcm_frames(TEST_AUDIO)
    print(f"[AUDIO] converted {len(frames)} PCM frames from {TEST_AUDIO.name}")

    messages = (
        [{"text": json.dumps({"event": "start_utterance"})}]
        + [{"bytes": frame_pcm(f)} for f in frames]
        + [{"text": json.dumps({"event": "end_utterance"})}]
    )

    ws = MockWebSocket(messages)
    handler = SessionHandler(ws=ws, device_id=uuid4())

    # Monkey-patch STT/LLM/TTS to add logging while still calling real implementations
    import app.services.assistant.stt_client as stt_mod
    import app.services.assistant.llm_client as llm_mod
    import app.services.assistant.tts_client as tts_mod

    _real_transcribe = stt_mod.transcribe
    _real_respond = llm_mod.respond
    _real_synthesize = tts_mod.synthesize

    async def logged_transcribe(pcm_frames):
        print("[STT] streaming PCM to ElevenLabs...")
        result = await _real_transcribe(pcm_frames)
        print(f"[STT] transcript: '{result}'")
        return result

    async def logged_respond(messages, system_prompt=None):
        print(f"[LLM] sending {len(messages)} messages, streaming response...")
        full = ""
        async for token in _real_respond(messages, system_prompt=system_prompt):
            full += token
            print(f"[LLM] token: {repr(token)}")
            yield token
        print(f"[LLM] full response: '{full}'")

    async def _logged_sentences(sentences):
        async for sentence in sentences:
            print(f"[TTS] got sentence: {repr(sentence)}")
            yield sentence

    async def logged_synthesize(sentences):
        chunk_count = 0
        async for pcm in _real_synthesize(_logged_sentences(sentences)):
            chunk_count += 1
            yield pcm
        print(f"[TTS] synthesized {chunk_count} PCM chunk(s)")

    stt_mod.transcribe = logged_transcribe
    llm_mod.respond = logged_respond
    tts_mod.synthesize = logged_synthesize

    try:
        await handler.run()
    except RuntimeError:
        pass  # inbox exhausted — expected
    finally:
        stt_mod.transcribe = _real_transcribe
        llm_mod.respond = _real_respond
        tts_mod.synthesize = _real_synthesize

    print(f"\n[RESULT] {len(ws.sent_bytes)} PCM frame(s) sent back to device")
    assert len(ws.sent_bytes) > 0, "expected audio frames sent to device"
    print("PASS")


async def main() -> None:
    _patch_db()
    await test_full_turn_e2e()


if __name__ == "__main__":
    asyncio.run(main())
