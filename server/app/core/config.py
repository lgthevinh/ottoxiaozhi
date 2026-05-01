from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = ""
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    stt_api_key: str = ""
    tts_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
