import numpy as np

from backend.reframe import CropPlan
from backend.render import _portrait_frame, _video_filter_graph


def plan(layout: str) -> CropPlan:
    return CropPlan(1920, 1080, 608, [(0.0, 656.0)], layout)


def test_fit_blur_filter_keeps_full_frame_over_blurred_background():
    graph = _video_filter_graph(plan("fit_blur"), "656", "captions.ass")

    assert "gblur=sigma=32" in graph
    assert "force_original_aspect_ratio=decrease" in graph
    assert graph.endswith("[base]")


def test_split_filter_stacks_left_and_right_views():
    graph = _video_filter_graph(plan("split"), "656", "captions.ass")

    assert "crop=iw/2:ih:0:0" in graph
    assert "crop=iw/2:ih:iw/2:0" in graph
    assert "vstack=inputs=2" in graph


def test_stacked_filter_keeps_group_shot_and_active_speaker():
    graph = _video_filter_graph(plan("stacked"), "656", "captions.ass")

    assert "[group]scale=1080:960" in graph
    assert "[speaker]crop=608:1080" in graph
    assert "[groupframe][speakerframe]vstack=inputs=2" in graph


def test_group_filter_keeps_only_the_old_upper_composition():
    graph = _video_filter_graph(plan("group"), "656", "captions.ass")

    assert "[groupfg]scale=1080:960" in graph
    assert "crop=1080:960[groupframe]" in graph
    assert "[blurred][groupframe]overlay=0:(H-h)/2" in graph
    assert "[speaker]" not in graph
    assert "vstack" not in graph


def test_thumbnail_layouts_are_portrait():
    frame = np.zeros((360, 640, 3), dtype=np.uint8)

    assert _portrait_frame(frame, plan("fit_blur")).shape == (1920, 1080, 3)
    assert _portrait_frame(frame, plan("split")).shape == (1920, 1080, 3)
    assert _portrait_frame(frame, plan("group")).shape == (1920, 1080, 3)
