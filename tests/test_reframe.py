from backend.reframe import (
    CropPlan,
    _build_shot_viewports,
    _keep_face_in_safe_area,
    _stabilize_positions,
    crop_expression,
)


def test_crop_expression_interpolates_positions():
    plan = CropPlan(
        source_width=1920,
        source_height=1080,
        crop_width=608,
        positions=[(0.0, 100.0), (1.5, 240.0), (3.0, 350.0)],
    )
    expression = crop_expression(plan)
    assert "if(lt(t\\,1.50)" in expression
    assert "350.0" in expression


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


def test_dynamic_viewports_become_stable_five_second_shots():
    raw = [
        (0.0, 3400.0, -2000.0),
        (1.0, 3400.0, -1800.0),
        (2.0, 3400.0, -1600.0),
        (5.0, 1800.0, -500.0),
        (6.0, 1750.0, -480.0),
    ]

    shots = _build_shot_viewports(
        raw, source_width=1920, crop_width=608, duration=10
    )

    assert shots[0][0] == 0
    assert shots[1][0] == 4.775
    assert shots[1][1:] == shots[0][1:]
    assert shots[2][0] == 5.225
    assert shots[-1][0] == 10
    assert len(shots) == 4
