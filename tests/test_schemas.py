import pytest
from pydantic import ValidationError

from backend.schemas import GeminiAnalysis, GeminiSubtitle, JobCreate


def test_job_requires_youtube_url_and_rights():
    job = JobCreate(url="https://www.youtube.com/watch?v=abc123", rights_confirmed=True)
    assert job.rights_confirmed is True

    with pytest.raises(ValidationError):
        JobCreate(url="https://example.com/video", rights_confirmed=True)

    with pytest.raises(ValidationError):
        JobCreate(url="https://youtu.be/abc123", rights_confirmed=False)


def test_gemini_schema_avoids_unsupported_exclusive_minimum():
    schema = GeminiAnalysis.model_json_schema()
    assert "exclusiveMinimum" not in str(schema)


def test_subtitle_end_must_be_after_start():
    GeminiSubtitle(start_seconds=10, end_seconds=11, text="Valid")

    with pytest.raises(ValidationError):
        GeminiSubtitle(start_seconds=10, end_seconds=10, text="Tidak valid")
