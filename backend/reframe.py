from __future__ import annotations

import math
from dataclasses import dataclass
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
    if framing_mode in {"fit_blur", "split"}:
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
    sample_count = 0
    face_sample_count = 0
    wide_pair_sample_count = 0
    missing_face_limit = max(2, int(round(5 / sample_interval)))

    relative = 0.0
    while start_seconds + relative <= end_seconds:
        capture.set(cv2.CAP_PROP_POS_MSEC, (start_seconds + relative) * 1000)
        ok, frame = capture.read()
        if not ok:
            break
        sample_count += 1
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
            faces.append((score, center))
            next_patches.append((center, patch))
        previous_patches = next_patches

        if faces:
            face_sample_count += 1
            centers = [face[1] for face in faces]
            if len(centers) >= 2 and max(centers) - min(centers) >= crop_width * 0.8:
                wide_pair_sample_count += 1
            missing_face_samples = 0
            faces.sort(reverse=True)
            _, best_center = faces[0]
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
        relative += sample_interval

    capture.release()
    if not positions:
        positions = [(0.0, center_x)]
    if framing_mode == "auto":
        if sample_count and wide_pair_sample_count / sample_count >= 0.2:
            return CropPlan(source_width, source_height, crop_width, [(0.0, center_x)], "split")
        if not sample_count or face_sample_count / sample_count < 0.25:
            return CropPlan(
                source_width, source_height, crop_width, [(0.0, center_x)], "fit_blur"
            )
    positions = _stabilize_positions(positions, center_x, crop_width, max_x)
    positions = _lock_positions_to_shots(positions, crop_width=crop_width)
    return CropPlan(source_width, source_height, crop_width, positions)


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
    positions = plan.positions
    if len(positions) == 1:
        return f"{positions[0][1]:.1f}"
    expression = f"{positions[-1][1]:.1f}"
    for index in range(len(positions) - 2, -1, -1):
        _, x0 = positions[index]
        next_time, _ = positions[index + 1]
        expression = f"if(lt(t\\,{next_time:.2f})\\,{x0:.1f}\\,{expression})"
    return expression


def _lock_positions_to_shots(
    positions: list[tuple[float, float]],
    *,
    crop_width: int,
    shot_duration: float = 5.0,
) -> list[tuple[float, float]]:
    """Kunci crop per shot agar kamera virtual tidak terus bergerak."""
    if len(positions) <= 1:
        return positions
    buckets: list[list[float]] = []
    for timestamp, x in positions:
        index = int(timestamp // shot_duration)
        while len(buckets) <= index:
            buckets.append([])
        buckets[index].append(x)

    locked: list[tuple[float, float]] = []
    minimum_change = crop_width * 0.12
    for index, values in enumerate(buckets):
        if not values:
            continue
        target = round(float(np.median(values)), 1)
        if locked and abs(target - locked[-1][1]) < minimum_change:
            continue
        locked.append((index * shot_duration, target))
    return locked or [positions[0]]


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
