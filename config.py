from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Lyrics sources (all optional — lrclib.net needs no key)
    musixmatch_api_key: str = ""
    genius_api_key: str = ""

    # Stage 4 + 5
    deepgram_api_key: str = ""
    deepl_api_key: str = ""

    output_dir: Path = Path("output")
    audio_quality: str = "128"
    max_concurrent_downloads: int = 3
    max_concurrent_api_calls: int = 5


settings = Settings()
