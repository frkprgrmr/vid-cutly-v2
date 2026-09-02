from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from threading import Lock
from typing import Callable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from backend.config import settings


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
_states: dict[str, tuple[float, str]] = {}
_state_lock = Lock()


def connection_status() -> dict:
    profile = _read_json(settings.youtube_profile_path)
    connected = False
    if settings.youtube_configured and settings.youtube_token_path.exists():
        try:
            connected = bool(load_credentials())
        except Exception:
            connected = False
    return {
        "configured": settings.youtube_configured,
        "connected": connected,
        "channel_id": profile.get("channel_id") if connected else None,
        "channel_title": profile.get("channel_title") if connected else None,
    }


def create_authorization_url() -> str:
    _require_configuration()
    state = secrets.token_urlsafe(32)
    flow = _flow(state=state)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent select_account",
    )
    if not flow.code_verifier:
        raise RuntimeError("PKCE verifier OAuth gagal dibuat")
    with _state_lock:
        _states.clear()
        _states[state] = (time.time() + 600, flow.code_verifier)
    return authorization_url


def complete_authorization(code: str, state: str) -> dict:
    _require_configuration()
    with _state_lock:
        pending = _states.pop(state, None)
    if not pending or pending[0] < time.time():
        raise RuntimeError("Sesi koneksi YouTube kedaluwarsa. Mulai koneksi lagi.")
    _, code_verifier = pending

    # OAuthlib mengizinkan HTTP untuk loopback redirect. Variabel ini hanya
    # diperlukan pada beberapa versi ketika host yang dipakai adalah 127.0.0.1.
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    flow = _flow(state=state, code_verifier=code_verifier)
    flow.fetch_token(code=code)
    _save_credentials(flow.credentials)
    profile = _fetch_channel_profile(flow.credentials)
    _write_secret_json(settings.youtube_profile_path, profile)
    return profile


def disconnect() -> None:
    for path in (settings.youtube_token_path, settings.youtube_profile_path):
        if path.exists():
            path.unlink()


def load_credentials() -> Credentials:
    if not settings.youtube_token_path.exists():
        raise RuntimeError("Akun YouTube belum dihubungkan")
    credentials = Credentials.from_authorized_user_file(
        str(settings.youtube_token_path), SCOPES
    )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _save_credentials(credentials)
    if not credentials.valid:
        raise RuntimeError("Sesi YouTube tidak valid. Hubungkan ulang akun YouTube.")
    return credentials


def upload_video(
    path: Path,
    *,
    title: str,
    description: str,
    privacy_status: str,
    tags: list[str],
    made_for_kids: bool,
    progress: Callable[[int], None],
) -> dict:
    if not path.exists():
        raise RuntimeError("File MP4 hasil render tidak ditemukan")
    credentials = load_credentials()
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags[:15],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }
    media = MediaFileUpload(
        str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True
    )
    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )
    response = None
    progress(1)
    while response is None:
        upload_status, response = request.next_chunk()
        if upload_status is not None:
            progress(max(1, min(99, round(upload_status.progress() * 100))))
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube tidak mengembalikan ID video")
    progress(100)
    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


def _fetch_channel_profile(credentials: Credentials) -> dict:
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    response = youtube.channels().list(part="snippet", mine=True).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError("Akun Google ini tidak memiliki channel YouTube")
    channel = items[0]
    return {
        "channel_id": channel.get("id"),
        "channel_title": channel.get("snippet", {}).get("title") or "Channel YouTube",
    }


def _flow(state: str | None = None, code_verifier: str | None = None) -> Flow:
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.youtube_redirect_uri],
            }
        },
        scopes=SCOPES,
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=code_verifier is None,
    )
    flow.redirect_uri = settings.youtube_redirect_uri
    return flow


def _save_credentials(credentials: Credentials) -> None:
    settings.youtube_token_path.parent.mkdir(parents=True, exist_ok=True)
    settings.youtube_token_path.write_text(credentials.to_json(), encoding="utf-8")
    settings.youtube_token_path.chmod(0o600)


def _write_secret_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _require_configuration() -> None:
    if not settings.youtube_configured:
        raise RuntimeError(
            "YOUTUBE_CLIENT_ID dan YOUTUBE_CLIENT_SECRET belum diisi di .env"
        )
