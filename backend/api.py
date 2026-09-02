from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse

from backend.config import settings
from backend.database import db
from backend.jobs import submit_analysis, submit_render, submit_youtube_upload
from backend.process import require_tool
from backend.schemas import (
    ClipResponse,
    ClipUpdate,
    JobCreate,
    JobResponse,
    YouTubeConnectionResponse,
    YouTubeConnectResponse,
    YouTubeUploadRequest,
)
from backend.youtube import (
    complete_authorization,
    connection_status,
    create_authorization_url,
    disconnect,
)


router = APIRouter(prefix="/api")


def serialize_job(job: dict) -> JobResponse:
    data = dict(job)
    data["source_url"] = media_url(job.get("source_path"))
    clips = []
    for original in job.get("clips", []):
        clip = dict(original)
        clip["output_url"] = media_url(clip.get("output_path"))
        clip["thumbnail_url"] = media_url(clip.get("thumbnail_path"))
        clips.append(clip)
    data["clips"] = clips
    return JobResponse.model_validate(data)


def media_url(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value).resolve()
    try:
        relative = path.relative_to(settings.jobs_dir)
    except ValueError:
        return None
    return "/media/" + relative.as_posix()


def serialize_clip(clip: dict) -> ClipResponse:
    data = dict(clip)
    data["output_url"] = media_url(clip.get("output_path"))
    data["thumbnail_url"] = media_url(clip.get("thumbnail_path"))
    return ClipResponse.model_validate(data)


@router.get("/health")
def health():
    try:
        ffmpeg_available = bool(require_tool("ffmpeg"))
    except RuntimeError:
        ffmpeg_available = False
    return {
        "ok": True,
        "gemini_configured": bool(settings.gemini_api_key),
        "gemini_model": settings.gemini_model,
        "youtube_configured": settings.youtube_configured,
        "tools": {
            "ffmpeg": ffmpeg_available,
            "yt_dlp": bool(shutil.which("yt-dlp")),
        },
    }


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs():
    return [serialize_job(job) for job in db.list_jobs()]


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreate):
    job = db.create_job(str(payload.url), payload.rights_confirmed)
    submit_analysis(job["id"])
    return serialize_job(job)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan")
    return serialize_job(job)


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan")
    db.update_job(
        job_id,
        status="queued",
        progress=0,
        stage_message="Menunggu diproses ulang",
        error=None,
    )
    submit_analysis(job_id)
    return serialize_job(db.get_job(job_id))


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan")
    if job["status"] in {"queued", "downloading", "analyzing", "rendering"}:
        raise HTTPException(status_code=409, detail="Job aktif tidak dapat dihapus")
    if any(clip.get("youtube_status") == "uploading" for clip in job["clips"]):
        raise HTTPException(status_code=409, detail="Upload YouTube sedang berjalan")
    job_dir = (settings.jobs_dir / job_id).resolve()
    if job_dir.parent != settings.jobs_dir.resolve():
        raise HTTPException(status_code=400, detail="Path job tidak valid")
    if job_dir.exists():
        shutil.rmtree(job_dir)
    db.delete_job(job_id)


@router.patch("/jobs/{job_id}/clips/{clip_id}", response_model=ClipResponse)
def update_clip(job_id: str, clip_id: str, payload: ClipUpdate):
    clip = db.get_clip(clip_id)
    if not clip or clip["job_id"] != job_id:
        raise HTTPException(status_code=404, detail="Clip tidak ditemukan")
    fields = payload.model_dump(exclude_none=True)
    start = fields.get("start_seconds", clip["start_seconds"])
    end = fields.get("end_seconds", clip["end_seconds"])
    if end <= start or end - start < 5 or end - start > 120:
        raise HTTPException(
            status_code=422,
            detail="Durasi clip harus 5–120 detik dan waktu selesai harus setelah waktu mulai",
        )
    if clip["status"] == "rendering":
        raise HTTPException(status_code=409, detail="Clip sedang dirender")
    if clip.get("youtube_status") == "uploading":
        raise HTTPException(status_code=409, detail="Clip sedang diunggah ke YouTube")
    fields.update({"status": "pending", "output_path": None, "thumbnail_path": None})
    db.update_clip(clip_id, **fields)
    updated = db.get_clip(clip_id)
    updated["output_url"] = None
    updated["thumbnail_url"] = None
    return ClipResponse.model_validate(updated)


@router.post("/jobs/{job_id}/clips/{clip_id}/render", response_model=ClipResponse)
def start_render(job_id: str, clip_id: str):
    job = db.get_job(job_id)
    clip = db.get_clip(clip_id)
    if not job or not clip or clip["job_id"] != job_id:
        raise HTTPException(status_code=404, detail="Clip tidak ditemukan")
    if clip["status"] == "rendering":
        raise HTTPException(status_code=409, detail="Clip sedang dirender")
    if clip.get("youtube_status") == "uploading":
        raise HTTPException(status_code=409, detail="Clip sedang diunggah ke YouTube")
    if not job.get("source_path"):
        raise HTTPException(status_code=409, detail="File sumber video belum siap")
    db.update_clip(clip_id, status="rendering", error=None)
    db.update_job(
        job_id,
        status="rendering",
        stage_message=f"Clip {clip['rank']}: masuk antrean render",
    )
    submit_render(job_id, clip_id)
    return serialize_clip(db.get_clip(clip_id))


@router.get("/youtube/status", response_model=YouTubeConnectionResponse)
def youtube_status():
    return YouTubeConnectionResponse.model_validate(connection_status())


@router.post("/youtube/connect", response_model=YouTubeConnectResponse)
def youtube_connect():
    try:
        return {"authorization_url": create_authorization_url()}
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/youtube/callback")
def youtube_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(status_code=400, detail=f"Koneksi YouTube ditolak: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Callback OAuth YouTube tidak lengkap")
    try:
        complete_authorization(code, state)
    except Exception as oauth_error:
        raise HTTPException(status_code=400, detail=str(oauth_error)) from oauth_error
    return RedirectResponse(url="/?youtube=connected", status_code=302)


@router.post("/youtube/disconnect", response_model=YouTubeConnectionResponse)
def youtube_disconnect():
    disconnect()
    return YouTubeConnectionResponse.model_validate(connection_status())


@router.post(
    "/jobs/{job_id}/clips/{clip_id}/youtube-upload",
    response_model=ClipResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_youtube_upload(job_id: str, clip_id: str, payload: YouTubeUploadRequest):
    job = db.get_job(job_id)
    clip = db.get_clip(clip_id)
    if not job or not clip or clip["job_id"] != job_id:
        raise HTTPException(status_code=404, detail="Job atau clip tidak ditemukan")
    if not connection_status()["connected"]:
        raise HTTPException(status_code=409, detail="Hubungkan akun YouTube terlebih dahulu")
    if clip.get("status") != "rendered" or not clip.get("output_path"):
        raise HTTPException(status_code=409, detail="Render clip sebelum upload ke YouTube")
    if clip.get("youtube_status") == "uploading":
        raise HTTPException(status_code=409, detail="Upload YouTube sedang berjalan")
    db.update_clip(
        clip_id,
        youtube_status="uploading",
        youtube_progress=0,
        youtube_error=None,
    )
    submit_youtube_upload(job_id, clip_id, payload.model_dump(mode="json"))
    return serialize_clip(db.get_clip(clip_id))
