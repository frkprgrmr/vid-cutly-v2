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


def test_dynamic_filter_animates_foreground_over_blurred_background():
    dynamic = plan("dynamic")
    dynamic.viewports = [(0.0, 3412.0, -1200.0), (2.0, 1080.0, 0.0)]
    graph = _video_filter_graph(dynamic, "656", "captions.ass")

    assert "scale=w='trunc((" in graph
    assert "eval=frame" in graph
    assert "gblur=sigma=32" in graph
    assert "overlay=x='" in graph


def test_thumbnail_layouts_are_portrait():
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    dynamic = plan("dynamic")
    dynamic.viewports = [(0.0, 1080.0, 0.0)]

    assert _portrait_frame(frame, plan("fit_blur")).shape == (1920, 1080, 3)
    assert _portrait_frame(frame, dynamic).shape == (1920, 1080, 3)
