# Otto Xiaozhi Project Specs

This document is a compact handoff reference for AI agents working in this repo.

## Overview

Otto Xiaozhi is a backend API for device-oriented audio streaming and user authentication.

Current capabilities:

- FastAPI HTTP API with health/root endpoints.
- WebSocket audio endpoints for device audio streaming and test audio playback.
- User authentication with public email/password signup, login, and Bearer JWT current-user lookup.
- PostgreSQL schema for users and devices.

There is no frontend application in this repo.

## Tech Stack

- **Language**: Python 3.12 target via Docker image; local development may use newer Python.
- **API framework**: FastAPI.
- **ASGI server**: Uvicorn.
- **Settings/env**: `pydantic-settings` and `.env`.
- **Database**: PostgreSQL, intended to use Neon.
- **DB access**: SQLAlchemy Core.
- **Postgres driver**: `psycopg[binary]` v3; plain `postgresql://` URLs are normalized to `postgresql+psycopg://` in the DB session module.
- **Auth**: JWT via PyJWT, password hashing via `pwdlib[argon2]`.
- **Tests**: pytest, FastAPI TestClient/httpx, websockets.
- **Container**: `server/Dockerfile`, `server/docker-compose.yml`.

## Folder Structure

```text
server/
  app/
    main.py                    # FastAPI app and router registration
    api/
      routes.py                # health/root HTTP endpoints
      auth_routes.py           # thin auth HTTP route wiring
      websocket/audio.py       # device audio WebSocket endpoints
    core/
      config.py                # env-backed settings
      security.py              # password hashing and JWT helpers
    db/
      session.py               # SQLAlchemy engine/session dependency
    repositories/
      users.py                 # SQLAlchemy Core user queries
    schemas/
      auth.py                  # auth request/response schemas
      user.py                  # user response schema
    services/
      auth.py                  # auth business logic
      audio/                   # audio config, handler, session logic
    assets/                    # bundled WAV files for audio verification/pink noise
  db/
    schemas.sql                # current PostgreSQL schema; no migration tool yet
  test/
    test_auth.py               # auth endpoint tests
    test_audio_websocket.py    # WebSocket audio smoke test
  requirements.txt
  .env.example
```

## API And Behavior

HTTP:

- `GET /health` returns server health.
- `GET /` returns a simple server-running message.
- `POST /auth/signup` creates a user with email/password and returns a Bearer JWT.
- `POST /auth/login` verifies email/password and returns a Bearer JWT.
- `GET /auth/me` requires `Authorization: Bearer <token>` and returns the current user.

WebSocket:

- `/ws/audio/{device_mac}` receives framed PCM audio packets.
- `/ws/audio/verify/{device_mac}` sends verification audio when the client sends `verify`.
- `/ws/audio/pink/{device_mac}` sends pink-noise audio when the client sends `pink`.

Audio assumptions:

- PCM audio.
- 16 kHz sample rate.
- Mono channel.
- 16-bit depth.
- 20 ms frames: 320 samples / 640 bytes.

## Database And Configuration

Schema source of truth is `server/db/schemas.sql`.

Core tables:

- `users`: UUID id, optional name, required unique email, password hash, optional unique phone number, millisecond timestamps.
- `devices`: UUID id, owner user id, unique device MAC, device metadata, audio format defaults, last active timestamp, millisecond timestamps.

Required runtime environment:

- `DATABASE_URL`: PostgreSQL connection URL.
- `SECRET_KEY`: long random secret for JWT signing.
- `ACCESS_TOKEN_EXPIRE_MINUTES`: access token lifetime; example default is `30`.

Do not commit real secrets. Use `server/.env.example` only for placeholders.

## Agent Implementation Notes

- Keep route files thin. Put workflow in `services/`, SQL in `repositories/`, security primitives in `core/security.py`, and request/response models in `schemas/`.
- Do not add auth logic directly to route files beyond FastAPI dependency and response wiring.
- There is no Alembic setup. If schema changes are required, update `server/db/schemas.sql` and call out any manual migration needed for existing databases.
- Existing device WebSocket auth is not production-grade; current endpoints trust `device_mac`. Plan device credentials separately before securing WebSocket access.
- Prefer focused tests under `server/test/` for any new behavior.
