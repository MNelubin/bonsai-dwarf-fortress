from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BONSAI_", case_sensitive=False)

    database_url: str
    lab_token: str
    admin_token: str
    bind_host: str = "127.0.0.1"
    bind_port: int = 8080
    lease_seconds: int = 120
    scheduler_interval_seconds: int = 10
    ollama_url: str = "http://100.96.0.4:11434"
    github_repo: str = ""
    artifact_dir: str = "/srv/bonsai-control/artifacts"
    artifact_max_bytes: int = 268_435_456


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
