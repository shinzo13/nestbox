from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    owner_id: int
    chat_id: int | None = None

    data_dir: Path = Field(default=Path("./data"))
    agents_config: Path = Field(default=Path("./config/agents.toml"))

    usage_warn_threshold: int = 80
    credentials_path: Path = Field(default=Path.home() / ".claude" / ".credentials.json")

    @property
    def sessions_path(self) -> Path:
        return self.data_dir / "sessions.json"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def branches_path(self) -> Path:
        return self.data_dir / "branches.json"

    @property
    def maintenance_lock(self) -> Path:
        """While this file exists, main is handed to a manual terminal session."""
        return self.data_dir / "main.lock"


def load_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
