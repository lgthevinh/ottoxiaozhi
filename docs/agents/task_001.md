# Research and draft draft design about otto xiaozhi server

## Note
- 04-27-2026: Filled the initial architecture research draft for the Otto Xiaozhi hybrid voice server.

## Task Description
Research and draft architecture about the server for otto-xiaozhi hybrid. The server connect to the device over websocket to handle audio streaming, and then connect to STT, TTS and LLM service, providing the device AI assistant over speech. The server should be able to handle audio streaming from device, streaming to STT services and receive text, and then pass to the LLM service, collecting text response, and pass to TTS service. The receiving WAV files, convert to PCM and stream down to the device

## Requirements
- Provide techstack option to the project (not the service)
- Reseach C1 and C2 components
- Reseach about concepts of how to handle concurrent audio streaming, converting WAV to PCM concurrently

## Output (agent response content here)

### Executive Summary

Otto Xiaozhi should be built as a realtime voice gateway. The device connects to the server over WebSocket, streams microphone audio to the server, and receives playback audio from the server. The server manages device sessions, packet framing, audio conversion, STT streaming, LLM orchestration, TTS streaming, and backpressure.

The server should keep device protocol logic separate from AI provider logic. STT, LLM, and TTS providers should be implemented as replaceable adapters so the project can change providers without changing the WebSocket protocol.

The current project audio contract is:

- Format: PCM
- Sample rate: 16 kHz
- Channels: mono
- Bit depth: 16-bit
- Frame duration: 20 ms
- Samples per frame: 320
- Bytes per frame: 640
- Transport: WebSocket

### Project Tech Stack Options

#### Recommended Stack

- Python 3.12+
- FastAPI for HTTP and WebSocket endpoints
- Uvicorn as the ASGI runtime
- `asyncio` for realtime concurrent session pipelines
- `asyncio.Queue` for bounded handoff between audio receive, STT, LLM, TTS, conversion, and device send tasks
- Pydantic for settings, schema validation, and internal event models
- `httpx` for outbound HTTP provider APIs
- `websockets` or provider SDKs for outbound WebSocket streaming APIs
- FFmpeg/libswresample for audio resampling, remixing, and sample-format conversion
- Docker Compose for local development
- Redis only when shared session registry, multi-worker routing, pub/sub, or distributed locks are required
- Celery/RQ only for offline jobs such as recording persistence, transcript storage, batch conversion, and analytics

This stack matches the existing project direction because the repo already uses FastAPI and Python. The realtime path should stay in `asyncio`, not Celery, because speech interaction needs low latency and direct backpressure control.

#### Minimal Development Stack

- FastAPI
- Uvicorn
- In-memory session registry
- Pure `asyncio` tasks and queues
- Mock STT/LLM/TTS adapters

Use this stack first to validate audio protocol, session lifecycle, and local tests before adding Redis or production deployment complexity.

#### Production-Oriented Stack

- FastAPI behind Nginx or a cloud load balancer
- Uvicorn with a controlled worker count
- Redis for cross-worker session metadata and control messages
- Object storage for optional recordings
- Structured logs, metrics, and tracing
- Background worker service for non-realtime jobs

When multiple workers are used, a WebSocket connection remains owned by the worker that accepted it. External commands for that session need routing metadata so the command reaches the correct worker.

### C1: System Context

At C1 level, Otto Xiaozhi is a voice AI system where the Otto Xiaozhi server is the central integration point between embedded devices and external AI services.

```text
                         +----------------------+
                         |  Observability       |
                         |  logs/metrics/traces |
                         +----------^-----------+
                                    |
                                    |
+----------+     speaks      +------+-------+     PCM frames      +----------------------+
| End User | --------------> | Xiaozhi      | ------------------> | Otto Xiaozhi Server |
|          | <-------------- | Device       | <------------------ |                      |
+----------+   plays audio   +--------------+   PCM playback     +----+------+-----+----+
                                                                        |      |     |
                                                                        |      |     |
                                                              audio     |      |     | text
                                                                        v      v     v
                                                                 +------+  +---+--+  +------+
                                                                 | STT  |  | LLM |  | TTS  |
                                                                 +--+---+  +---+-+  +--+---+
                                                                    |          |       |
                                                                    +----------+-------+
                                                                            AI services

Optional storage receives transcripts, recordings, and device/session metadata when enabled.
```

External actors and systems:

- End user: speaks to the device and hears the assistant response.
- Otto Xiaozhi device: captures microphone audio, sends PCM frames, receives PCM playback frames.
- Otto Xiaozhi server: owns realtime session management and AI orchestration.
- STT service: receives streamed PCM audio and returns partial/final transcripts.
- LLM service: receives transcript plus context and returns assistant text.
- TTS service: receives assistant text and returns synthesized speech audio.
- Observability system: stores logs, metrics, traces, and failure diagnostics.
- Optional persistence layer: stores device metadata, transcripts, conversation history, recordings, and audit data.

Context flow:

1. User speaks into the Otto Xiaozhi device.
2. Device captures audio as 16 kHz mono 16-bit PCM.
3. Device opens a WebSocket connection to the server.
4. Device sends framed PCM audio to the server.
5. Server validates packet framing and streams audio to STT.
6. STT returns transcript events.
7. Server sends final user text and conversation context to the LLM.
8. LLM streams assistant text back to the server.
9. Server streams assistant text to TTS.
10. TTS returns audio bytes.
11. Server converts TTS output to 16 kHz mono 16-bit PCM if needed.
12. Server slices PCM into 640-byte frames, wraps packets, and sends them to the device.
13. Device plays the assistant response.

### C2: Container and Component Design

At C2 level, the system can start as one FastAPI service split into internal modules. These modules can become separate services later if scale requires it.

```text
+--------------------------------------------------------------------------------+
|                         Otto Xiaozhi FastAPI Server                             |
|                                                                                |
|  Device WebSocket                                                              |
|        |                                                                       |
|        v                                                                       |
|  +-------------+     +-----------------+     +-----------------------------+   |
|  | WebSocket   | --> | Session Manager | --> | Session Pipeline Supervisor |   |
|  | API         |     +-----------------+     +---------------+-------------+   |
|  +------+------+                                           |                 |
|         ^                                                  |                 |
|         |                                                  v                 |
|  +------+---------+     +----------------------+     +-------------+         |
|  | Outbound Audio | <-- | Audio Framing/Codec | <-- | TTS Adapter | <--- TTS |
|  | Sender         |     +----------+-----------+     +------+------+         |
|  +----------------+                ^                        ^                |
|                                    |                        | text           |
|                                    |                        |                |
|                              +-----+------+          +------+---------+      |
|                              | STT Adapter| -------> | Dialogue      |      |
|                              +-----+------+ transcript| Orchestrator |      |
|                                    |                 +------+--------+      |
|                                    v                        |               |
|                                   STT                       v               |
|                                                            LLM              |
|                                                                                |
|  Observability hooks collect logs, metrics, queue depth, latency, and errors.  |
+--------------------------------------------------------------------------------+

Optional Redis sits beside the server for multi-worker session metadata and routing.
```

#### WebSocket API

Responsibilities:

- Accept device WebSocket connections.
- Authenticate or identify `device_id`.
- Receive binary audio packets.
- Send binary playback packets.
- Detect disconnects and trigger session cleanup.

This component should not contain STT, LLM, or TTS provider-specific code.

#### Session Manager

Responsibilities:

- Create one audio session per connected device.
- Track `session_id`, `device_id`, created time, frame counts, queue depth, and state.
- Start and cancel per-session tasks.
- Clean up provider connections and queues after disconnect.

The session manager owns lifecycle and cancellation.

#### Audio Framing and Codec Module

Responsibilities:

- Validate packet start/end markers.
- Extract PCM payloads from device packets.
- Buffer partial frames if needed.
- Enforce the 640-byte frame size for outgoing device audio.
- Convert WAV/provider audio to 16 kHz mono 16-bit PCM.
- Split outgoing PCM into 20 ms frames.

This module should have strong unit tests because it protects the device protocol.

#### STT Adapter

Responsibilities:

- Open a streaming STT connection for each active conversation.
- Send incoming PCM frames to the STT provider.
- Receive partial and final transcript events.
- Normalize provider events into internal `TranscriptEvent` objects.
- Surface provider failures without crashing the WebSocket task.

#### Dialogue Orchestrator

Responsibilities:

- Consume final transcript events.
- Decide when a user turn is complete.
- Apply barge-in and cancellation rules.
- Build LLM input from transcript and context.
- Stream LLM output to the TTS stage.

Turn-taking policy should live here, not in the WebSocket handler.

#### LLM Adapter

Responsibilities:

- Hide the selected LLM provider API.
- Send prompt/context and receive assistant response.
- Prefer streaming response chunks.
- Apply timeout, retry, and error mapping policies.

#### TTS Adapter

Responsibilities:

- Consume assistant text chunks.
- Stream text to the TTS provider.
- Receive synthesized audio.
- Return audio plus metadata such as encoding, sample rate, channels, and bit depth.
- Support cancellation when the user interrupts.

#### Outbound Audio Sender

Responsibilities:

- Consume synthesized audio chunks.
- Convert audio to the device PCM contract when needed.
- Slice converted PCM into 640-byte frames.
- Wrap each frame with packet delimiters.
- Send playback packets to the device.
- Apply backpressure if device sending is slower than TTS generation.

#### Observability

Responsibilities:

- Emit structured logs with `session_id` and `device_id`.
- Track received frames, sent frames, queue depths, dropped frames, STT latency, LLM latency, TTS latency, conversion errors, provider errors, and disconnect reasons.

### Concurrent Audio Streaming Design

Each WebSocket connection should create one supervisor coroutine. The supervisor owns child tasks and bounded queues for that session.

```text
One connected device creates one supervised pipeline:

  Device microphone
        |
        v
  receive_device_audio
        |
        |  validated PCM frames
        v
  incoming_audio_queue
        |
        v
  stream_audio_to_stt  --->  STT provider
        |                         |
        |                         | transcript events
        v                         v
  receive_stt_events  --->  transcript_queue
                                  |
                                  v
                            run_dialogue  --->  LLM provider
                                  |
                                  | assistant text chunks
                                  v
                            tts_text_queue
                                  |
                                  v
                            stream_tts  --->  TTS provider
                                  |
                                  | synthesized audio chunks
                                  v
                            outgoing_audio_queue
                                  |
                                  v
                            send_device_audio
                                  |
                                  | convert to 16 kHz mono PCM
                                  | slice into 640-byte frames
                                  v
                            Device speaker
```

Recommended per-session queues:

- `incoming_audio_queue`: PCM frames from device waiting for STT.
- `transcript_queue`: transcript events waiting for dialogue handling.
- `tts_text_queue`: assistant text waiting for TTS.
- `outgoing_audio_queue`: synthesized audio waiting for conversion/framing/send.
- `control_queue`: cancellation, timeout, barge-in, and close events.

Recommended per-session tasks:

- `receive_device_audio`: reads WebSocket packets, validates framing, extracts PCM, and pushes audio frames to `incoming_audio_queue`.
- `stream_audio_to_stt`: consumes `incoming_audio_queue` and writes PCM frames to the STT provider.
- `receive_stt_events`: reads STT provider events and pushes final transcripts to `transcript_queue`.
- `run_dialogue`: consumes transcripts, calls the LLM adapter, and streams assistant text into `tts_text_queue`.
- `stream_tts`: consumes assistant text, calls TTS, and pushes generated audio into `outgoing_audio_queue`.
- `send_device_audio`: consumes generated audio, converts/fragments it, and writes playback packets to the device WebSocket.

The supervisor cancels all child tasks when the device disconnects, authentication fails, the session times out, the server shuts down, or an unrecoverable provider error occurs.

### Backpressure Policy

All realtime queues should have finite `maxsize`. Unbounded queues hide latency problems and can exhaust memory when a provider stalls.

Recommended policies:

- Microphone input: block briefly, then drop oldest frames if STT cannot keep up.
- Transcript events: preserve order and avoid dropping final transcripts.
- LLM text chunks: preserve order within one assistant turn.
- TTS/playback audio: slow generation before dropping audio, because playback gaps are user-visible.
- Control events: never drop cancellation or close events.

### Low-Latency Response Strategy

To make the device feel like it answers in one to two seconds, the system must stream every stage instead of waiting for complete files or complete responses.

Low-latency pipeline:

```text
Device microphone
  -> send 20 ms PCM frames immediately
  -> server streams frames to STT immediately
  -> STT returns partial/final text while user is speaking
  -> server detects end of user turn quickly
  -> LLM starts as soon as the turn is likely complete
  -> TTS starts as soon as the first useful LLM text chunk is available
  -> server streams PCM playback frames back to the device
  -> device starts playback while later audio is still being generated
```

Main techniques:

- Use streaming STT. Send audio continuously in 20 ms frames or small 40-100 ms batches. Do not wait for a complete recorded file.
- Use fast end-of-turn detection. Combine VAD, silence detection, and STT endpointing. A practical target is detecting the end of speech after 300-700 ms of silence.
- Stream LLM output. Do not wait for a full assistant response. Start TTS after the first stable phrase or sentence.
- Stream TTS output. Prefer a TTS provider that returns audio chunks as synthesis progresses. Do not wait for a full WAV before playback.
- Keep the live audio format native. Prefer providers that accept or return 16 kHz mono 16-bit PCM to avoid conversion cost in the hot path.
- Keep prompts and context compact. Long prompts delay first LLM tokens.
- Use a small playback jitter buffer. A 100-300 ms buffer can smooth network jitter without making the assistant feel slow.
- Run receive, STT, LLM, TTS, conversion, and send work concurrently as separate per-session tasks.
- Send a short first response when useful. A brief first phrase can reduce perceived latency while the full answer continues streaming.

Example perceived-latency budget:

```text
End-of-turn detection:        300-700 ms
STT finalization:             100-400 ms
LLM first tokens:             200-800 ms
TTS first audio chunk:        200-700 ms
Network and jitter buffer:    100-300 ms

Expected response start:      about 1-2 seconds
```

Design rule: never use a full-recording request/response path for the realtime conversation. The device should stream audio while the user speaks, and the server should stream the assistant audio back while generation is still in progress.

### Barge-In and Turn Cancellation

The server should eventually support user interruption. If user speech starts while assistant audio is still playing:

1. Stop sending queued assistant audio.
2. Cancel active TTS work.
3. Cancel or ignore active LLM streaming output.
4. Keep STT listening active.
5. Start a new user turn.

This prevents the assistant from speaking over the user and keeps the conversation responsive.

### WAV to PCM Conversion

The device should only receive 16 kHz mono signed 16-bit PCM sliced into 20 ms frames.

Conversion rules:

1. Parse WAV metadata: encoding, channels, sample rate, bits per sample, and data chunk size.
2. If the WAV already matches 16 kHz mono 16-bit PCM, strip the WAV header and stream the data chunk directly.
3. If the WAV differs, use FFmpeg/libswresample or an equivalent audio library to resample, remix, and convert sample format.
4. Avoid loading long audio responses fully into memory. Stream conversion output when possible.
5. Slice converted PCM into 640-byte frames.
6. If the final frame is shorter than 640 bytes, pad it with zero bytes for silence unless the device protocol explicitly supports short final frames.

Concurrency options for conversion:

- For short clips, use `asyncio.to_thread()` around blocking conversion.
- For streaming TTS output, run FFmpeg as an async subprocess and read converted PCM from stdout.
- For high traffic, use a bounded conversion worker pool so CPU-heavy conversion cannot block WebSocket receive loops.

### Entity Planning

The first version should keep the realtime session entities in memory and persist only stable business entities when needed. Do not persist raw audio by default unless product, privacy, and storage requirements are clear.

#### Core Domain Entities

```text
User
  owns zero or more Devices

Device
  opens many AudioSessions over time

AudioSession
  contains many ConversationTurns
  owns live queues, frame counters, and provider connections

ConversationTurn
  contains user TranscriptSegments
  contains one AssistantResponse

AssistantResponse
  contains text chunks
  produces synthesized AudioChunks

ProviderRequest
  records STT, LLM, and TTS calls for diagnostics

AudioAsset
  represents optional stored recordings or generated audio files
```

#### Entity List

##### User

Represents the person who owns or uses one or more devices.

Key fields:

- `id`
- `display_name`
- `locale`
- `timezone`
- `created_at`
- `updated_at`

Early project note: this can be deferred if devices do not need real user accounts yet. Start with `device_id` as the main identity.

##### Device

Represents a physical Otto Xiaozhi device.

Key fields:

- `id`
- `device_mac`
- `name`
- `owner_user_id`
- `firmware_version`
- `audio_sample_rate`
- `audio_channels`
- `audio_bit_depth`
- `last_seen_at`
- `created_at`
- `updated_at`

Important constraints:

- `device_mac` should be unique.
- The server should not trust `device_mac` alone for production auth. Add device credentials later.

##### DeviceCredential

Represents authentication material for a device.

Key fields:

- `id`
- `device_id`
- `credential_type`
- `public_key` or `token_hash`
- `status`
- `created_at`
- `revoked_at`

Early project note: this can be a placeholder until auth requirements are defined.

##### AudioSession

Represents one live WebSocket connection from one device.

Key fields:

- `id`
- `device_id`
- `status`
- `started_at`
- `ended_at`
- `disconnect_reason`
- `received_frame_count`
- `sent_frame_count`
- `received_pcm_bytes`
- `sent_pcm_bytes`
- `current_turn_id`

Runtime-only fields:

- `incoming_audio_queue`
- `transcript_queue`
- `tts_text_queue`
- `outgoing_audio_queue`
- `control_queue`
- `provider_connections`
- `active_tasks`

Persistence note: persist summary fields only if diagnostics need it. Queues and live task handles are runtime-only.

##### Conversation

Represents a longer logical conversation across one or more audio sessions.

Key fields:

- `id`
- `device_id`
- `user_id`
- `started_at`
- `ended_at`
- `summary`
- `status`

Early project note: defer this if each WebSocket session can be treated as one short conversation.

##### ConversationTurn

Represents one user request and one assistant response.

Key fields:

- `id`
- `session_id`
- `conversation_id`
- `turn_index`
- `status`
- `started_at`
- `user_speech_started_at`
- `user_speech_ended_at`
- `assistant_started_at`
- `assistant_ended_at`
- `cancelled_reason`

Statuses:

- `listening`
- `transcribing`
- `thinking`
- `speaking`
- `cancelled`
- `completed`
- `failed`

##### TranscriptSegment

Represents text from STT.

Key fields:

- `id`
- `turn_id`
- `provider`
- `text`
- `is_final`
- `start_ms`
- `end_ms`
- `confidence`
- `created_at`

Early project note: persist final transcripts first. Partial transcripts can remain runtime-only unless debugging needs them.

##### AssistantResponse

Represents the assistant answer for a turn.

Key fields:

- `id`
- `turn_id`
- `provider`
- `model`
- `final_text`
- `status`
- `first_token_at`
- `completed_at`
- `error_message`

Runtime-only fields:

- streamed text chunks
- active cancellation token

##### AudioChunk

Represents a chunk of audio moving through the live pipeline.

Key fields:

- `session_id`
- `turn_id`
- `direction`
- `sequence_number`
- `pcm_bytes`
- `sample_rate`
- `channels`
- `bit_depth`
- `duration_ms`
- `created_at`

Persistence note: this should usually be runtime-only. Persisting every audio chunk would create a large storage and privacy burden.

##### AudioAsset

Represents an optional stored audio file, such as a saved user recording, generated TTS response, or test fixture.

Key fields:

- `id`
- `session_id`
- `turn_id`
- `asset_type`
- `storage_uri`
- `sample_rate`
- `channels`
- `bit_depth`
- `duration_ms`
- `byte_size`
- `created_at`

##### ProviderRequest

Represents one outbound request to STT, LLM, or TTS.

Key fields:

- `id`
- `session_id`
- `turn_id`
- `provider_type`
- `provider_name`
- `model`
- `status`
- `started_at`
- `first_result_at`
- `ended_at`
- `latency_ms`
- `error_code`
- `error_message`

This entity is useful for debugging latency and provider reliability.

##### SessionMetric

Represents summarized metrics for a session or turn.

Key fields:

- `id`
- `session_id`
- `turn_id`
- `metric_name`
- `metric_value`
- `unit`
- `created_at`

Useful metrics:

- `stt_first_partial_ms`
- `stt_final_ms`
- `llm_first_token_ms`
- `tts_first_audio_ms`
- `response_start_ms`
- `incoming_queue_max_depth`
- `outgoing_queue_max_depth`
- `dropped_audio_frames`

#### Suggested First Implementation Scope

For the first implementation, create Python dataclasses or Pydantic models for:

- `Device`
- `AudioSession`
- `ConversationTurn`
- `TranscriptSegment`
- `AssistantResponse`
- `AudioFrame`
- `SynthAudioChunk`
- `ProviderRequest`

Defer database persistence until the realtime pipeline is working. The first persistent table, if needed, should be `Device`. The second should be `ProviderRequest` or `SessionMetric` because latency debugging will become important quickly.

### Suggested Internal Events

Provider adapters should convert provider-specific data into internal events:

- `AudioFrame(session_id, index, pcm_bytes, timestamp)`
- `TranscriptEvent(session_id, text, is_final, start_ms, end_ms)`
- `AssistantTextChunk(session_id, turn_id, text, is_final)`
- `SynthAudioChunk(session_id, turn_id, audio_bytes, sample_rate, channels, encoding)`
- `TurnStarted(session_id, turn_id, speaker)`
- `TurnCancelled(session_id, turn_id, reason)`
- `SessionClosed(session_id, reason)`

This keeps the core pipeline independent from provider payload formats.

### Implementation Roadmap

1. Keep the current FastAPI project structure.
2. Split audio code into framing, conversion, session, and pipeline modules.
3. Add unit tests for packet framing and WAV-to-PCM extraction.
4. Add a mock STT/LLM/TTS pipeline for deterministic local testing.
5. Implement per-session supervisor tasks and bounded queues.
6. Add real provider adapters behind interfaces.
7. Add structured logs and latency metrics.
8. Add Redis only when multiple Uvicorn workers or external session commands are required.
9. Add production deployment settings after the single-worker realtime flow is reliable.

### Sources (for reference only, not part of the final output)
- FastAPI WebSocket documentation: https://fastapi.tiangolo.com/advanced/websockets/
- Python `asyncio` documentation: https://docs.python.org/3/library/asyncio.html
- Python `asyncio.Queue` documentation: https://docs.python.org/3/library/asyncio-queue.html
- Uvicorn deployment documentation: https://www.uvicorn.org/deployment/
- FFmpeg resampler documentation: https://ffmpeg.org/ffmpeg-resampler.html
- Celery introduction: https://docs.celeryq.dev/en/main/getting-started/introduction.html
- OpenAI Realtime API documentation: https://platform.openai.com/docs/guides/realtime
