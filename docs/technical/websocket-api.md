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
  │                               │
  │   (next turn or disconnect)   │
```

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

The server does not send structured error messages over the WebSocket. On unrecoverable error the connection is closed. The client should reconnect and retry.

Malformed packet envelopes (wrong start/end markers) are silently discarded.
Invalid JSON text messages are silently discarded.
