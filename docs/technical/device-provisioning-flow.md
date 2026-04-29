# Device Provisioning Flow

## Overview

When a user receives an Otto Xiaozhi device (ESP32-S3), they must go through a one-time provisioning
flow to connect it to their account and the backend service. After provisioning, the device holds a
persistent WebSocket connection to the API for audio streaming.

There is no factory-burned identity. The device gets its identity during the setup flow.

---

## Actors

| Actor | Description |
|-------|-------------|
| User | The person who bought the device |
| Mobile App | iOS/Android app, user is logged in with a JWT |
| ESP32-S3 | The physical device — has BLE and WiFi |
| Backend API | FastAPI server (this repo) |

---

## Provisioning Sequence

```
┌─────────┐         ┌────────────┐        ┌──────────────┐        ┌─────────┐
│  User   │         │ Mobile App │        │ ESP32-S3     │        │   API   │
└────┬────┘         └─────┬──────┘        └──────┬───────┘        └────┬────┘
     │                    │                       │                     │
     │  Tap "Add Device"  │                       │                     │
     │───────────────────>│                       │                     │
     │                    │  POST /devices/register-intent (JWT)        │
     │                    │────────────────────────────────────────────>│
     │                    │<────────────────────────────────────────────│
     │                    │  { device_id,                               │
     │                    │    device_secret,                           │
     │                    │    claim_token }  (5 min TTL)               │
     │                    │                       │                     │
     │                    │  Scan BLE, find "OTTO_XXXX"                 │
     │                    │──────────────────────>│                     │
     │                    │  Connect (BluFi encrypted channel)          │
     │                    │──────────────────────>│                     │
     │                    │  Send:                │                     │
     │                    │  { wifi_ssid,         │                     │
     │                    │    wifi_password,     │                     │
     │                    │    device_id,         │                     │
     │                    │    device_secret,     │                     │
     │                    │    claim_token }      │                     │
     │                    │──────────────────────>│                     │
     │                    │          ACK          │                     │
     │                    │<──────────────────────│                     │
     │                    │                       │                     │
     │  "Connecting..."   │                       │  Save to NVS flash  │
     │<───────────────────│                       │  Reboot, join WiFi  │
     │                    │                       │                     │
     │                    │                       │  POST /devices/provision
     │                    │                       │  { device_id,       │
     │                    │                       │    device_secret,   │
     │                    │                       │    claim_token,     │
     │                    │                       │    mac_address }    │
     │                    │                       │────────────────────>│
     │                    │                       │                     │ verify secret
     │                    │                       │                     │ link to user
     │                    │                       │                     │ mark active
     │                    │                       │<────────────────────│
     │                    │                       │     { ws_url }      │
     │                    │                       │                     │
     │                    │                       │  Save to NVS        │
     │                    │                       │  Connect WebSocket  │
     │                    │                       │  WS /ws/audio/{device_id}
     │                    │                       │────────────────────>│
     │                    │                       │<────────────────────│
     │                    │                       │  Connected          │
     │                    │                       │                     │
     │                    │  GET /devices (poll)  │                     │
     │                    │────────────────────────────────────────────>│
     │                    │<────────────────────────────────────────────│
     │                    │  device status: online│                     │
     │  "Device ready!"   │                       │                     │
     │<───────────────────│                       │                     │
```

---

## Device Boot Logic

On every power-on, the device checks NVS (non-volatile storage) to decide what to do:

```
Power on
   │
   ▼
NVS empty? ──yes──> Enter BLE provisioning mode
   │                Advertise "OTTO_XXXX" and wait for app
   │                Receive credentials over BluFi
   │                Save to NVS, reboot
   │
   no
   │
   ▼
Has ws_url? ──no──> Connect WiFi
   │                POST /devices/provision
   │                Save ws_url to NVS
   │
   yes
   │
   ▼
Connect WiFi
   │
   ▼
Open WebSocket (ws_url)
   │
   ▼
Operating — stream audio
   │
   ▼
Disconnected? ──> Retry with exponential backoff
```

---

## API Contracts

### 1. App requests provisioning credentials

**Request**
```
POST /devices/register-intent
Authorization: Bearer <user JWT>
```

**Response**
```json
{
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_secret": "a3f1c2d4e5b6...",
  "claim_token": "9f8e7d6c...",
  "expires_at": 1714000000000
}
```

- `device_id`: UUID, the permanent identity of this device
- `device_secret`: 32-byte random hex, proves the device received the credentials via BLE
- `claim_token`: 16-byte random hex, proves the app user initiated the flow
- All three expire together after 5 minutes

---

### 2. App sends credentials to device over BLE

Sent over the ESP-BluFi encrypted channel:

```json
{
  "wifi_ssid": "HomeNetwork",
  "wifi_password": "wifipass",
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_secret": "a3f1c2d4e5b6...",
  "claim_token": "9f8e7d6c..."
}
```

---

### 3. Device completes provisioning

**Request**
```
POST /devices/provision
Content-Type: application/json
```
```json
{
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_secret": "a3f1c2d4e5b6...",
  "claim_token": "9f8e7d6c...",
  "mac_address": "AA:BB:CC:DD:EE:FF"
}
```

**Response**
```json
{
  "ws_url": "wss://api.yourdomain.com/ws/audio/550e8400-e29b-41d4-a716-446655440000"
}
```

The device saves `ws_url` to NVS and opens the WebSocket connection immediately.

---

### 4. App polls for device status

**Request**
```
GET /devices
Authorization: Bearer <user JWT>
```

**Response**
```json
[
  {
    "device_id": "550e8400-e29b-41d4-a716-446655440000",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "status": "online",
    "created_at": 1714000000000
  }
]
```

---

## Database Changes Required

```sql
-- New table for short-lived provisioning intents
CREATE TABLE device_intents (
  device_id     UUID PRIMARY KEY,
  device_secret TEXT NOT NULL,
  claim_token   TEXT NOT NULL,
  user_id       UUID NOT NULL REFERENCES users(id),
  expires_at    BIGINT NOT NULL,
  used          BOOLEAN DEFAULT false
);

-- Additions to existing devices table
ALTER TABLE devices ADD COLUMN status TEXT DEFAULT 'unprovisioned';
ALTER TABLE devices ADD COLUMN mac_address TEXT;
```

---

## Security Notes

| Threat | Mitigation |
|--------|------------|
| BLE interception | ESP-BluFi uses ECDH key exchange to encrypt the channel |
| Stolen claim_token | Single-use + 5 min TTL; marked `used=true` after `/provision` |
| MAC spoofing | MAC is stored for reference only; `device_secret` is the proof of identity |
| Replay attack on `/provision` | `claim_token` is single-use, rejected if already used or expired |
| Unauthorized WebSocket access | `device_id` in the WS path must match a provisioned, active device |

---

## BLE Implementation Note (ESP32-S3)

Use the **ESP-IDF WiFi Provisioning Manager** with BLE transport. It handles the BluFi protocol,
ECDH handshake, and WiFi credential delivery. Hook into the custom data callback to receive and
store `device_id`, `device_secret`, and `claim_token` alongside the WiFi credentials.

On first boot (NVS empty): start provisioning manager, advertise as `OTTO_<MAC_SUFFIX>`.
On subsequent boots: skip provisioning manager entirely, connect WiFi and open WebSocket.
