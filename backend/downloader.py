from __future__ import annotations

import json
import shutil
from pathlib import Path

from backend.process import ProgressCallback, ToolError, require_tool, run


def download_youtube(
    url: str,
    job_dir: Path,
    max_height: int,
    progress: ProgressCallback,
) -> tuple[dict, Path, Path | None]:
    yt_dlp = require_tool("yt-dlp")
    ffmpeg = require_tool("ffmpeg")
    job_dir.mkdir(parents=True, exist_ok=True)
    youtube_options = [yt_dlp, "--no-playlist", *_javascript_runtime_options()]

    progress(8, "Mengambil metadata video")
    metadata_result = run(
        [*youtube_options, "--dump-single-json", "--skip-download", url]
    )
    metadata = json.loads(metadata_result.stdout)

    progress(14, "Mengunduh video dan subtitle otomatis")
    output_template = str(job_dir / "source.%(ext)s")
    format_selector = (
        f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/"
        f"bv*[height<={max_height}]+ba/b[height<={max_height}]"
    )
    run(
        [
            *youtube_options,
            "--newline",
            "--merge-output-format",
            "mp4",
            "--ffmpeg-location",
            ffmpeg,
            "-f",
            format_selector,
            "-o",
            output_template,
            url,
        ],
        cwd=job_dir,
    )

    source_candidates = sorted(
        path
        for path in job_dir.glob("source.*")
        if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
    )
    if not source_candidates:
        raise RuntimeError("Video selesai diunduh tetapi file sumber tidak ditemukan")

    # Subtitle YouTube bersifat opsional karena Gemini juga menghasilkan transkrip
    # fallback. Unduh secara terpisah agar rate limit subtitle tidak membatalkan
    # video yang sudah berhasil diunduh.
    progress(40, "Mengambil subtitle Indonesia")
    try:
        run(
            [
                *youtube_options,
                "--skip-download",
                "--write-auto-subs",
                "--write-subs",
                "--sub-langs",
                "id,id.*",
                "--sub-format",
                "vtt",
                "-o",
                output_template,
                url,
            ],
            cwd=job_dir,
        )
    except ToolError:
        progress(42, "Subtitle YouTube tidak tersedia; akan memakai transkrip Gemini")

    subtitle_candidates = sorted(job_dir.glob("source*.vtt"))
    subtitle = _prefer_indonesian(subtitle_candidates)
    return metadata, source_candidates[0], subtitle


def _javascript_runtime_options() -> list[str]:
    node = shutil.which("node")
    if not node:
        return []
    return ["--js-runtimes", f"node:{node}"]


def _prefer_indonesian(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    for path in paths:
        lowered = path.name.lower()
        if ".id" in lowered or "indonesia" in lowered:
            return path
    return paths[0]
