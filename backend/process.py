from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable


ProgressCallback = Callable[[int, str], None]


class ToolError(RuntimeError):
    pass


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path and name == "ffmpeg":
        try:
            import imageio_ffmpeg

            path = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            path = None
    if not path:
        raise ToolError(
            f"Tool '{name}' belum terpasang. Jalankan ./scripts/setup.sh lalu coba lagi."
        )
    return path


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-3000:]
        raise ToolError(detail or f"Perintah gagal: {command[0]}")
    return result


def probe_video(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        result = run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=width,height",
                "-select_streams",
                "v:0",
                "-of",
                "json",
                str(path),
            ]
        )
        return json.loads(result.stdout)

    import cv2

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ToolError("Hasil render tidak dapat dibuka untuk verifikasi")
    fps = capture.get(cv2.CAP_PROP_FPS) or 0
    frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    return {
        "format": {"duration": str(frames / fps if fps else 0)},
        "streams": [{"width": width, "height": height}],
    }
