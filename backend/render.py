from __future__ import annotations

import textwrap
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from backend.captions import Cue, parse_vtt, write_ass
from backend.config import settings
from backend.process import ProgressCallback, probe_video, require_tool, run
from backend.reframe import build_crop_plan, crop_expression


def render_clip(
    source_path: Path,
    subtitle_path: Path | None,
    output_path: Path,
    thumbnail_path: Path,
    start_seconds: float,
    end_seconds: float,
    title: str,
    thumbnail_headline: str,
    keywords: list[str],
    fallback_subtitles: list[dict],
    source_channel: str | None,
    framing_mode: str,
    progress: ProgressCallback,
) -> None:
    ffmpeg = require_tool("ffmpeg")
    duration = end_seconds - start_seconds
    if duration < 5:
        raise ValueError("Durasi clip minimal 5 detik")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    progress(76, "Menganalisis wajah dan gerakan pembicara")
    plan = build_crop_plan(
        source_path, start_seconds, end_seconds, framing_mode=framing_mode
    )
    expression = crop_expression(plan)

    ass_path = output_path.with_suffix(".ass")
    cues = parse_vtt(subtitle_path)
    if not cues:
        cues = [
            Cue(
                start=float(item["start_seconds"]),
                end=float(item["end_seconds"]),
                text=str(item["text"]),
            )
            for item in fallback_subtitles
            if item.get("end_seconds", 0) > item.get("start_seconds", 0)
        ]
    write_ass(
        ass_path,
        cues,
        start_seconds,
        end_seconds,
        title,
        keywords,
        source_channel=source_channel,
    )

    progress(82, "Merender video vertikal dan subtitle")
    ass_filter_path = str(ass_path).replace("'", r"\'").replace(":", r"\:")
    base_filter_graph = _video_filter_graph(plan, expression, ass_filter_path)

    watermark_path = settings.root_dir / "assets" / "clipper-magang954-watermark.png"
    youtube_icon_path = settings.root_dir / "assets" / "youtube-source-icon.png"
    command = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-i",
        str(source_path),
    ]
    if watermark_path.exists() and youtube_icon_path.exists():
        command.extend(
            [
                "-loop",
                "1",
                "-i",
                str(watermark_path),
                "-loop",
                "1",
                "-i",
                str(youtube_icon_path),
            ]
        )
        filter_graph = (
            f"{base_filter_graph};"
            "[1:v]scale=300:-1,format=rgba,colorchannelmixer=aa=0.72[watermark];"
            "[2:v]scale=44:-1,format=rgba[youtube];"
            "[base][watermark]overlay=40:(H-h)/2-45:format=auto[branded];"
            "[branded][youtube]overlay=48:(H-h)/2+70:format=auto[v]"
        )
        command.extend(
            ["-filter_complex", filter_graph, "-map", "[v]", "-map", "0:a?"]
        )
    else:
        command.extend(
            ["-filter_complex", base_filter_graph, "-map", "[base]", "-map", "0:a?"]
        )

    command.extend(
        [
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    run(command)

    progress(96, "Membuat thumbnail")
    _make_thumbnail(
        source_path,
        thumbnail_path,
        start_seconds,
        end_seconds,
        thumbnail_headline,
        plan,
    )
    probe_video(output_path)


def _make_thumbnail(source, output, start, end, headline, plan) -> None:
    capture = cv2.VideoCapture(str(source))
    best_frame = None
    best_score = -1.0
    duration = max(1, end - start)
    for fraction in (0.12, 0.25, 0.4, 0.55, 0.7, 0.84):
        capture.set(cv2.CAP_PROP_POS_MSEC, (start + duration * fraction) * 1000)
        ok, frame = capture.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        exposure = max(0, 1 - abs(brightness - 128) / 128)
        score = sharpness * (0.65 + 0.35 * exposure)
        if score > best_score:
            best_score = score
            best_frame = frame
    capture.release()
    if best_frame is None:
        raise RuntimeError("Tidak dapat mengambil frame untuk thumbnail")

    portrait = _portrait_frame(best_frame, plan)
    portrait = cv2.cvtColor(portrait, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(portrait).convert("RGBA")

    gradient = Image.new("RGBA", image.size, (0, 0, 0, 0))
    gradient_pixels = np.zeros((1920, 1080, 4), dtype=np.uint8)
    for y in range(900):
        alpha = int(220 * (1 - y / 900) ** 1.6)
        gradient_pixels[y, :, :] = (9, 6, 23, alpha)
    gradient = Image.fromarray(gradient_pixels, mode="RGBA")
    image = Image.alpha_composite(image, gradient)

    draw = ImageDraw.Draw(image)
    font_path = _font_path()
    font_size = 94
    font = ImageFont.truetype(font_path, font_size)
    wrapped = _pixel_wrap(draw, headline.upper(), font, 920)
    while len(wrapped) > 4 and font_size > 64:
        font_size -= 6
        font = ImageFont.truetype(font_path, font_size)
        wrapped = _pixel_wrap(draw, headline.upper(), font, 920)
    text = "\n".join(wrapped[:4])
    draw.multiline_text(
        (80, 110),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        stroke_width=6,
        stroke_fill=(16, 10, 36, 255),
        spacing=12,
    )
    draw.rounded_rectangle((80, 72, 300, 110), radius=18, fill=(255, 193, 7, 255))
    image.convert("RGB").save(output, quality=92)


def _video_filter_graph(plan, expression: str, ass_filter_path: str) -> str:
    subtitles = f"subtitles=filename='{ass_filter_path}'"
    if plan.layout == "fit_blur":
        return (
            "[0:v]split=2[fitbg][fitfg];"
            "[fitbg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,gblur=sigma=32[blurred];"
            "[fitfg]scale=1080:1920:force_original_aspect_ratio=decrease[foreground];"
            f"[blurred][foreground]overlay=(W-w)/2:(H-h)/2,{subtitles}[base]"
        )
    if plan.layout == "split":
        return (
            "[0:v]split=2[splitleft][splitright];"
            "[splitleft]crop=iw/2:ih:0:0,"
            "scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[left];"
            "[splitright]crop=iw/2:ih:iw/2:0,"
            "scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[right];"
            f"[left][right]vstack=inputs=2,{subtitles}[base]"
        )
    if plan.source_width >= plan.crop_width and plan.crop_width > 0:
        return (
            f"[0:v]crop={plan.crop_width}:{plan.source_height}:'{expression}':0,"
            f"scale=1080:1920:flags=lanczos,{subtitles}[base]"
        )
    return (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
        f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,{subtitles}[base]"
    )


def _portrait_frame(frame: np.ndarray, plan) -> np.ndarray:
    if plan.layout == "fit_blur":
        background = _cover_resize(frame, 1080, 1920)
        background = cv2.GaussianBlur(background, (0, 0), 32)
        scale = min(1080 / frame.shape[1], 1920 / frame.shape[0])
        foreground = cv2.resize(
            frame,
            (max(1, round(frame.shape[1] * scale)), max(1, round(frame.shape[0] * scale))),
            interpolation=cv2.INTER_LANCZOS4,
        )
        y = (1920 - foreground.shape[0]) // 2
        x = (1080 - foreground.shape[1]) // 2
        background[y : y + foreground.shape[0], x : x + foreground.shape[1]] = foreground
        return background
    if plan.layout == "split":
        midpoint = frame.shape[1] // 2
        left = _cover_resize(frame[:, :midpoint], 1080, 960)
        right = _cover_resize(frame[:, midpoint:], 1080, 960)
        return np.vstack((left, right))

    height, width = frame.shape[:2]
    crop_width = min(width, int(height * 9 / 16))
    mid_x = plan.positions[len(plan.positions) // 2][1] if plan.positions else (width - crop_width) / 2
    crop_x = int(min(max(mid_x, 0), max(0, width - crop_width)))
    portrait = frame[:, crop_x : crop_x + crop_width]
    return cv2.resize(portrait, (1080, 1920), interpolation=cv2.INTER_LANCZOS4)


def _cover_resize(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    scale = max(width / frame.shape[1], height / frame.shape[0])
    resized = cv2.resize(
        frame,
        (max(1, round(frame.shape[1] * scale)), max(1, round(frame.shape[0] * scale))),
        interpolation=cv2.INTER_LANCZOS4,
    )
    x = max(0, (resized.shape[1] - width) // 2)
    y = max(0, (resized.shape[0] - height) // 2)
    return resized[y : y + height, x : x + width]


def _font_path() -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    raise RuntimeError("Font bold sistem tidak ditemukan")


def _pixel_wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int):
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [textwrap.shorten(text, width=18)]
