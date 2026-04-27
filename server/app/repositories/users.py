from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Column, MetaData, String, Table, Uuid, insert, select
from sqlalchemy.orm import Session


metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("name", String(255)),
    Column("email", String(320), nullable=False, unique=True),
    Column("password_hash", String, nullable=False),
    Column("phone_number", String(32), unique=True),
    Column("created_at_ms", BigInteger),
    Column("updated_at_ms", BigInteger),
)


def create_user(
    db: Session,
    *,
    email: str,
    password_hash: str,
    name: str | None = None,
    phone_number: str | None = None,
) -> dict[str, Any]:
    user_id = uuid4()
    statement = (
        insert(users)
        .values(
            id=user_id,
            email=email,
            password_hash=password_hash,
            name=name,
            phone_number=phone_number,
        )
        .returning(users)
    )
    result = db.execute(statement)
    db.commit()
    return dict(result.mappings().one())


def get_user_by_email(db: Session, email: str) -> dict[str, Any] | None:
    statement = select(users).where(users.c.email == email)
    result = db.execute(statement)
    row = result.mappings().one_or_none()
    return dict(row) if row else None


def get_user_by_id(db: Session, user_id: UUID) -> dict[str, Any] | None:
    statement = select(users).where(users.c.id == user_id)
    result = db.execute(statement)
    row = result.mappings().one_or_none()
    return dict(row) if row else None
