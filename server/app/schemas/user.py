from uuid import UUID

from pydantic import BaseModel, EmailStr


class UserResponse(BaseModel):
    id: UUID
    name: str | None = None
    email: EmailStr
    phone_number: str | None = None
    created_at_ms: int | None = None
    updated_at_ms: int | None = None
