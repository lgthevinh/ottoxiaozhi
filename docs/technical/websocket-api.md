# WebSocket API Reference

## Overview

All WebSocket endpoints are under the `/ws` prefix. The primary endpoint `/ws/audio/{device_id}` is the full voice assistant pipeline. The verify and pink endpoints are utility connections for audio hardware testing.

---

## `/ws/audio/{device_id}`

Voice assistant session. One session per device connection. The server runs STT → LLM → TTS for each utterance and streams PCM audio back to the device.

### Connection

```
ws://<host>/ws/audio/<device_id>
```

| Parameter | Type | Description |
|---|---|---|
| `device_id` | UUID | Device identifier |

### Session Lifecycle

```
client connects
    └─ server creates session, loads memory from previous session

client: start_utterance event
    └─ server opens STT stream

client: PCM frames (bytes)
    └─ server pipes frames to STT in real time

client: end_utterance event
    └─ server commits STT stream, awaits final transcript
    └─ server calls LLM with memory + transcript
    └─ server streams TTS audio back to client as framed PCM
    └─ server sends response_complete text event when audio is done

client disconnects
    └─ server summarizes session turns via LLM, saves to DB
```

### Message Format

All binary messages use a 1-byte envelope:

```
[ 0x01 | PCM payload | 0x03 ]
```

| Byte | Value | Description |
|---|---|---|
| First | `0x01` | Packet start marker |
| Middle | raw PCM | 16kHz mono 16-bit PCM data |
| Last | `0x03` | Packet end marker |

### Client → Server Messages

**Binary (PCM audio frames)**

Raw PCM audio wrapped in the packet envelope. Send continuously while button is held.

```
bytes: [ 0x01 ] + <640 bytes PCM> + [ 0x03 ]
```

PCM spec: 16kHz, mono, 16-bit, 20ms frames (320 samples / 640 bytes per frame).

**Text (JSON events)**

```json
{ "event": "start_utterance" }
```
Signals button press. Server opens STT stream. Cancels any in-progress turn.

```json
{ "event": "end_utterance" }
```
Signals button release. Server commits STT stream and triggers the LLM → TTS pipeline.

### Server → Client Messages

**Binary (PCM audio frames)**

TTS response audio, framed identically to incoming audio:

```
bytes: [ 0x01 ] + <PCM chunk> + [ 0x03 ]
```

Chunks arrive as they are synthesized — playback can start before the full response is generated.

**Text (JSON events)**

```json
{ "event": "response_complete" }
```

Signals that the current assistant response has finished and no more PCM chunks will be sent for this turn. The client should stop waiting for audio and may start the next turn.

```json
{ "event": "response_complete", "reason": "empty_transcript" }
```

Signals that the turn finished without response audio because STT did not return a transcript.

```json
{ "event": "response_error", "message": "<error message>" }
```

Signals that the turn failed. The connection can remain open, but the client should treat the current turn as failed.

### Turn Flow

```
client                          server
  │                               │
  │── { "event": "start_utterance" } ──→│  open STT stream
  │                               │
  │══ PCM frames (streaming) ════→│  forward to STT
  │                               │
  │── { "event": "end_utterance" } ───→│  commit STT → transcript
  │                               │  LLM(memory + transcript) → tokens
  │                               │  TTS(tokens) → PCM chunks
  │←══ PCM frames (streaming) ════│  stream audio back
  │←─ { "event": "response_complete" } ─│  response done
  │                               │
  │   (next turn or disconnect)   │
```

### Client Receive Loop

Clients must handle both binary and text messages from the same WebSocket. Binary messages are framed PCM audio. Text messages are JSON events.

Example with Python `websockets`:

```python
import asyncio
import json

async def receive_response(ws):
    pcm_chunks = []

    while True:
        msg = await ws.recv()

        if isinstance(msg, bytes):
            pcm = unframe_pcm(msg)
            if pcm:
                pcm_chunks.append(pcm)
                play_or_buffer(pcm)
            continue

        event = json.loads(msg)
        if event.get("event") == "response_complete":
            break
        if event.get("event") == "response_error":
            raise RuntimeError(event.get("message", "assistant turn failed"))

    return b"".join(pcm_chunks)
```

Do not use a timeout as the normal way to detect response completion. Use `response_complete`; keep a timeout only as a network failure guard.

### Interruption

Sending `start_utterance` while a turn is in progress cancels the current turn immediately and starts a new one.

### Memory

At session start the server loads a text summary of the previous session for this device. This summary is injected into the LLM context. At session end (disconnect) the server summarizes all turns and saves to the database for the next session.

---

## `/ws/audio/verify/{device_mac}`

Hardware audio verification. Sends a pre-recorded verification WAV as framed PCM when triggered.

### Connection

```
ws://<host>/ws/audio/verify/<device_mac>
```

### Client → Server

```
text: "verify"
```

### Server → Client

Framed PCM frames of the verification audio file, sent sequentially.

---

## `/ws/audio/pink/{device_mac}`

Pink noise playback for speaker/microphone hardware testing.

### Connection

```
ws://<host>/ws/audio/pink/<device_mac>
```

### Client → Server

```
text: "pink"
```

### Server → Client

Framed PCM frames of pink noise audio, sent sequentially.

---

## Audio Format

All PCM audio on all endpoints:

| Property | Value |
|---|---|
| Sample rate | 16,000 Hz |
| Channels | 1 (mono) |
| Bit depth | 16-bit signed little-endian |
| Frame duration | 20 ms |
| Samples per frame | 320 |
| Bytes per frame | 640 |
| Packet start marker | `0x01` |
| Packet end marker | `0x03` |

---

## Error Handling

For recoverable turn-level failures, `/ws/audio/{device_id}` sends:

```json
{ "event": "response_error", "message": "<error message>" }
```

The client should stop waiting for audio for that turn. It may start a new turn on the same connection or reconnect.

For an empty STT result, the server sends:

```json
{ "event": "response_complete", "reason": "empty_transcript" }
```

No response audio is sent for that turn.

Malformed packet envelopes (wrong start/end markers) are silently discarded. Invalid JSON text messages are silently discarded. On unrecoverable connection-level errors, the connection may close; the client should reconnect and retry.
