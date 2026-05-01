from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from app.db.session import get_session_local


def create_session(device_id: UUID) -> UUID:
    with get_session_local()() as db:
        row = db.execute(
            text("INSERT INTO sessions (device_id) VALUES (:device_id) RETURNING id"),
            {"device_id": str(device_id)},
        ).fetchone()
        db.commit()
        return UUID(str(row.id))


def save_turn(session_id: UUID, role: str, content: str) -> None:
    with get_session_local()() as db:
        db.execute(
            text(
                "INSERT INTO session_turns (session_id, role, content) "
                "VALUES (:session_id, :role, :content)"
            ),
            {"session_id": str(session_id), "role": role, "content": content},
        )
        db.commit()


def get_recent_turns(session_id: UUID, limit: int) -> list[dict]:
    with get_session_local()() as db:
        rows = db.execute(
            text(
                "SELECT role, content FROM session_turns "
                "WHERE session_id = :session_id "
                "ORDER BY created_at_ms DESC LIMIT :limit"
            ),
            {"session_id": str(session_id), "limit": limit},
        ).fetchall()
    # reverse so oldest first for LLM context
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


def get_all_turns(session_id: UUID) -> list[dict]:
    with get_session_local()() as db:
        rows = db.execute(
            text(
                "SELECT role, content FROM session_turns "
                "WHERE session_id = :session_id "
                "ORDER BY created_at_ms ASC"
            ),
            {"session_id": str(session_id)},
        ).fetchall()
    return [{"role": r.role, "content": r.content} for r in rows]


def close_session(session_id: UUID, summary: str) -> None:
    with get_session_local()() as db:
        db.execute(
            text(
                "UPDATE sessions SET ended_at_ms = current_unix_ms(), memory_summary = :summary "
                "WHERE id = :session_id"
            ),
            {"summary": summary, "session_id": str(session_id)},
        )
        db.commit()


def get_last_memory(device_id: UUID) -> str | None:
    with get_session_local()() as db:
        row = db.execute(
            text(
                "SELECT memory_summary FROM sessions "
                "WHERE device_id = :device_id AND memory_summary IS NOT NULL "
                "ORDER BY ended_at_ms DESC LIMIT 1"
            ),
            {"device_id": str(device_id)},
        ).fetchone()
    return row.memory_summary if row else None
