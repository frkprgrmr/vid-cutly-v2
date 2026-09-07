from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    root_dir: Path = ROOT_DIR
    data_dir: Path = Path(os.getenv("APP_DATA_DIR", ROOT_DIR / "data")).resolve()
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    host: str = os.getenv("APP_HOST", "127.0.0.1")
    port: int = int(os.getenv("APP_PORT", "8000"))
    video_max_height: int = int(os.getenv("VIDEO_MAX_HEIGHT", "1080"))
    reframe_speaker_window_seconds: float = float(
        os.getenv("REFRAME_SPEAKER_WINDOW_SECONDS", "1.2")
    )
    reframe_speaker_min_confidence: float = float(
        os.getenv("REFRAME_SPEAKER_MIN_CONFIDENCE", "0.10")
    )
    reframe_speaker_switch_margin: float = float(
        os.getenv("REFRAME_SPEAKER_SWITCH_MARGIN", "0.08")
    )
    reframe_speaker_min_stable_seconds: float = float(
        os.getenv("REFRAME_SPEAKER_MIN_STABLE_SECONDS", "0.8")
    )
    reframe_track_max_missing_seconds: float = float(
        os.getenv("REFRAME_TRACK_MAX_MISSING_SECONDS", "1.2")
    )
    reframe_audio_gate_enabled: bool = _env_bool(
        "REFRAME_AUDIO_GATE_ENABLED", True
    )
    reframe_tracking_debug: bool = _env_bool("REFRAME_TRACKING_DEBUG", False)
    youtube_client_id: str = os.getenv("YOUTUBE_CLIENT_ID", "")
    youtube_client_secret: str = os.getenv("YOUTUBE_CLIENT_SECRET", "")
    youtube_redirect_uri: str = os.getenv(
        "YOUTUBE_REDIRECT_URI", "http://127.0.0.1:8000/api/youtube/callback"
    )

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "vidcutly.sqlite3"

    @property
    def youtube_token_path(self) -> Path:
        return self.data_dir / "youtube-token.json"

    @property
    def youtube_profile_path(self) -> Path:
        return self.data_dir / "youtube-profile.json"

    @property
    def youtube_configured(self) -> bool:
        return bool(self.youtube_client_id and self.youtube_client_secret)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.jobs_dir.mkdir(parents=True, exist_ok=True)
