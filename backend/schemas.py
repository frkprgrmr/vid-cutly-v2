from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


JobStatus = Literal[
    "queued",
    "downloading",
    "analyzing",
    "ready",
    "rendering",
    "completed",
    "failed",
]

ClipStatus = Literal["pending", "selected", "rendering", "rendered", "failed"]
YouTubeUploadStatus = Literal["idle", "uploading", "uploaded", "failed"]
FramingMode = Literal["auto", "left", "center", "right", "fit_blur"]


class ScoreBreakdown(BaseModel):
    hook: int = Field(ge=0, le=100)
    insight: int = Field(ge=0, le=100)
    emotion: int = Field(ge=0, le=100)
    uniqueness: int = Field(ge=0, le=100)
    standalone: int = Field(ge=0, le=100)
    short_form_fit: int = Field(ge=0, le=100)


class GeminiSubtitle(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str = Field(min_length=1, max_length=160)

    @field_validator("end_seconds")
    @classmethod
    def end_after_start(cls, value: float, info):
        start = info.data.get("start_seconds", 0)
        if value <= start:
            raise ValueError("Waktu akhir subtitle harus setelah waktu mulai")
        return value


class GeminiClip(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    score: int = Field(ge=0, le=100)
    scores: ScoreBreakdown
    title: str = Field(min_length=3, max_length=100)
    thumbnail_headline: str = Field(min_length=3, max_length=80)
    hook: str = Field(min_length=3, max_length=220)
    reason: str = Field(min_length=3, max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=8)
    subtitles: list[GeminiSubtitle] = Field(default_factory=list, max_length=60)

    @field_validator("end_seconds")
    @classmethod
    def valid_duration(cls, value: float, info):
        start = info.data.get("start_seconds", 0)
        duration = value - start
        if duration < 15 or duration > 120:
            raise ValueError("Durasi kandidat harus 15–120 detik")
        return value


class GeminiAnalysis(BaseModel):
    video_summary: str = Field(min_length=3, max_length=1000)
    clips: list[GeminiClip] = Field(min_length=5, max_length=8)


class JobCreate(BaseModel):
    url: HttpUrl
    rights_confirmed: bool

    @field_validator("url")
    @classmethod
    def youtube_only(cls, value: HttpUrl):
        host = (value.host or "").lower()
        allowed = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
        if host not in allowed:
            raise ValueError("Masukkan URL video YouTube yang valid")
        return value

    @field_validator("rights_confirmed")
    @classmethod
    def rights_required(cls, value: bool):
        if not value:
            raise ValueError("Konfirmasi hak atau izin penggunaan diperlukan")
        return value


class ClipUpdate(BaseModel):
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, min_length=3, max_length=100)
    thumbnail_headline: str | None = Field(default=None, min_length=3, max_length=80)
    framing_mode: FramingMode | None = None


class ClipResponse(BaseModel):
    id: str
    job_id: str
    rank: int
    start_seconds: float
    end_seconds: float
    score: int
    scores: ScoreBreakdown
    title: str
    thumbnail_headline: str
    hook: str
    reason: str
    keywords: list[str]
    subtitles: list[GeminiSubtitle] = Field(default_factory=list)
    status: ClipStatus
    output_url: str | None = None
    thumbnail_url: str | None = None
    error: str | None = None
    framing_mode: FramingMode = "auto"
    youtube_status: YouTubeUploadStatus = "idle"
    youtube_progress: int = 0
    youtube_video_id: str | None = None
    youtube_url: str | None = None
    youtube_error: str | None = None


class YouTubeUploadRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    privacy_status: Literal["private", "unlisted", "public"] = "private"
    tags: list[str] = Field(default_factory=list, max_length=15)
    made_for_kids: bool = False


class YouTubeConnectionResponse(BaseModel):
    configured: bool
    connected: bool
    channel_id: str | None = None
    channel_title: str | None = None


class YouTubeConnectResponse(BaseModel):
    authorization_url: str


class JobResponse(BaseModel):
    id: str
    url: str
    title: str | None = None
    source_channel: str | None = None
    duration_seconds: float | None = None
    status: JobStatus
    progress: int
    stage_message: str
    rights_confirmed: bool
    source_url: str | None = None
    video_summary: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    clips: list[ClipResponse] = Field(default_factory=list)
