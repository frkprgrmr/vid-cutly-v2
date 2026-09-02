from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from backend.config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  title TEXT,
  source_channel TEXT,
  duration_seconds REAL,
  status TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0,
  stage_message TEXT NOT NULL DEFAULT '',
  rights_confirmed INTEGER NOT NULL,
  source_path TEXT,
  subtitle_path TEXT,
  video_summary TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clips (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  rank INTEGER NOT NULL,
  start_seconds REAL NOT NULL,
  end_seconds REAL NOT NULL,
  score INTEGER NOT NULL,
  scores_json TEXT NOT NULL,
  title TEXT NOT NULL,
  thumbnail_headline TEXT NOT NULL,
  hook TEXT NOT NULL,
  reason TEXT NOT NULL,
  keywords_json TEXT NOT NULL,
  subtitles_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending',
  output_path TEXT,
  thumbnail_path TEXT,
  error TEXT,
  framing_mode TEXT NOT NULL DEFAULT 'auto',
  youtube_status TEXT NOT NULL DEFAULT 'idle',
  youtube_progress INTEGER NOT NULL DEFAULT 0,
  youtube_video_id TEXT,
  youtube_url TEXT,
  youtube_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clips_job_id ON clips(job_id);
"""


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path = settings.database_path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            job_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "source_channel" not in job_columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN source_channel TEXT")
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(clips)").fetchall()
            }
            if "subtitles_json" not in columns:
                connection.execute(
                    "ALTER TABLE clips ADD COLUMN subtitles_json TEXT NOT NULL DEFAULT '[]'"
                )
            clip_migrations = {
                "framing_mode": "TEXT NOT NULL DEFAULT 'auto'",
                "youtube_status": "TEXT NOT NULL DEFAULT 'idle'",
                "youtube_progress": "INTEGER NOT NULL DEFAULT 0",
                "youtube_video_id": "TEXT",
                "youtube_url": "TEXT",
                "youtube_error": "TEXT",
            }
            for name, definition in clip_migrations.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE clips ADD COLUMN {name} {definition}")
            connection.execute(
                "UPDATE clips SET framing_mode = 'auto' WHERE framing_mode = 'split'"
            )

    def create_job(self, url: str, rights_confirmed: bool) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        now = utcnow()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO jobs
                (id, url, status, progress, stage_message, rights_confirmed, created_at, updated_at)
                VALUES (?, ?, 'queued', 0, 'Menunggu diproses', ?, ?, ?)""",
                (job_id, url, int(rights_confirmed), now, now),
            )
        return self.get_job(job_id)

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utcnow()
        columns = ", ".join(f"{key} = ?" for key in fields)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {columns} WHERE id = ?",
                (*fields.values(), job_id),
            )

    def replace_clips(self, job_id: str, clips: list[dict[str, Any]]) -> None:
        now = utcnow()
        with self.connect() as connection:
            connection.execute("DELETE FROM clips WHERE job_id = ?", (job_id,))
            for rank, clip in enumerate(clips, start=1):
                connection.execute(
                    """INSERT INTO clips
                    (id, job_id, rank, start_seconds, end_seconds, score, scores_json,
                     title, thumbnail_headline, hook, reason, keywords_json, subtitles_json, status,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                    (
                        uuid.uuid4().hex,
                        job_id,
                        rank,
                        clip["start_seconds"],
                        clip["end_seconds"],
                        clip["score"],
                        json.dumps(clip["scores"], ensure_ascii=False),
                        clip["title"],
                        clip["thumbnail_headline"],
                        clip["hook"],
                        clip["reason"],
                        json.dumps(clip.get("keywords", []), ensure_ascii=False),
                        json.dumps(clip.get("subtitles", []), ensure_ascii=False),
                        now,
                        now,
                    ),
                )

    def update_clip(self, clip_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utcnow()
        columns = ", ".join(f"{key} = ?" for key in fields)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE clips SET {columns} WHERE id = ?",
                (*fields.values(), clip_id),
            )

    def get_clip(self, clip_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        return self._clip(row) if row else None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            clips = connection.execute(
                "SELECT * FROM clips WHERE job_id = ? ORDER BY rank", (job_id,)
            ).fetchall()
        if not row:
            return None
        result = dict(row)
        result["rights_confirmed"] = bool(result["rights_confirmed"])
        result["clips"] = [self._clip(clip) for clip in clips]
        return result

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
        return [job for row in rows if (job := self.get_job(row["id"]))]

    def delete_job(self, job_id: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    @staticmethod
    def _clip(row: sqlite3.Row) -> dict[str, Any]:
        clip = dict(row)
        clip["scores"] = json.loads(clip.pop("scores_json"))
        clip["keywords"] = json.loads(clip.pop("keywords_json"))
        clip["subtitles"] = json.loads(clip.pop("subtitles_json", "[]"))
        return clip


db = Database()
