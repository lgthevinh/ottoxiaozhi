from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import WebSocket

from app.repositories import sessions as sessions_repo
from app.services.audio import audio_handler
from app.services.assistant import llm_client, stt_client, tts_client
from app.services.assistant.config import SUMMARY_PROMPT, TURN_WINDOW

_SENTENCE_ENDINGS = {".", "?", "!"}


def _is_sentence_boundary(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in _SENTENCE_ENDINGS


async def _collect_summary(turns: list[dict]) -> str:
    if not turns:
        return ""
    conversation = "\n".join(f"{t['role'].capitalize()}: {t['content']}" for t in turns)
    prompt = f"{SUMMARY_PROMPT}\n\nConversation:\n{conversation}"
    summary = ""
    async for token in llm_client.respond([{"role": "user", "content": prompt}], system_prompt=""):
        summary += token
    return summary.strip()


class SessionHandler:
    def __init__(self, ws: WebSocket, device_id: UUID) -> None:
        self.ws = ws
        self.device_id = device_id
        self.session_id: UUID | None = None
        self.memory_summary: str = ""
        self.pcm_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.current_turn_task: asyncio.Task | None = None

    async def run(self) -> None:
        self.memory_summary = sessions_repo.get_last_memory(self.device_id) or ""
        self.session_id = sessions_repo.create_session(self.device_id)

        try:
            while True:
                message = await self.ws.receive()
                if "bytes" in message:
                    pcm = audio_handler.unframe(message["bytes"])
                    if pcm:
                        await self.pcm_queue.put(pcm)
                elif "text" in message:
                    await self._handle_event(message["text"])
        except Exception:
            pass
        finally:
            await self._on_disconnect()

    async def _handle_event(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return

        name = event.get("event")

        if name == "start_utterance":
            if self.current_turn_task and not self.current_turn_task.done():
                self.current_turn_task.cancel()
            self.pcm_queue = asyncio.Queue()
            self.current_turn_task = asyncio.create_task(self._run_turn())

        elif name == "end_utterance":
            await self.pcm_queue.put(None)

    async def _run_turn(self) -> None:
        async def _queue_iter():
            while True:
                frame = await self.pcm_queue.get()
                if frame is None:
                    return
                yield frame

        try:
            transcript = await stt_client.transcribe(_queue_iter())
            if not transcript:
                return

            recent_turns = sessions_repo.get_recent_turns(self.session_id, TURN_WINDOW)
            messages = self._build_messages(recent_turns, transcript)

            full_response = ""
            sentence_buffer = ""

            async def _sentence_stream():
                nonlocal full_response, sentence_buffer
                async for token in llm_client.respond(messages):
                    full_response += token
                    sentence_buffer += token
                    if _is_sentence_boundary(sentence_buffer):
                        yield sentence_buffer.strip()
                        sentence_buffer = ""
                if sentence_buffer.strip():
                    yield sentence_buffer.strip()
                    sentence_buffer = ""

            async for pcm_chunk in tts_client.synthesize(_sentence_stream()):
                await self.ws.send_bytes(audio_handler.frame_pcm(pcm_chunk))

            sessions_repo.save_turn(self.session_id, "user", transcript)
            sessions_repo.save_turn(self.session_id, "assistant", full_response)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[SessionHandler] turn error for device {self.device_id}: {type(e).__name__}: {e}")

    def _build_messages(self, recent_turns: list[dict], transcript: str) -> list[dict]:
        messages = []
        if self.memory_summary:
            messages.append({
                "role": "user",
                "content": f"[Previous session summary: {self.memory_summary}]",
            })
            messages.append({
                "role": "assistant",
                "content": "Understood, I have context from our previous conversation.",
            })
        messages.extend(recent_turns)
        messages.append({"role": "user", "content": transcript})
        return messages

    async def _on_disconnect(self) -> None:
        if self.current_turn_task and not self.current_turn_task.done():
            try:
                await asyncio.wait_for(self.current_turn_task, timeout=10.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.current_turn_task.cancel()

        if not self.session_id:
            return

        turns = sessions_repo.get_all_turns(self.session_id)
        summary = await _collect_summary(turns)
        sessions_repo.close_session(self.session_id, summary)
