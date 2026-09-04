from __future__ import annotations

import logging
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from backend.config import settings


logger = logging.getLogger(__name__)


@dataclass
class CropPlan:
    source_width: int
    source_height: int
    crop_width: int
    positions: list[tuple[float, float]]
    layout: str = "crop"


@dataclass(frozen=True)
class SpeakerSelectionConfig:
    window_seconds: float = settings.reframe_speaker_window_seconds
    minimum_confidence: float = settings.reframe_speaker_min_confidence
    switch_margin: float = settings.reframe_speaker_switch_margin
    minimum_stable_duration: float = settings.reframe_speaker_min_stable_seconds
    track_max_missing_seconds: float = settings.reframe_track_max_missing_seconds


@dataclass(frozen=True)
class _FaceDetection:
    bbox: tuple[float, float, float, float]
    patch: np.ndarray


@dataclass
class _FaceTrack:
    track_id: int
    bbox: tuple[float, float, float, float]
    patch: np.ndarray
    last_seen: float
    hits: int = 1


@dataclass(frozen=True)
class _TrackedFace:
    track_id: int
    bbox: tuple[float, float, float, float]
    mouth_score: float
    audio_score: float
    speaker_score: float

    @property
    def center(self) -> float:
        return self.bbox[0] + self.bbox[2] / 2


@dataclass(frozen=True)
class _SpeakerDecision:
    current_speaker_id: int | None
    candidate_speaker_id: int | None
    current_speaker_score: float
    candidate_speaker_score: float
    switch_reason: str
    switched: bool = False


class _FaceTracker:
    """Associate detections over time without changing the face detector."""

    def __init__(self, max_missing_seconds: float) -> None:
        self.max_missing_seconds = max_missing_seconds
        self._tracks: dict[int, _FaceTrack] = {}
        self._next_track_id = 1

    def reset(self) -> None:
        # Keep the counter monotonic so an ID is never reused within a clip.
        self._tracks.clear()

    @property
    def active_track_count(self) -> int:
        return len(self._tracks)

    def update(
        self,
        detections: list[_FaceDetection],
        timestamp: float,
        frame_width: int,
        audio_score: float,
        audio_available: bool,
    ) -> list[_TrackedFace]:
        self._prune(timestamp)
        associations = self._associate(detections, frame_width)
        tracked: list[_TrackedFace] = []
        matched_detection_ids: set[int] = set()

        for track_id, detection_index in associations:
            state = self._tracks[track_id]
            detection = detections[detection_index]
            mouth_score, head_motion = _mouth_activity(
                state.bbox, state.patch, detection.bbox, detection.patch
            )
            audio_factor = 1.0
            if audio_available and settings.reframe_audio_gate_enabled:
                # Silence strongly reduces a visual-only mouth event, while a
                # missing audio stream leaves the visual score unchanged.
                audio_factor = 0.25 + 0.75 * audio_score
            speaker_score = float(
                np.clip(mouth_score * audio_factor * (1 - 0.35 * head_motion), 0, 1)
            )
            state.bbox = _smooth_bbox(state.bbox, detection.bbox)
            state.patch = detection.patch
            state.last_seen = timestamp
            state.hits += 1
            tracked.append(
                _TrackedFace(
                    track_id=track_id,
                    bbox=state.bbox,
                    mouth_score=mouth_score,
                    audio_score=audio_score if audio_available else 0.0,
                    speaker_score=speaker_score,
                )
            )
            matched_detection_ids.add(detection_index)

        for index, detection in enumerate(detections):
            if index in matched_detection_ids:
                continue
            track_id = self._next_track_id
            self._next_track_id += 1
            self._tracks[track_id] = _FaceTrack(
                track_id=track_id,
                bbox=detection.bbox,
                patch=detection.patch,
                last_seen=timestamp,
            )
            tracked.append(
                _TrackedFace(
                    track_id=track_id,
                    bbox=detection.bbox,
                    mouth_score=0.0,
                    audio_score=audio_score if audio_available else 0.0,
                    speaker_score=0.0,
                )
            )
        return sorted(tracked, key=lambda face: face.track_id)

    def _prune(self, timestamp: float) -> None:
        expired = [
            track_id
            for track_id, track in self._tracks.items()
            if timestamp - track.last_seen > self.max_missing_seconds
        ]
        for track_id in expired:
            del self._tracks[track_id]

    def _associate(
        self, detections: list[_FaceDetection], frame_width: int
    ) -> list[tuple[int, int]]:
        candidates: list[tuple[float, int, int]] = []
        for track_id, track in self._tracks.items():
            for detection_index, detection in enumerate(detections):
                score = _association_score(track, detection, frame_width)
                if score is not None:
                    candidates.append((score, track_id, detection_index))

        matched_tracks: set[int] = set()
        matched_detections: set[int] = set()
        associations: list[tuple[int, int]] = []
        for _, track_id, detection_index in sorted(candidates, reverse=True):
            if track_id in matched_tracks or detection_index in matched_detections:
                continue
            matched_tracks.add(track_id)
            matched_detections.add(detection_index)
            associations.append((track_id, detection_index))
        return associations


class _SpeakerSelector:
    """Choose a speaker from rolling evidence with confidence hysteresis."""

    def __init__(self, config: SpeakerSelectionConfig) -> None:
        self.config = config
        self.current_speaker_id: int | None = None
        self.candidate_speaker_id: int | None = None
        self.candidate_since: float | None = None
        self._history: dict[int, list[tuple[float, float]]] = {}

    def reset(self) -> None:
        # Track IDs are scoped to a continuous camera shot. A hard cut makes
        # all previous identity and score evidence invalid.
        self.current_speaker_id = None
        self._clear_candidate()
        self._history.clear()

    def update(
        self,
        timestamp: float,
        faces: list[_TrackedFace],
        known_face_count: int | None = None,
    ) -> _SpeakerDecision:
        known_face_count = (
            known_face_count if known_face_count is not None else len(faces)
        )
        visible_ids = {face.track_id for face in faces}
        for face in faces:
            self._history.setdefault(face.track_id, []).append(
                (timestamp, face.speaker_score)
            )
        cutoff = timestamp - self.config.window_seconds
        for track_id, history in list(self._history.items()):
            self._history[track_id] = [item for item in history if item[0] >= cutoff]
            if not self._history[track_id] and track_id != self.current_speaker_id:
                del self._history[track_id]

        scores = {
            track_id: float(np.mean([score for _, score in history]))
            for track_id, history in self._history.items()
            if history
        }
        current_score = scores.get(self.current_speaker_id, 0.0)

        if (
            len(faces) == 1
            and known_face_count == 1
            and self.current_speaker_id is None
        ):
            self.current_speaker_id = faces[0].track_id
            self._clear_candidate()
            return _SpeakerDecision(
                self.current_speaker_id,
                None,
                scores.get(self.current_speaker_id, 0.0),
                0.0,
                "single_face_initial",
                True,
            )

        challengers = [
            face for face in faces if face.track_id != self.current_speaker_id
        ]
        challenger = max(
            challengers,
            key=lambda face: scores.get(face.track_id, 0.0),
            default=None,
        )
        candidate_id = challenger.track_id if challenger else None
        candidate_score = scores.get(candidate_id, 0.0)
        only_visible_fallback = (
            len(faces) == 1 and self.current_speaker_id not in visible_ids
        )

        if challenger is None:
            self._clear_candidate()
            reason = (
                "current_speaker_retained"
                if self.current_speaker_id in visible_ids
                else "current_speaker_missing_hold_last_target"
            )
            return _SpeakerDecision(
                self.current_speaker_id,
                None,
                current_score,
                0.0,
                reason,
            )

        if (
            not only_visible_fallback
            and candidate_score < self.config.minimum_confidence
        ):
            self._clear_candidate()
            return _SpeakerDecision(
                self.current_speaker_id,
                candidate_id,
                current_score,
                candidate_score,
                "candidate_below_minimum_confidence",
            )

        if (
            not only_visible_fallback
            and candidate_score <= current_score + self.config.switch_margin
        ):
            self._clear_candidate()
            return _SpeakerDecision(
                self.current_speaker_id,
                candidate_id,
                current_score,
                candidate_score,
                "candidate_below_switch_margin",
            )

        if self.candidate_speaker_id != candidate_id:
            self.candidate_speaker_id = candidate_id
            self.candidate_since = timestamp
        candidate_since = (
            self.candidate_since if self.candidate_since is not None else timestamp
        )
        stable_for = timestamp - candidate_since
        if stable_for + 1e-9 < self.config.minimum_stable_duration:
            return _SpeakerDecision(
                self.current_speaker_id,
                candidate_id,
                current_score,
                candidate_score,
                (
                    "only_visible_face_stabilizing"
                    if only_visible_fallback
                    else "candidate_stabilizing"
                ),
            )

        self.current_speaker_id = candidate_id
        self._clear_candidate()
        return _SpeakerDecision(
            self.current_speaker_id,
            candidate_id,
            candidate_score,
            candidate_score,
            (
                "only_visible_face_stable"
                if only_visible_fallback
                else "candidate_stable_above_margin"
            ),
            True,
        )

    def _clear_candidate(self) -> None:
        self.candidate_speaker_id = None
        self.candidate_since = None


def build_crop_plan(
    video_path: Path,
    start_seconds: float,
    end_seconds: float,
    sample_interval: float = 0.4,
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
    selection_config = SpeakerSelectionConfig()
    tracker = _FaceTracker(selection_config.track_max_missing_seconds)
    selector = _SpeakerSelector(selection_config)
    audio_levels, audio_available = _extract_audio_activity(
        video_path, start_seconds, end_seconds, sample_interval
    )
    positions: list[tuple[float, float]] = []
    current_face_center: float | None = None
    smoothed_x = center_x
    previous_scene: np.ndarray | None = None
    shot_boundaries = [0.0]
    face_bin_counts: dict[int, int] = {}
    sample_count = 0
    face_sample_count = 0

    if settings.reframe_tracking_debug:
        logger.info(
            "tracking_config window_seconds=%.2f minimum_confidence=%.3f "
            "switch_margin=%.3f minimum_stable_duration=%.2f "
            "track_max_missing_seconds=%.2f audio_available=%s",
            selection_config.window_seconds,
            selection_config.minimum_confidence,
            selection_config.switch_margin,
            selection_config.minimum_stable_duration,
            selection_config.track_max_missing_seconds,
            audio_available,
        )

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
        scene = cv2.resize(small, (160, 90))
        scene_cut = False
        if previous_scene is not None:
            scene_change = float(np.mean(cv2.absdiff(scene, previous_scene)))
            if scene_change >= 18 and relative - shot_boundaries[-1] >= 0.8:
                shot_boundaries.append(round(relative, 2))
                tracker.reset()
                selector.reset()
                scene_cut = True
        previous_scene = scene
        frontal = list(cascade.detectMultiScale(
            small, scaleFactor=1.12, minNeighbors=5, minSize=(45, 45)
        ))
        profiles: list[tuple[int, int, int, int]] = []
        if not profile_cascade.empty():
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
        detected = _merge_face_detections(frontal + profiles)
        detections: list[_FaceDetection] = []
        for x, y, width, height in detected:
            x, y, width, height = [int(value / scale) for value in (x, y, width, height)]
            x = max(0, x)
            y = max(0, y)
            width = min(width, source_width - x)
            height = min(height, source_height - y)
            center = x + width / 2
            patch = gray[y : y + height, x : x + width]
            if patch.size == 0:
                continue
            patch = cv2.resize(patch, (64, 64))
            detections.append(
                _FaceDetection(
                    bbox=(float(x), float(y), float(width), float(height)),
                    patch=patch,
                )
            )
            bin_id = round(center / max(crop_width * 0.35, 1))
            face_bin_counts[bin_id] = face_bin_counts.get(bin_id, 0) + 1

        audio_score = (
            audio_levels[min(sample_count - 1, len(audio_levels) - 1)]
            if audio_levels
            else 0.0
        )
        faces = tracker.update(
            detections,
            relative,
            source_width,
            audio_score,
            audio_available,
        )
        decision = selector.update(
            relative,
            faces,
            known_face_count=tracker.active_track_count,
        )

        if faces:
            face_sample_count += 1

        target_face = next(
            (
                face
                for face in faces
                if face.track_id == decision.current_speaker_id
            ),
            None,
        )
        if target_face is not None:
            if current_face_center is None or decision.switched:
                current_face_center = target_face.center
            else:
                current_face_center = 0.7 * current_face_center + 0.3 * target_face.center
        if (
            decision.switched
            and relative > 0
            and relative - shot_boundaries[-1] >= 0.8
        ):
            shot_boundaries.append(round(relative, 2))

        _log_tracking_decision(
            relative,
            faces,
            decision,
            scene_cut=scene_cut,
            audio_available=audio_available,
        )

        target_x = (
            center_x
            if current_face_center is None
            else current_face_center - crop_width / 2
        )
        target_x = min(max(target_x, 0), max_x)
        smoothing = 0.45 if current_face_center is None else 0.32
        if decision.switched and relative > 0:
            # The renderer already expresses speaker changes as cuts. Start a
            # newly approved shot on its actual face instead of averaging the
            # old and new speakers into a crop that frames neither one.
            smoothed_x = target_x
        else:
            smoothed_x = (1 - smoothing) * smoothed_x + smoothing * target_x
        if target_face is not None:
            smoothed_x = _keep_face_in_safe_area(
                smoothed_x, target_face.center, crop_width, max_x
            )
        positions.append((round(relative, 2), round(smoothed_x, 1)))
        relative += sample_interval

    capture.release()
    if not positions:
        positions = [(0.0, center_x)]
    auto_layout = "crop"
    if framing_mode == "auto":
        # Frame wide dengan tiga orang atau lebih memakai satu group shot.
        # Komposisinya sama dengan panel atas layout stacked lama, tanpa panel
        # active-speaker kedua yang menduplikasi isi video.
        persistent_faces = sum(
            count >= max(3, sample_count * 0.25) for count in face_bin_counts.values()
        )
        if persistent_faces >= 3:
            auto_layout = "group"
        # Dua wajah dalam satu shot tidak otomatis berarti dua pembicara.
        # Prioritaskan crop pembicara; split tetap tersedia sebagai mode manual.
        elif not sample_count or face_sample_count / sample_count < 0.25:
            return CropPlan(
                source_width, source_height, crop_width, [(0.0, center_x)], "fit_blur"
            )
    positions = _stabilize_positions(
        positions,
        center_x,
        crop_width,
        max_x,
        boundaries=shot_boundaries,
    )
    positions = _lock_positions_to_shots(
        positions,
        crop_width=crop_width,
        shot_duration=2.4,
        boundaries=shot_boundaries,
    )
    return CropPlan(source_width, source_height, crop_width, positions, auto_layout)


def _association_score(
    track: _FaceTrack, detection: _FaceDetection, frame_width: int
) -> float | None:
    tx, ty, tw, th = track.bbox
    dx, dy, dw, dh = detection.bbox
    track_center = (tx + tw / 2, ty + th / 2)
    detection_center = (dx + dw / 2, dy + dh / 2)
    center_distance = math.hypot(
        track_center[0] - detection_center[0],
        track_center[1] - detection_center[1],
    )
    distance_scale = max(tw, th, dw, dh, frame_width * 0.04, 1)
    normalized_distance = center_distance / distance_scale
    track_area = max(tw * th, 1)
    detection_area = max(dw * dh, 1)
    size_similarity = min(track_area, detection_area) / max(track_area, detection_area)
    overlap = _intersection_over_union(track.bbox, detection.bbox)

    # A track can survive a missed sample, but it may not jump across the
    # frame to whichever face happens to be nearest on the next sample.
    if size_similarity < 0.3 or (overlap < 0.02 and normalized_distance > 1.25):
        return None

    upper_face = detection.patch[8:34, 10:54]
    previous_upper_face = track.patch[8:34, 10:54]
    appearance_difference = float(
        np.mean(cv2.absdiff(upper_face, previous_upper_face)) / 255
    )
    appearance_similarity = 1 - min(appearance_difference / 0.35, 1)
    proximity = 1 - min(normalized_distance / 1.25, 1)
    return (
        overlap * 2.0
        + proximity * 0.8
        + size_similarity * 0.45
        + appearance_similarity * 0.45
    )


def _mouth_activity(
    previous_bbox: tuple[float, float, float, float],
    previous_patch: np.ndarray,
    bbox: tuple[float, float, float, float],
    patch: np.ndarray,
) -> tuple[float, float]:
    """Return localized mouth motion and a head-motion penalty.

    Comparing the mouth with the upper face removes much of the lighting,
    camera, and whole-head motion that previously looked like speech.
    """
    mouth = patch[36:60, 14:50]
    previous_mouth = previous_patch[36:60, 14:50]
    upper_face = patch[8:34, 10:54]
    previous_upper_face = previous_patch[8:34, 10:54]
    mouth_delta = float(np.mean(cv2.absdiff(mouth, previous_mouth)) / 255)
    upper_delta = float(np.mean(cv2.absdiff(upper_face, previous_upper_face)) / 255)
    if upper_delta > 0.01 and mouth_delta <= upper_delta * 1.08:
        localized_motion = 0.0
    else:
        localized_motion = max(0.0, mouth_delta - upper_delta * 0.8)
    mouth_score = float(np.clip(localized_motion / 0.08, 0, 1))

    px, py, pw, ph = previous_bbox
    x, y, width, height = bbox
    center_delta = math.hypot(
        (px + pw / 2) - (x + width / 2),
        (py + ph / 2) - (y + height / 2),
    ) / max(pw, ph, width, height, 1)
    size_delta = abs((width * height) - (pw * ph)) / max(width * height, pw * ph, 1)
    head_motion = float(np.clip(center_delta + size_delta * 0.5, 0, 1))
    return mouth_score, head_motion


def _smooth_bbox(
    previous: tuple[float, float, float, float],
    current: tuple[float, float, float, float],
    smoothing: float = 0.35,
) -> tuple[float, float, float, float]:
    return tuple(
        (1 - smoothing) * old + smoothing * new
        for old, new in zip(previous, current)
    )


def _extract_audio_activity(
    video_path: Path,
    start_seconds: float,
    end_seconds: float,
    sample_interval: float,
) -> tuple[list[float], bool]:
    """Extract normalized mono energy for gating, never as speaker identity."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            return [], False

    duration = max(0.0, end_seconds - start_seconds)
    if duration <= 0 or sample_interval <= 0:
        return [], False
    sample_rate = 8000
    command = [
        ffmpeg,
        "-v",
        "error",
        "-ss",
        f"{start_seconds:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=max(15.0, duration * 0.5),
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], False
    if result.returncode != 0 or not result.stdout:
        return [], False

    samples = np.frombuffer(result.stdout, dtype=np.float32)
    samples_per_window = max(1, int(round(sample_rate * sample_interval)))
    energies = [
        float(np.sqrt(np.mean(np.square(samples[index : index + samples_per_window]))))
        for index in range(0, len(samples), samples_per_window)
        if len(samples[index : index + samples_per_window])
    ]
    if not energies:
        return [], False
    decibels = 20 * np.log10(np.asarray(energies, dtype=np.float64) + 1e-7)
    noise_floor = float(np.percentile(decibels, 20))
    voice_level = float(np.percentile(decibels, 85))
    dynamic_range = max(voice_level - noise_floor, 9.0)
    levels = np.clip((decibels - noise_floor) / dynamic_range, 0, 1)
    return [float(level) for level in levels], True


def _log_tracking_decision(
    timestamp: float,
    faces: list[_TrackedFace],
    decision: _SpeakerDecision,
    *,
    scene_cut: bool,
    audio_available: bool,
) -> None:
    if not settings.reframe_tracking_debug:
        return
    rows: list[_TrackedFace | None] = list(faces) or [None]
    for face in rows:
        bbox = (
            tuple(round(value, 1) for value in face.bbox)
            if face is not None
            else None
        )
        logger.info(
            "tracking_frame timestamp=%.2f track_id=%s face_bbox=%s "
            "speaker_score=%.3f audio_score=%.3f mouth_score=%.3f "
            "current_speaker_id=%s candidate_speaker_id=%s "
            "current_speaker_score=%.3f candidate_speaker_score=%.3f "
            "switch_reason=%s audio_available=%s scene_cut=%s",
            timestamp,
            face.track_id if face is not None else None,
            bbox,
            face.speaker_score if face is not None else 0.0,
            face.audio_score if face is not None else 0.0,
            face.mouth_score if face is not None else 0.0,
            decision.current_speaker_id,
            decision.candidate_speaker_id,
            decision.current_speaker_score,
            decision.candidate_speaker_score,
            decision.switch_reason,
            audio_available,
            scene_cut,
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
    boundaries: list[float] | None = None,
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
    boundary_times = {round(timestamp, 2) for timestamp in boundaries or []}

    for timestamp, raw_x in positions:
        correction = (raw_x - center_x) * follow_strength
        correction = min(max(correction, -max_offset), max_offset)
        target = min(max(center_x + correction, 0), max_x)
        difference = target - current
        elapsed = max(timestamp - previous_time, 0)
        if stabilized and round(timestamp, 2) in boundary_times:
            current = target
        elif stabilized and abs(difference) > dead_zone:
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
    boundaries: list[float] | None = None,
) -> list[tuple[float, float]]:
    """Kunci crop dan hanya pindah pada cut kamera/pergantian pembicara."""
    if len(positions) <= 1:
        return positions
    if boundaries:
        normalized = sorted({max(0.0, value) for value in boundaries})
        if not normalized or normalized[0] > 0:
            normalized.insert(0, 0.0)
        locked: list[tuple[float, float]] = []
        minimum_change = crop_width * 0.12
        for index, start in enumerate(normalized):
            end = normalized[index + 1] if index + 1 < len(normalized) else float("inf")
            values = [x for timestamp, x in positions if start <= timestamp < end]
            if not values:
                continue
            target = round(float(np.median(values)), 1)
            if locked and abs(target - locked[-1][1]) < minimum_change:
                continue
            locked.append((start, target))
        return locked or [positions[0]]

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
    # Area mulut berada di sepertiga bawah wajah; abaikan dahi/mata yang mudah
    # berubah karena kedipan atau gerakan kepala.
    lower = patch[40:62]
    old_lower = old_patch[40:62]
    return float(np.mean(cv2.absdiff(lower, old_lower)))


def _merge_face_detections(
    detections: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    """Gabungkan frontal/profile tanpa menghitung wajah yang sama dua kali."""
    merged: list[tuple[int, int, int, int]] = []
    for candidate in sorted(detections, key=lambda item: item[2] * item[3], reverse=True):
        if any(_same_face(candidate, existing) for existing in merged):
            continue
        merged.append(candidate)
    return merged


def _same_face(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> bool:
    if _intersection_over_union(first, second) >= 0.25:
        return True
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    horizontal = abs((ax + aw / 2) - (bx + bw / 2))
    vertical = abs((ay + ah / 2) - (by + bh / 2))
    return horizontal < max(aw, bw) * 0.55 and vertical < max(ah, bh) * 0.55


def _intersection_over_union(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left, top = max(ax, bx), max(ay, by)
    right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0, right - left) * max(0, bottom - top)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0.0


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
