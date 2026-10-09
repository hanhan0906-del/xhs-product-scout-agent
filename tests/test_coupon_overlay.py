from pathlib import Path

import cv2
import numpy as np
import pytest

from xhs_scout.coupon_overlay import find_coupon_close_button


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "relative_path",
    [
        "data/probes/monitor-4460fba28109-probe-start/current.png",
        "data/probes/monitor-ebf25783933a-seller-after-25/current.png",
    ],
)
def test_real_coupon_overlay_has_one_visual_x_target(relative_path):
    target = find_coupon_close_button(PROJECT_ROOT / relative_path)

    assert target is not None
    assert abs(target.x - 539) <= 3
    assert abs(target.y - 1720) <= 3
    assert "circular X" in target.reason


@pytest.mark.parametrize(
    "relative_path",
    [
        "data/probes/monitor-ebf25783933a-seller-coupon-25/current.png",
        "data/probes/monitor-ebf25783933a-probe-detail-25/current.png",
        "data/probes/monitor-ebf25783933a-probe-search-results/current.png",
        "data/probes/monitor-ebf25783933a-probe-start/current.png",
    ],
)
def test_real_non_overlay_screens_have_no_visual_x_target(relative_path):
    assert find_coupon_close_button(PROJECT_ROOT / relative_path) is None


def _write_shape(tmp_path, name, draw):
    image = np.full((2340, 1080, 3), 80, dtype=np.uint8)
    draw(image)
    path = tmp_path / name
    assert cv2.imwrite(str(path), image)
    return path


def _circle(image, center=(540, 1720), *, mark="x"):
    cv2.circle(image, center, 28, (220, 220, 220), 3, cv2.LINE_AA)
    if mark == "x":
        cv2.line(image, (center[0] - 13, center[1] - 13), (center[0] + 13, center[1] + 13), (220, 220, 220), 4, cv2.LINE_AA)
        cv2.line(image, (center[0] - 13, center[1] + 13), (center[0] + 13, center[1] - 13), (220, 220, 220), 4, cv2.LINE_AA)
    elif mark == "slash":
        cv2.line(image, (center[0] - 13, center[1] - 13), (center[0] + 13, center[1] + 13), (220, 220, 220), 4, cv2.LINE_AA)
    elif mark == "plus":
        cv2.line(image, (center[0] - 14, center[1]), (center[0] + 14, center[1]), (220, 220, 220), 4, cv2.LINE_AA)
        cv2.line(image, (center[0], center[1] - 14), (center[0], center[1] + 14), (220, 220, 220), 4, cv2.LINE_AA)


@pytest.mark.parametrize("mark", [None, "slash", "plus"])
def test_circle_without_two_diagonal_x_strokes_is_rejected(tmp_path, mark):
    path = _write_shape(
        tmp_path,
        f"{mark or 'hollow'}.png",
        lambda image: _circle(image, mark=mark),
    )
    assert find_coupon_close_button(path) is None


def test_large_rounded_card_is_not_a_close_circle(tmp_path):
    def draw(image):
        cv2.rectangle(image, (410, 1640), (670, 1800), (220, 220, 220), 4, cv2.LINE_AA)
        cv2.line(image, (527, 1707), (553, 1733), (220, 220, 220), 4, cv2.LINE_AA)
        cv2.line(image, (527, 1733), (553, 1707), (220, 220, 220), 4, cv2.LINE_AA)

    assert find_coupon_close_button(_write_shape(tmp_path, "rounded.png", draw)) is None


def test_multiple_valid_visual_x_controls_are_rejected(tmp_path):
    def draw(image):
        _circle(image, (540, 1600))
        _circle(image, (540, 1780))

    assert find_coupon_close_button(_write_shape(tmp_path, "multiple.png", draw)) is None


def test_unreadable_image_is_rejected(tmp_path):
    assert find_coupon_close_button(tmp_path / "missing.png") is None
