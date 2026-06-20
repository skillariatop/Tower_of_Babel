from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Discord
    discord_token: str
    discord_guild_id: int

    # GitHub
    github_token: str
    github_repo: str = "skillariatop/Tower_of_Babel"

    # LLM
    llm_provider: str = "openrouter"
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    # Storage
    database_url: str = "sqlite+aiosqlite:///./data/tower.db"
    decisions_dir: Path = Path("./decisions")

    # Vote defaults
    routine_duration_hours: int = 24
    significant_duration_hours: int = 48
    critical_duration_hours: int = 72
    routine_quorum: int = 3           # minimum absolute votes
    significant_quorum_pct: float = 0.5
    critical_quorum_pct: float = 0.5

    # Misc
    log_level: str = Field(default="INFO")

    # Channel names (resolved to IDs at startup)
    voting_channel_name: str = "voting"
    audit_channel_name: str = "audit-log"
    tasks_channel_name: str = "tasks"
    announcements_channel_name: str = "announcements"


settings = Settings()  # type: ignore[call-arg]
