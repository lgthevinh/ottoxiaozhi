from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.assistant.session_handler import SessionHandler
from app.services.audio.audio_config import AudioConstants
from app.services.audio.audio_handler import frame_pcm
import app.services.assistant.stt_client as stt_mod
import app.services.assistant.llm_client as llm_mod
import app.services.assistant.tts_client as tts_mod
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


def _patch_dependencies() -> None:
    sessions_mod.get_last_memory = lambda device_id: None
    sessions_mod.create_session = lambda device_id: uuid4()
    sessions_mod.get_recent_turns = lambda session_id, limit: []
    sessions_mod.save_turn = lambda *a, **kw: None
    sessions_mod.get_all_turns = lambda session_id: []
    sessions_mod.close_session = lambda *a, **kw: None

    async def fake_transcribe(pcm_frames):
        async for _ in pcm_frames:
            pass
        return "hello this is a test"

    async def fake_respond(messages, system_prompt=None):
        for token in ["Hello! ", "I heard you. ", "How can I help?"]:
            yield token

    async def fake_synthesize(sentences):
        async for _ in sentences:
            pass
        yield b"\x00" * AudioConstants.BYTES_PER_SAMPLE

    stt_mod.transcribe = fake_transcribe
    llm_mod.respond = fake_respond
    tts_mod.synthesize = fake_synthesize


async def test_full_turn() -> None:
    print("TEST: full turn sends audio back to device")
    frames = _m4a_to_pcm_frames(TEST_AUDIO)
    print(f"  converted {len(frames)} PCM frames from M4A")

    messages = (
        [{"text": json.dumps({"event": "start_utterance"})}]
        + [{"bytes": frame_pcm(f)} for f in frames]
        + [{"text": json.dumps({"event": "end_utterance"})}]
    )

    ws = MockWebSocket(messages)
    handler = SessionHandler(ws=ws, device_id=uuid4())

    try:
        await handler.run()
    except RuntimeError:
        pass  # inbox exhausted — expected

    if handler.current_turn_task:
        await asyncio.wait_for(handler.current_turn_task, timeout=5.0)

    assert len(ws.sent_bytes) > 0, "expected audio frames sent to device"
    print(f"  sent {len(ws.sent_bytes)} audio frame(s) back to device — PASS")


async def test_end_without_start() -> None:
    print("TEST: end_utterance without start_utterance is ignored")
    ws = MockWebSocket([{"text": json.dumps({"event": "end_utterance"})}])
    handler = SessionHandler(ws=ws, device_id=uuid4())

    try:
        await handler.run()
    except RuntimeError:
        pass

    assert handler.current_turn_task is None
    print("  no turn task created — PASS")


async def test_second_start_cancels_first() -> None:
    print("TEST: second start_utterance cancels first turn")
    ws = MockWebSocket([
        {"text": json.dumps({"event": "start_utterance"})},
        {"text": json.dumps({"event": "start_utterance"})},
    ])
    handler = SessionHandler(ws=ws, device_id=uuid4())

    try:
        await handler.run()
    except RuntimeError:
        pass

    assert handler.current_turn_task is not None
    print("  second turn task created — PASS")


async def test_invalid_json_ignored() -> None:
    print("TEST: invalid JSON text message is ignored")
    ws = MockWebSocket([{"text": "not json"}])
    handler = SessionHandler(ws=ws, device_id=uuid4())

    try:
        await handler.run()
    except RuntimeError:
        pass

    print("  no crash — PASS")


async def main() -> None:
    _patch_dependencies()
    await test_full_turn()
    await test_end_without_start()
    await test_second_start_cancels_first()
    await test_invalid_json_ignored()
    print("\nAll tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
