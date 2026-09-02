from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class CropPlan:
    source_width: int
    source_height: int
    crop_width: int
    positions: list[tuple[float, float]]
    layout: str = "crop"
    viewports: list[tuple[float, float, float]] = field(default_factory=list)


def build_crop_plan(
    video_path: Path,
    start_seconds: float,
    end_seconds: float,
    sample_interval: float = 0.75,
    framing_mode: str = "auto",
) -> CropPlan:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("Video tidak dapat dibuka untuk analisis framing")
    source_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    source_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    crop_width = min(source_width, int(round(source_height * 9 / 16)))
    max_x = max(0, source_width - crop_width)
    center_x = max_x / 2

    fixed_positions = {
        "left": 0.0,
        "center": center_x,
        "right": float(max_x),
    }
    if framing_mode in fixed_positions:
        capture.release()
        return CropPlan(
            source_width, source_height, crop_width, [(0.0, fixed_positions[framing_mode])]
        )
    if framing_mode == "fit_blur":
        capture.release()
        return CropPlan(
            source_width, source_height, crop_width, [(0.0, center_x)], framing_mode
        )

    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    profile_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_profileface.xml"
    )
    positions: list[tuple[float, float]] = []
    current_face_center: float | None = None
    smoothed_x = center_x
    challenger_center: float | None = None
    challenger_count = 0
    missing_face_samples = 0
    previous_patches: list[tuple[float, np.ndarray]] = []
    missing_face_limit = max(2, int(round(5 / sample_interval)))
    wide_hold_limit = max(2, int(round(3 / sample_interval)))
    wide_hold_samples = 0
    last_wide_focus = source_width / 2
    last_wide_width = 1080.0
    display_width: float | None = None
    display_focus = source_width / 2
    viewports: list[tuple[float, float, float]] = []
    full_display_width = 1080.0
    close_display_width = max(
        full_display_width, source_width * 1920 / max(1, source_height)
    )

    relative = 0.0
    while start_seconds + relative <= end_seconds:
        capture.set(cv2.CAP_PROP_POS_MSEC, (start_seconds + relative) * 1000)
        ok, frame = capture.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        scale = min(1.0, 720 / max(source_width, source_height))
        small = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
        detected = cascade.detectMultiScale(
            small, scaleFactor=1.12, minNeighbors=5, minSize=(45, 45)
        )
        if len(detected) == 0 and not profile_cascade.empty():
            profiles = list(
                profile_cascade.detectMultiScale(
                    small, scaleFactor=1.12, minNeighbors=4, minSize=(45, 45)
                )
            )
            flipped = cv2.flip(small, 1)
            mirrored = profile_cascade.detectMultiScale(
                flipped, scaleFactor=1.12, minNeighbors=4, minSize=(45, 45)
            )
            profiles.extend(
                (small.shape[1] - x - width, y, width, height)
                for x, y, width, height in mirrored
            )
            detected = profiles
        faces = []
        next_patches: list[tuple[float, np.ndarray]] = []
        for x, y, width, height in detected:
            x, y, width, height = [int(value / scale) for value in (x, y, width, height)]
            center = x + width / 2
            patch = gray[y : y + height, x : x + width]
            if patch.size == 0:
                continue
            patch = cv2.resize(patch, (64, 64))
            motion = _closest_motion(center, patch, previous_patches, source_width)
            area_score = (width * height) / max(1, source_width * source_height)
            score = area_score * (1 + min(motion / 24, 2.0))
            faces.append((score, center, width))
            next_patches.append((center, patch))
        previous_patches = next_patches

        if faces:
            missing_face_samples = 0
            faces.sort(reverse=True)
            _, best_center, _ = faces[0]
            if current_face_center is None:
                current_face_center = best_center
            elif abs(best_center - current_face_center) <= crop_width * 0.28:
                current_face_center = 0.7 * current_face_center + 0.3 * best_center
                challenger_center = None
                challenger_count = 0
            else:
                if challenger_center is not None and abs(best_center - challenger_center) < crop_width * 0.2:
                    challenger_count += 1
                else:
                    challenger_center = best_center
                    challenger_count = 1
                if challenger_count >= 3:
                    current_face_center = best_center
                    challenger_center = None
                    challenger_count = 0
        else:
            missing_face_samples += 1
            if missing_face_samples >= missing_face_limit:
                current_face_center = None
                challenger_center = None
                challenger_count = 0

        target_x = center_x if current_face_center is None else current_face_center - crop_width / 2
        target_x = min(max(target_x, 0), max_x)
        smoothing = 0.45 if current_face_center is None else 0.18
        smoothed_x = (1 - smoothing) * smoothed_x + smoothing * target_x
        if faces:
            smoothed_x = _keep_face_in_safe_area(
                smoothed_x, best_center, crop_width, max_x
            )
        positions.append((round(relative, 2), round(smoothed_x, 1)))

        if len(faces) >= 2:
            left_edge = min(center - width * 0.7 for _, center, width in faces)
            right_edge = max(center + width * 0.7 for _, center, width in faces)
            visible_source_width = min(
                source_width,
                max(crop_width, (right_edge - left_edge) / 0.78),
            )
            target_width = min(
                close_display_width,
                max(full_display_width, full_display_width * source_width / visible_source_width),
            )
            target_focus = (left_edge + right_edge) / 2
            last_wide_focus = target_focus
            last_wide_width = target_width
            wide_hold_samples = wide_hold_limit
        elif wide_hold_samples > 0:
            target_focus = last_wide_focus
            target_width = last_wide_width
            wide_hold_samples -= 1
        elif faces and current_face_center is not None:
            target_focus = current_face_center
            target_width = close_display_width
        elif missing_face_samples < missing_face_limit and viewports:
            _, target_focus, target_width = viewports[-1]
        else:
            target_focus = source_width / 2
            target_width = full_display_width

        if display_width is None:
            display_width = target_width
            display_focus = target_focus
        else:
            zoom_smoothing = 0.3
            focus_smoothing = 0.34
            display_width = (1 - zoom_smoothing) * display_width + zoom_smoothing * target_width
            display_focus = (1 - focus_smoothing) * display_focus + focus_smoothing * target_focus
        overlay_x = 540 - display_width * display_focus / max(1, source_width)
        overlay_x = min(0.0, max(1080 - display_width, overlay_x))
        viewports.append(
            (round(relative, 2), round(display_width, 1), round(overlay_x, 1))
        )
        relative += sample_interval

    capture.release()
    if not positions:
        positions = [(0.0, center_x)]
    positions = _stabilize_positions(positions, center_x, crop_width, max_x)
    return CropPlan(
        source_width,
        source_height,
        crop_width,
        _thin_positions(positions),
        "dynamic" if framing_mode == "auto" else "crop",
        _build_shot_viewports(
            viewports,
            source_width=source_width,
            crop_width=crop_width,
            duration=max(0.0, end_seconds - start_seconds),
        ),
    )


def _keep_face_in_safe_area(
    crop_x: float,
    face_center: float,
    crop_width: int,
    max_x: int,
) -> float:
    # Hindari wajah menempel/terpotong di tepi meski perpindahan antar kamera
    # sedang melalui smoothing atau hysteresis.
    minimum = min(max(face_center - crop_width * 0.78, 0), max_x)
    maximum = min(max(face_center - crop_width * 0.22, 0), max_x)
    return min(max(crop_x, minimum), maximum)


def _stabilize_positions(
    positions: list[tuple[float, float]],
    center_x: float,
    crop_width: int,
    max_x: int,
) -> list[tuple[float, float]]:
    """Ubah tracking mentah menjadi gerakan kamera yang tenang.

    Deteksi wajah hanya memberi koreksi kecil dari center crop. Dead-zone
    mengabaikan perubahan kecil dan speed limit mencegah pan cepat ketika
    kamera sumber berganti atau Haar cascade mendeteksi objek yang salah.
    """
    if not positions:
        return []
    max_offset = max(center_x, max_x - center_x)
    max_speed = crop_width * 0.22
    dead_zone = crop_width * 0.06
    follow_strength = 0.85
    stabilized: list[tuple[float, float]] = []
    current = min(max(positions[0][1], 0), max_x)
    previous_time = positions[0][0]

    for timestamp, raw_x in positions:
        correction = (raw_x - center_x) * follow_strength
        correction = min(max(correction, -max_offset), max_offset)
        target = min(max(center_x + correction, 0), max_x)
        difference = target - current
        elapsed = max(timestamp - previous_time, 0)
        if stabilized and abs(difference) > dead_zone:
            maximum_step = max_speed * elapsed
            current += min(max(difference, -maximum_step), maximum_step)
        stabilized.append((timestamp, round(current, 1)))
        previous_time = timestamp
    return stabilized


def crop_expression(plan: CropPlan) -> str:
    return timeline_expression(plan.positions)


def timeline_expression(positions: list[tuple[float, float]]) -> str:
    if not positions:
        return "0.0"
    if len(positions) == 1:
        return f"{positions[0][1]:.1f}"
    expression = f"{positions[-1][1]:.1f}"
    for index in range(len(positions) - 2, -1, -1):
        t0, x0 = positions[index]
        t1, x1 = positions[index + 1]
        span = max(t1 - t0, 0.01)
        interpolated = f"({x0:.1f}+({x1:.1f}-{x0:.1f})*(t-{t0:.2f})/{span:.2f})"
        expression = f"if(lt(t\\,{t1:.2f})\\,{interpolated}\\,{expression})"
    return expression


def _closest_motion(
    center: float,
    patch: np.ndarray,
    previous: list[tuple[float, np.ndarray]],
    frame_width: int,
) -> float:
    if not previous:
        return 0.0
    candidates = sorted(previous, key=lambda item: abs(item[0] - center))
    old_center, old_patch = candidates[0]
    if abs(old_center - center) > frame_width * 0.2:
        return 0.0
    lower = patch[30:62]
    old_lower = old_patch[30:62]
    return float(np.mean(cv2.absdiff(lower, old_lower)))


def _thin_positions(positions: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(positions) <= 3:
        return positions
    thinned = [positions[0]]
    for index, position in enumerate(positions[1:-1], start=1):
        previous = thinned[-1]
        if position[0] - previous[0] >= 1.5 or math.fabs(position[1] - previous[1]) >= 24:
            thinned.append(position)
    thinned.append(positions[-1])
    return thinned


def _build_shot_viewports(
    viewports: list[tuple[float, float, float]],
    *,
    source_width: int,
    crop_width: int,
    duration: float,
    shot_duration: float = 5.0,
    transition_duration: float = 0.45,
) -> list[tuple[float, float, float]]:
    """Ubah tracking rapat menjadi framing seperti editor manusia.

    Setiap shot menahan posisi tetap. Jika fokus bergerak di dalam satu shot,
    framing diperlebar agar semua fokus masuk tanpa pan terus-menerus. Hanya
    batas antar-shot yang memakai transisi singkat.
    """
    if not viewports:
        return []
    if len(viewports) == 1:
        return viewports

    buckets: list[list[tuple[float, float, float]]] = []
    for viewport in viewports:
        index = int(viewport[0] // shot_duration)
        while len(buckets) <= index:
            buckets.append([])
        buckets[index].append(viewport)

    targets: list[tuple[float, float, float]] = []
    for index, samples in enumerate(buckets):
        if not samples:
            continue
        left = float(source_width)
        right = 0.0
        for _, display_width, overlay_x in samples:
            scale = max(display_width / max(1, source_width), 0.001)
            visible_width = min(float(source_width), 1080 / scale)
            focus = (540 - overlay_x) / scale
            left = min(left, focus - visible_width / 2)
            right = max(right, focus + visible_width / 2)
        left = max(0.0, left)
        right = min(float(source_width), right)
        required_width = min(
            float(source_width), max(float(crop_width), (right - left) * 1.08)
        )
        focus = (left + right) / 2
        focus = min(
            max(focus, required_width / 2), source_width - required_width / 2
        )
        display_width = 1080 * source_width / required_width
        overlay_x = 540 - display_width * focus / source_width
        overlay_x = min(0.0, max(1080 - display_width, overlay_x))
        targets.append(
            (index * shot_duration, round(display_width, 1), round(overlay_x, 1))
        )

    # Shot yang hampir sama memakai framing identik agar tidak ada "napas"
    # zoom kecil yang tidak membawa informasi visual baru.
    merged: list[tuple[float, float, float]] = []
    for timestamp, width, x in targets:
        if merged:
            previous_width, previous_x = merged[-1][1], merged[-1][2]
            zoom_difference = abs(width - previous_width) / max(previous_width, 1)
            if zoom_difference < 0.1 and abs(x - previous_x) < 110:
                continue
        merged.append((timestamp, width, x))

    timeline = [(0.0, merged[0][1], merged[0][2])]
    half_transition = transition_duration / 2
    for timestamp, width, x in merged[1:]:
        previous_width, previous_x = timeline[-1][1], timeline[-1][2]
        timeline.append(
            (max(0.0, timestamp - half_transition), previous_width, previous_x)
        )
        timeline.append((timestamp + half_transition, width, x))
    final_timestamp = max(duration, viewports[-1][0])
    timeline.append((final_timestamp, timeline[-1][1], timeline[-1][2]))
    return timeline
