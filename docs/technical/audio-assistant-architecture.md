# Audio Assistant Architecture

## Overview

When a device connects via WebSocket, the server runs a full voice assistant pipeline: streaming STT → LLM (token stream) → sentence-boundary TTS → PCM back to device. Short memory is carried across turns within a session; a summary is persisted to the database when the session ends.

## Folder Structure

```text
server/app/
  services/
    audio/                          # device PCM framing (existing)
      audio_config.py               # audio constants
      audio_handler.py              # stateless: frame/unframe PCM, load WAV assets
      __init__.py

    assistant/                      # assistant pipeline (new)
      orchestrator.py               # one instance per WS connection; owns DeviceSession, drives turns
      device_session.py             # DeviceSession dataclass — ws ref, STT stream, turn state, history
      pipeline.py                   # pure async fn: run_turn(session, clients, memory_repo)
      stt_client.py                 # streaming STT provider wrapper
      tts_client.py                 # TTS provider wrapper, yields PCM chunks
      llm_client.py                 # LLM provider wrapper, yields text tokens
      memory.py                     # load/save short memory per device
      __init__.py

  repositories/
    users.py                        # existing
    sessions.py                     # session/turn DB queries (new)

  schemas/
    auth.py                         # existing
    user.py                         # existing
    assistant.py                    # Turn, MemorySummary shapes (new)

  api/
    websocket/
      audio.py                      # thin: accept WS, instantiate orchestrator, hand off
```

## Ownership Model

```
AssistantOrchestrator  (one per WS connection)
  │
  ├── DeviceSession
  │     ├── ws: WebSocket              # owns the connection reference
  │     ├── device_id: str
  │     ├── session_id: UUID
  │     ├── state: idle | listening | processing
  │     ├── stt_connection: STTStream | None   # open during listening, None otherwise
  │     ├── turn_transcript: str               # final STT output, held for LLM
  │     ├── turn_history: list[Turn]           # sliding window of current session turns
  │     └── memory_summary: str               # loaded once at session start from DB
  │
  ├── AudioHandler  (stateless singleton)
  │     ├── unframe(data) → bytes | None       # strip 0x01/0x03 envelope, validate
  │     ├── frame_pcm(pcm) → bytes             # wrap raw PCM for device
  │     └── assets: dict[str, bytes]           # verify/pink WAVs, loaded at startup
  │
  └── injected clients
        ├── stt_client
        ├── llm_client
        └── tts_client
```

## Data Flow

```
WS connect
  → AssistantOrchestrator created
  → DeviceSession initialized
  → memory_summary loaded from DB

device: {"event": "start_utterance"}
  → session.stt_connection = stt_client.open_stream()
  → session.state = listening

device: PCM frame (bytes)
  → audio_handler.unframe(data) → raw PCM
  → session.stt_connection.send(pcm_frame)     # piped directly, no local buffer

device: {"event": "end_utterance"}             # button released
  → session.stt_connection.close()             # signal end of audio to STT
  → await stt_connection.final_transcript()    # drain, wait for final result
  → session.turn_transcript = transcript
  → session.state = processing

pipeline.run_turn(session, clients, memory_repo)
  → build prompt: memory_summary + turn_history (sliding window) + transcript
  → async for token in llm_client.respond(prompt):
        token_buffer += token
        if sentence_boundary(token_buffer):
            sentence = flush(token_buffer)
            async for pcm_chunk in tts_client.synthesize(sentence):
                await session.ws.send_bytes(audio_handler.frame_pcm(pcm_chunk))
  → session.turn_history.append(Turn("user", transcript), Turn("assistant", full_response))
  → save turns to DB
  → session.state = idle

WS disconnect
  → summarize session.turn_history → save to sessions.memory_summary in DB
  → mark session ended_at
```

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `audio/audio_handler.py` | Stateless framing only: `frame_pcm`, `unframe`, load WAV assets at startup |
| `assistant/orchestrator.py` | Creates `DeviceSession`, drives the WS receive loop, delegates turns to pipeline |
| `assistant/device_session.py` | Dataclass holding all per-connection state: ws, STT stream, transcript, turn history, memory |
| `assistant/pipeline.py` | Pure async fn: takes session + clients, runs STT drain → LLM stream → sentence TTS → send |
| `assistant/stt_client.py` | `open_stream() → STTStream`; stream has `send(pcm)`, `close()`, `final_transcript()` |
| `assistant/tts_client.py` | `synthesize(text: str) -> AsyncIterator[bytes]` (raw PCM) |
| `assistant/llm_client.py` | `respond(prompt: str) -> AsyncIterator[str]` (token stream) |
| `assistant/memory.py` | `load_memory(device_id, db) -> str`, `save_turns(session_id, turns, db)`, `summarize(turns) -> str` |
| `repositories/sessions.py` | Raw SQLAlchemy Core queries for sessions and session_turns |

## Turn Lifecycle Detail

```
idle
 │
 │  {"event": "start_utterance"}
 ▼
listening  ←── PCM frames streaming to STT WebSocket
 │
 │  {"event": "end_utterance"}  (button released)
 ▼
processing
 │  STT drains → final transcript
 │  LLM streams tokens → sentence boundaries → TTS → PCM → device
 ▼
idle
```

## Sentence Boundary TTS

LLM tokens are accumulated in a buffer. On detecting a sentence boundary (`.`, `?`, `!` followed by whitespace or end of stream), the sentence is flushed to TTS immediately. PCM chunks stream to the device while the LLM continues generating the next sentence.

This minimizes time-to-first-audio: device starts playing the first sentence before the LLM finishes the full response.

## Turn History (Sliding Window)

`turn_history` on `DeviceSession` holds the last N turn pairs (user + assistant) for the current session. Older turns are dropped to keep LLM context bounded. The full turn list is persisted to `session_turns` in the DB regardless of the window — the window only controls what is sent to the LLM.

Window size is configurable; default N = 10 turns (5 exchanges).

## Database Schema

```sql
CREATE TABLE sessions (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id      UUID NOT NULL REFERENCES devices(id),
  started_at     BIGINT NOT NULL,
  ended_at       BIGINT,
  memory_summary TEXT
);

CREATE TABLE session_turns (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES sessions(id),
  role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content    TEXT NOT NULL,
  created_at BIGINT NOT NULL
);
```

## Memory Shape

Short memory passed to the LLM is a plain text summary generated at session close:

```
Previous session summary:
User asked about the weather and set a reminder for 9am. Assistant confirmed both.
```

LLM prompt structure per turn:

```
[system prompt]
[short memory summary from last session, if any]
[sliding window of current session turns]
[current user transcript]
```

## Audio Format Contract

All PCM exchanged between device and server uses the existing spec:
- 16 kHz sample rate
- Mono channel
- 16-bit depth
- 20 ms frames: 320 samples / 640 bytes

TTS output must be resampled to match this spec before framing and sending to device.

## Configuration (to add to .env)

```
STT_PROVIDER=           # e.g. openai
STT_API_KEY=
TTS_PROVIDER=           # e.g. openai
TTS_API_KEY=
LLM_PROVIDER=           # e.g. openai / anthropic
LLM_API_KEY=
LLM_MODEL=
ASSISTANT_TURN_WINDOW=10
```
