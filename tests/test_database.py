from pathlib import Path

from backend.database import Database


def test_job_and_clip_roundtrip(tmp_path: Path):
    database = Database(tmp_path / "test.sqlite3")
    job = database.create_job("https://youtu.be/abc", True)
    database.replace_clips(
        job["id"],
        [
            {
                "start_seconds": 10,
                "end_seconds": 42,
                "score": 91,
                "scores": {
                    "hook": 95,
                    "insight": 90,
                    "emotion": 80,
                    "uniqueness": 92,
                    "standalone": 93,
                    "short_form_fit": 90,
                },
                "title": "Rahasia yang jarang dibahas",
                "thumbnail_headline": "TERNYATA INI RAHASIANYA",
                "hook": "Satu kalimat pembuka yang kuat",
                "reason": "Segmen dapat dipahami secara mandiri.",
                "keywords": ["rahasia"],
                "subtitles": [
                    {"start_seconds": 10, "end_seconds": 12, "text": "Ini rahasianya"}
                ],
            }
        ],
    )
    loaded = database.get_job(job["id"])
    assert loaded is not None
    assert loaded["rights_confirmed"] is True
    assert loaded["clips"][0]["score"] == 91
    assert loaded["clips"][0]["keywords"] == ["rahasia"]
    assert loaded["clips"][0]["subtitles"][0]["text"] == "Ini rahasianya"
