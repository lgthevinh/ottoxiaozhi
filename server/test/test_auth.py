from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.repositories.users import metadata, users


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("SECRET_KEY", "test_secret_key")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    get_settings.cache_clear()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_signup_returns_bearer_token_and_hashes_password(client: TestClient) -> None:
    response = client.post(
        "/auth/signup",
        json={
            "email": "user@example.com",
            "password": "correct-password",
            "name": "Test User",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] == 1800

    db = next(app.dependency_overrides[get_db]())
    row = db.execute(select(users).where(users.c.email == "user@example.com")).mappings().one()
    assert row["password_hash"] != "correct-password"
    assert row["password_hash"]


def test_duplicate_signup_email_returns_conflict(client: TestClient) -> None:
    payload = {"email": "user@example.com", "password": "correct-password"}
    first_response = client.post("/auth/signup", json=payload)
    second_response = client.post("/auth/signup", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_login_returns_bearer_token(client: TestClient) -> None:
    client.post("/auth/signup", json={"email": "user@example.com", "password": "correct-password"})

    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "correct-password"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_rejects_wrong_password(client: TestClient) -> None:
    client.post("/auth/signup", json={"email": "user@example.com", "password": "correct-password"})

    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_me_returns_current_user_with_valid_token(client: TestClient) -> None:
    signup_response = client.post(
        "/auth/signup",
        json={"email": "user@example.com", "password": "correct-password", "name": "Test User"},
    )
    token = signup_response.json()["access_token"]

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert UUID(body["id"])
    assert body["email"] == "user@example.com"
    assert body["name"] == "Test User"


def test_me_rejects_missing_invalid_and_expired_tokens(client: TestClient) -> None:
    missing_response = client.get("/auth/me")
    invalid_response = client.get("/auth/me", headers={"Authorization": "Bearer invalid-token"})

    expired_token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000000",
            "email": "user@example.com",
            "iat": int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
            "exp": datetime.now(UTC) - timedelta(hours=1),
        },
        "test_secret_key",
        algorithm="HS256",
    )
    expired_response = client.get("/auth/me", headers={"Authorization": f"Bearer {expired_token}"})

    assert missing_response.status_code == 401
    assert invalid_response.status_code == 401
    assert expired_response.status_code == 401
