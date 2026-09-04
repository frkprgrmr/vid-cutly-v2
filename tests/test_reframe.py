import numpy as np

from backend.reframe import (
    CropPlan,
    SpeakerSelectionConfig,
    _FaceDetection,
    _FaceTracker,
    _SpeakerSelector,
    _TrackedFace,
    _keep_face_in_safe_area,
    _lock_positions_to_shots,
    _merge_face_detections,
    _mouth_activity,
    _stabilize_positions,
    crop_expression,
)


def test_crop_expression_cuts_between_locked_positions():
    plan = CropPlan(
        source_width=1920,
        source_height=1080,
        crop_width=608,
        positions=[(0.0, 100.0), (1.5, 240.0), (3.0, 350.0)],
    )
    expression = crop_expression(plan)
    assert "if(lt(t\\,1.50)" in expression
    assert "350.0" in expression
    assert "*(t-" not in expression


def test_face_is_kept_away_from_crop_edges():
    assert _keep_face_in_safe_area(850, 870, 608, 1312) == 736.24
    assert _keep_face_in_safe_area(100, 1188, 608, 1312) == 713.76


def test_stabilized_tracking_limits_offset_and_pan_speed():
    raw = [(0.0, 656.0), (1.5, 1296.0), (3.0, 460.0), (4.5, 1296.0)]
    stable = _stabilize_positions(raw, center_x=656, crop_width=608, max_x=1312)

    assert stable[0][1] == 656
    assert stable[1][1] > 800
    assert all(0 <= x <= 1312 for _, x in stable)
    assert all(
        abs(current[1] - previous[1]) / (current[0] - previous[0]) <= 608 * 0.22 + 0.1
        for previous, current in zip(stable, stable[1:])
    )


def test_stabilized_tracking_cuts_directly_on_approved_boundary():
    raw = [(0.0, 656.0), (0.4, 656.0), (0.8, 1000.0), (1.2, 1000.0)]

    stable = _stabilize_positions(
        raw,
        center_x=656,
        crop_width=608,
        max_x=1312,
        boundaries=[0.0, 0.8],
    )

    assert stable[2][1] == 948.4


def test_tracking_is_locked_into_stable_five_second_shots():
    positions = [
        (0.0, 500.0),
        (1.0, 540.0),
        (2.0, 520.0),
        (5.0, 900.0),
        (6.0, 940.0),
        (10.0, 910.0),
    ]

    locked = _lock_positions_to_shots(positions, crop_width=608)

    assert locked == [(0.0, 520.0), (5.0, 920.0)]


def test_tracking_cuts_on_detected_shot_boundaries():
    positions = [
        (0.0, 500.0),
        (0.4, 520.0),
        (0.8, 510.0),
        (1.2, 900.0),
        (1.6, 920.0),
        (2.0, 910.0),
    ]

    locked = _lock_positions_to_shots(
        positions, crop_width=608, boundaries=[0.0, 1.2]
    )

    assert locked == [(0.0, 510.0), (1.2, 910.0)]


def test_frontal_and_profile_detections_for_same_face_are_merged():
    detections = [(100, 100, 120, 120), (118, 105, 115, 118), (700, 100, 120, 120)]

    merged = _merge_face_detections(detections)

    assert len(merged) == 2


def _tracked_face(track_id: int, score: float, x: float) -> _TrackedFace:
    return _TrackedFace(
        track_id=track_id,
        bbox=(x, 100.0, 120.0, 120.0),
        mouth_score=score,
        audio_score=0.8,
        speaker_score=score,
    )


def test_face_tracker_keeps_ids_when_detection_order_changes():
    tracker = _FaceTracker(max_missing_seconds=1.2)
    patch = np.zeros((64, 64), dtype=np.uint8)
    first = tracker.update(
        [
            _FaceDetection((100.0, 100.0, 120.0, 120.0), patch),
            _FaceDetection((600.0, 100.0, 120.0, 120.0), patch),
        ],
        timestamp=0.0,
        frame_width=1280,
        audio_score=0.8,
        audio_available=True,
    )
    second = tracker.update(
        [
            _FaceDetection((610.0, 102.0, 120.0, 120.0), patch),
            _FaceDetection((108.0, 101.0, 120.0, 120.0), patch),
        ],
        timestamp=0.4,
        frame_width=1280,
        audio_score=0.8,
        audio_available=True,
    )

    assert [(face.track_id, round(face.center)) for face in first] == [(1, 160), (2, 660)]
    assert [(face.track_id, round(face.center)) for face in second] == [(1, 163), (2, 664)]


def test_face_tracker_keeps_id_across_a_short_missed_detection():
    tracker = _FaceTracker(max_missing_seconds=1.2)
    patch = np.zeros((64, 64), dtype=np.uint8)
    detection = _FaceDetection((100.0, 100.0, 120.0, 120.0), patch)

    assert tracker.update([detection], 0.0, 1280, 0.0, False)[0].track_id == 1
    assert tracker.update([], 0.4, 1280, 0.0, False) == []
    observed_again = tracker.update(
        [_FaceDetection((110.0, 100.0, 120.0, 120.0), patch)],
        0.8,
        1280,
        0.0,
        False,
    )

    assert observed_again[0].track_id == 1


def test_whole_face_brightness_change_is_not_mouth_activity():
    previous = np.zeros((64, 64), dtype=np.uint8)
    brighter = np.full((64, 64), 30, dtype=np.uint8)

    mouth_score, _ = _mouth_activity(
        (100.0, 100.0, 120.0, 120.0),
        previous,
        (100.0, 100.0, 120.0, 120.0),
        brighter,
    )

    assert mouth_score == 0.0


def test_localized_mouth_change_produces_activity():
    previous = np.zeros((64, 64), dtype=np.uint8)
    mouth_changed = previous.copy()
    mouth_changed[36:60, 14:50] = 30

    mouth_score, _ = _mouth_activity(
        (100.0, 100.0, 120.0, 120.0),
        previous,
        (100.0, 100.0, 120.0, 120.0),
        mouth_changed,
    )

    assert mouth_score > 0.9


def test_single_face_is_selected_immediately():
    selector = _SpeakerSelector(SpeakerSelectionConfig())

    decision = selector.update(0.0, [_tracked_face(7, 0.0, 100.0)])

    assert decision.current_speaker_id == 7
    assert decision.switch_reason == "single_face_initial"


def test_single_detection_is_not_immediate_when_another_track_is_recent():
    selector = _SpeakerSelector(SpeakerSelectionConfig())

    decision = selector.update(
        0.0,
        [_tracked_face(7, 0.0, 100.0)],
        known_face_count=2,
    )

    assert decision.current_speaker_id is None
    assert decision.switch_reason == "only_visible_face_stabilizing"


def test_only_visible_face_replaces_missing_speaker_after_stable_duration():
    selector = _SpeakerSelector(
        SpeakerSelectionConfig(minimum_stable_duration=0.8)
    )
    selector.update(0.0, [_tracked_face(1, 0.0, 100.0)])

    decisions = [
        selector.update(timestamp, [_tracked_face(2, 0.0, 600.0)])
        for timestamp in (0.4, 0.8, 1.2)
    ]

    assert [decision.current_speaker_id for decision in decisions] == [1, 1, 2]
    assert decisions[-1].switch_reason == "only_visible_face_stable"


def test_one_frame_challenger_does_not_replace_current_speaker():
    selector = _SpeakerSelector(
        SpeakerSelectionConfig(
            window_seconds=1.6,
            minimum_confidence=0.2,
            switch_margin=0.1,
            minimum_stable_duration=0.8,
        )
    )
    selector.update(0.0, [_tracked_face(1, 0.0, 100.0)])
    pending = selector.update(
        0.4,
        [_tracked_face(1, 0.25, 100.0), _tracked_face(2, 0.9, 600.0)],
    )
    retained = selector.update(0.8, [_tracked_face(1, 0.25, 100.0)])

    assert pending.switch_reason == "candidate_stabilizing"
    assert retained.current_speaker_id == 1
    assert retained.switch_reason == "current_speaker_retained"


def test_consistent_challenger_switches_only_after_stable_duration():
    selector = _SpeakerSelector(
        SpeakerSelectionConfig(
            window_seconds=1.6,
            minimum_confidence=0.2,
            switch_margin=0.1,
            minimum_stable_duration=0.8,
        )
    )
    selector.update(0.0, [_tracked_face(1, 0.0, 100.0)])

    decisions = [
        selector.update(
            timestamp,
            [_tracked_face(1, 0.2, 100.0), _tracked_face(2, 0.8, 600.0)],
        )
        for timestamp in (0.4, 0.8, 1.2)
    ]

    assert [decision.current_speaker_id for decision in decisions] == [1, 1, 2]
    assert decisions[-1].switch_reason == "candidate_stable_above_margin"
