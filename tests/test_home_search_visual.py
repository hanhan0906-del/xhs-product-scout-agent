import cv2
import numpy as np

from xhs_scout.home_search_visual import find_home_search_icon


def _write_image(path, image):
    success, encoded = cv2.imencode(".png", image)
    assert success
    encoded.tofile(path)


def _home_image(*, icon_x=1000, icon_y=136, draw_handle=True):
    image = np.full((2340, 1080, 3), 255, dtype=np.uint8)
    cv2.circle(image, (icon_x, icon_y), 18, (40, 40, 40), 5)
    if draw_handle:
        cv2.line(
            image,
            (icon_x + 13, icon_y + 13),
            (icon_x + 30, icon_y + 30),
            (40, 40, 40),
            5,
        )
    return image


def test_home_search_visual_finds_unique_top_right_magnifier(tmp_path):
    screenshot = tmp_path / "home.png"
    _write_image(screenshot, _home_image())

    target = find_home_search_icon(screenshot)

    assert target is not None
    assert abs(target.x - 1000) <= 3
    assert abs(target.y - 136) <= 3
    assert target.label == "首页搜索"
    assert target.reason == "home-search-visual-icon"


def test_home_search_visual_rejects_circle_without_handle(tmp_path):
    screenshot = tmp_path / "circle.png"
    _write_image(screenshot, _home_image(draw_handle=False))

    assert find_home_search_icon(screenshot) is None


def test_home_search_visual_rejects_magnifier_outside_safe_header_region(tmp_path):
    screenshot = tmp_path / "unsafe-region.png"
    _write_image(screenshot, _home_image(icon_x=760, icon_y=136))

    assert find_home_search_icon(screenshot) is None


def test_home_search_visual_rejects_ambiguous_candidates(tmp_path):
    screenshot = tmp_path / "ambiguous.png"
    image = _home_image(icon_x=950, icon_y=136)
    cv2.circle(image, (1030, 136), 18, (40, 40, 40), 5)
    cv2.line(image, (1043, 149), (1060, 166), (40, 40, 40), 5)
    _write_image(screenshot, image)

    assert find_home_search_icon(screenshot) is None


def test_home_search_visual_replays_real_home_screenshot():
    screenshot = (
        "data/probes/monitor-97bfcb656286-probe-start/current.png"
    )

    target = find_home_search_icon(screenshot)

    assert target is not None
    assert 985 <= target.x <= 1015
    assert 120 <= target.y <= 150
