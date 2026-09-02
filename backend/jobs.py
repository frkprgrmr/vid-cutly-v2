from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from backend.config import settings
from backend.database import db
from backend.downloader import download_youtube
from backend.gemini import analyze_youtube
from backend.render import render_clip
from backend.youtube import upload_video


executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vidcutly")
active_jobs: set[str] = set()
active_lock = Lock()


def submit_analysis(job_id: str) -> None:
    with active_lock:
        key = f"analysis:{job_id}"
        if key in active_jobs:
            return
        active_jobs.add(key)
    executor.submit(_analysis_guard, job_id, key)


def submit_render(job_id: str, clip_id: str) -> None:
    with active_lock:
        key = f"render:{clip_id}"
        if key in active_jobs:
            return
        active_jobs.add(key)
    executor.submit(_render_guard, job_id, clip_id, key)


def submit_youtube_upload(job_id: str, clip_id: str, options: dict) -> None:
    with active_lock:
        key = f"youtube:{clip_id}"
        if key in active_jobs:
            return
        active_jobs.add(key)
    executor.submit(_youtube_upload_guard, job_id, clip_id, options, key)


def _analysis_guard(job_id: str, key: str) -> None:
    try:
        analyze_job(job_id)
    except Exception as error:
        db.update_job(
            job_id,
            status="failed",
            error=_friendly_error(error),
            stage_message="Proses gagal",
        )
    finally:
        with active_lock:
            active_jobs.discard(key)


def _render_guard(job_id: str, clip_id: str, key: str) -> None:
    try:
        render_job_clip(job_id, clip_id)
    except Exception as error:
        db.update_clip(clip_id, status="failed", error=_friendly_error(error))
        job = db.get_job(job_id)
        if job:
            status = "completed" if any(c["status"] == "rendered" for c in job["clips"]) else "ready"
            db.update_job(
                job_id,
                status=status,
                stage_message="Render clip gagal; kandidat lain tetap dapat digunakan",
            )
    finally:
        with active_lock:
            active_jobs.discard(key)


def _youtube_upload_guard(job_id: str, clip_id: str, options: dict, key: str) -> None:
    try:
        upload_job_clip(job_id, clip_id, options)
    except Exception as error:
        db.update_clip(
            clip_id,
            youtube_status="failed",
            youtube_error=_friendly_error(error),
        )
    finally:
        with active_lock:
            active_jobs.discard(key)


def analyze_job(job_id: str) -> None:
    job = db.get_job(job_id)
    if not job:
        return
    job_dir = settings.jobs_dir / job_id

    def download_progress(value: int, message: str) -> None:
        db.update_job(
            job_id,
            status="downloading",
            progress=value,
            stage_message=message,
            error=None,
        )

    metadata, source_path, subtitle_path = download_youtube(
        job["url"], job_dir, settings.video_max_height, download_progress
    )
    db.update_job(
        job_id,
        status="analyzing",
        progress=45,
        stage_message="Gemini sedang memahami audio, ekspresi, dan percakapan",
        title=metadata.get("title") or "Podcast tanpa judul",
        source_channel=(
            metadata.get("channel")
            or metadata.get("uploader")
            or metadata.get("channel_id")
            or "YouTube"
        ),
        duration_seconds=float(metadata.get("duration") or 0),
        source_path=str(source_path),
        subtitle_path=str(subtitle_path) if subtitle_path else None,
    )

    analysis = analyze_youtube(job["url"])
    db.replace_clips(
        job_id,
        [clip.model_dump(mode="json") for clip in analysis.clips[:5]],
    )
    db.update_job(
        job_id,
        status="ready",
        progress=70,
        stage_message="Lima kandidat siap ditinjau",
        video_summary=analysis.video_summary,
        error=None,
    )


def render_job_clip(job_id: str, clip_id: str) -> None:
    job = db.get_job(job_id)
    clip = db.get_clip(clip_id)
    if not job or not clip or clip["job_id"] != job_id:
        raise RuntimeError("Job atau clip tidak ditemukan")
    if not job.get("source_path"):
        raise RuntimeError("File sumber video belum tersedia")

    job_dir = settings.jobs_dir / job_id
    outputs_dir = job_dir / "outputs"
    output_path = outputs_dir / f"clip-{clip['rank']:02d}.mp4"
    thumbnail_path = outputs_dir / f"clip-{clip['rank']:02d}-thumbnail.jpg"

    def render_progress(value: int, message: str) -> None:
        db.update_job(
            job_id,
            status="rendering",
            progress=value,
            stage_message=f"Clip {clip['rank']}: {message}",
        )

    db.update_clip(clip_id, status="rendering", error=None)
    render_clip(
        source_path=Path(job["source_path"]),
        subtitle_path=Path(job["subtitle_path"]) if job.get("subtitle_path") else None,
        output_path=output_path,
        thumbnail_path=thumbnail_path,
        start_seconds=clip["start_seconds"],
        end_seconds=clip["end_seconds"],
        title=clip["title"],
        thumbnail_headline=clip["thumbnail_headline"],
        keywords=clip["keywords"],
        fallback_subtitles=clip.get("subtitles", []),
        source_channel=job.get("source_channel") or "YouTube",
        framing_mode=clip.get("framing_mode") or "auto",
        progress=render_progress,
    )
    db.update_clip(
        clip_id,
        status="rendered",
        output_path=str(output_path),
        thumbnail_path=str(thumbnail_path),
        error=None,
    )
    updated = db.get_job(job_id)
    all_rendered = updated and all(c["status"] == "rendered" for c in updated["clips"])
    db.update_job(
        job_id,
        status="completed" if all_rendered else "ready",
        progress=100 if all_rendered else 70,
        stage_message="Semua clip selesai" if all_rendered else "Clip selesai; kandidat lain siap ditinjau",
    )


def upload_job_clip(job_id: str, clip_id: str, options: dict) -> None:
    job = db.get_job(job_id)
    clip = db.get_clip(clip_id)
    if not job or not clip or clip["job_id"] != job_id:
        raise RuntimeError("Job atau clip tidak ditemukan")
    if clip.get("status") != "rendered" or not clip.get("output_path"):
        raise RuntimeError("Render clip sebelum mengunggah ke YouTube")

    def upload_progress(value: int) -> None:
        db.update_clip(
            clip_id,
            youtube_status="uploading",
            youtube_progress=value,
            youtube_error=None,
        )

    result = upload_video(
        Path(clip["output_path"]),
        title=options["title"],
        description=options.get("description", ""),
        privacy_status=options.get("privacy_status", "private"),
        tags=options.get("tags", []),
        made_for_kids=bool(options.get("made_for_kids", False)),
        progress=upload_progress,
    )
    db.update_clip(
        clip_id,
        youtube_status="uploaded",
        youtube_progress=100,
        youtube_video_id=result["video_id"],
        youtube_url=result["url"],
        youtube_error=None,
    )


def _friendly_error(error: Exception) -> str:
    message = str(error).strip()
    if message:
        return message[-2000:]
    return f"{error.__class__.__name__}: proses tidak dapat diselesaikan"
