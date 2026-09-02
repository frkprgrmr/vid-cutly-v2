from pathlib import Path
import time

import pytest

from backend import youtube
from backend.schemas import YouTubeUploadRequest


def test_youtube_upload_defaults_to_private():
    payload = YouTubeUploadRequest(title="Clip pilihan")

    assert payload.privacy_status == "private"
    assert payload.made_for_kids is False


def test_upload_video_uses_resumable_request(monkeypatch, tmp_path: Path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")
    captured = {}

    class UploadStatus:
        @staticmethod
        def progress():
            return 0.5

    class Request:
        calls = 0

        def next_chunk(self):
            self.calls += 1
            if self.calls == 1:
                return UploadStatus(), None
            return None, {"id": "abc123"}

    class Videos:
        def insert(self, **kwargs):
            captured.update(kwargs)
            return Request()

    class YouTube:
        @staticmethod
        def videos():
            return Videos()

    monkeypatch.setattr(youtube, "load_credentials", lambda: object())
    monkeypatch.setattr(youtube, "build", lambda *args, **kwargs: YouTube())
    monkeypatch.setattr(youtube, "MediaFileUpload", lambda *args, **kwargs: "media")
    progress = []

    result = youtube.upload_video(
        video_path,
        title="Judul",
        description="Deskripsi",
        privacy_status="private",
        tags=["shorts"],
        made_for_kids=False,
        progress=progress.append,
    )

    assert result == {
        "video_id": "abc123",
        "url": "https://www.youtube.com/watch?v=abc123",
    }
    assert captured["part"] == "snippet,status"
    assert captured["body"]["status"]["privacyStatus"] == "private"
    assert captured["media_body"] == "media"
    assert progress == [1, 50, 100]


def test_upload_video_requires_existing_file(tmp_path: Path):
    with pytest.raises(RuntimeError, match="tidak ditemukan"):
        youtube.upload_video(
            tmp_path / "missing.mp4",
            title="Judul",
            description="",
            privacy_status="private",
            tags=[],
            made_for_kids=False,
            progress=lambda _: None,
        )


def test_oauth_callback_reuses_pkce_verifier(monkeypatch):
    state = "oauth-state"
    credentials = object()

    class CallbackFlow:
        def __init__(self):
            self.credentials = credentials

        def fetch_token(self, *, code):
            assert code == "authorization-code"

    def fake_flow(*, state: str, code_verifier: str):
        assert state == "oauth-state"
        assert code_verifier == "saved-pkce-verifier"
        return CallbackFlow()

    monkeypatch.setattr(youtube, "_require_configuration", lambda: None)
    monkeypatch.setattr(youtube, "_flow", fake_flow)
    monkeypatch.setattr(youtube, "_save_credentials", lambda value: None)
    monkeypatch.setattr(
        youtube,
        "_fetch_channel_profile",
        lambda value: {"channel_id": "channel", "channel_title": "Clipper"},
    )
    monkeypatch.setattr(youtube, "_write_secret_json", lambda path, value: None)
    youtube._states[state] = (time.time() + 60, "saved-pkce-verifier")

    profile = youtube.complete_authorization("authorization-code", state)

    assert profile["channel_title"] == "Clipper"
    assert state not in youtube._states


def test_oauth_start_saves_generated_pkce_verifier(monkeypatch):
    class AuthorizationFlow:
        code_verifier = None

        def authorization_url(self, **kwargs):
            self.code_verifier = "generated-pkce-verifier"
            return "https://accounts.google.com/oauth", "oauth-state"

    monkeypatch.setattr(youtube, "_require_configuration", lambda: None)
    monkeypatch.setattr(youtube.secrets, "token_urlsafe", lambda size: "oauth-state")
    monkeypatch.setattr(youtube, "_flow", lambda *, state: AuthorizationFlow())
    youtube._states.clear()

    authorization_url = youtube.create_authorization_url()

    assert authorization_url == "https://accounts.google.com/oauth"
    assert youtube._states["oauth-state"][1] == "generated-pkce-verifier"
    youtube._states.clear()
