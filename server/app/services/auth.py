from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.repositories import users as user_repository
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse
from app.schemas.user import UserResponse


def signup(db: Session, payload: SignupRequest) -> TokenResponse:
    password_hash = hash_password(payload.password)
    try:
        user = user_repository.create_user(
            db,
            email=payload.email,
            password_hash=password_hash,
            name=payload.name,
            phone_number=payload.phone_number,
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        ) from exc

    return _token_response(user["id"], user["email"])


def login(db: Session, payload: LoginRequest) -> TokenResponse:
    user = user_repository.get_user_by_email(db, payload.email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _token_response(user["id"], user["email"])


def get_current_user(db: Session, token: str | None) -> UserResponse:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise ValueError("Token subject is missing")
        user_id = UUID(subject)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = user_repository.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UserResponse.model_validate(user)


def _token_response(user_id: UUID | str, email: str) -> TokenResponse:
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user_id, email),
        expires_in=settings.access_token_expire_minutes * 60,
    )
