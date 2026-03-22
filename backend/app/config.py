from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_db_url: str
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    data_dir: Path = Path("./sap-o2c-data")
    allowed_origin: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
