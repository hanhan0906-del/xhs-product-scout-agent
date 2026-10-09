from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from .ui_automation import Bounds, UiTarget


def _direction_dark_ratio(
    gray: np.ndarray,
    *,
    x: int,
    y: int,
    radius: int,
    angle_degrees: float,
) -> float:
    angle = math.radians(angle_degrees)
    forward_x, forward_y = math.cos(angle), math.sin(angle)
    cross_x, cross_y = -forward_y, forward_x
    values: list[int] = []
    for distance in np.linspace(radius * 0.75, radius * 2.1, 30):
        for offset in np.linspace(-radius * 0.18, radius * 0.18, 9):
            sample_x = int(round(x + forward_x * distance + cross_x * offset))
            sample_y = int(round(y + forward_y * distance + cross_y * offset))
            if 0 <= sample_y < gray.shape[0] and 0 <= sample_x < gray.shape[1]:
                values.append(int(gray[sample_y, sample_x]))
    if not values:
        return 0.0
    return float(np.mean(np.asarray(values) < 145))


def _looks_like_magnifier(
    gray: np.ndarray,
    *,
    x: int,
    y: int,
    radius: int,
) -> bool:
    y1, y2 = max(0, y - radius * 2), min(gray.shape[0], y + radius * 2 + 1)
    x1, x2 = max(0, x - radius * 2), min(gray.shape[1], x + radius * 2 + 1)
    patch = gray[y1:y2, x1:x2]
    if patch.size == 0 or float(np.mean(patch)) < 175:
        return False

    patch_y, patch_x = np.ogrid[y1:y2, x1:x2]
    distance = np.sqrt((patch_x - x) ** 2 + (patch_y - y) ** 2)
    ring = patch[(distance >= radius * 0.72) & (distance <= radius * 1.25)]
    center = patch[distance <= radius * 0.48]
    if ring.size == 0 or center.size == 0:
        return False
    if float(np.mean(ring < 145)) < 0.22:
        return False
    if float(np.mean(center > 175)) < 0.82:
        return False

    down_right = _direction_dark_ratio(
        gray,
        x=x,
        y=y,
        radius=radius,
        angle_degrees=45,
    )
    other_directions = max(
        _direction_dark_ratio(
            gray,
            x=x,
            y=y,
            radius=radius,
            angle_degrees=angle,
        )
        for angle in (135, 225, 315)
    )
    return down_right >= 0.30 and down_right - other_directions >= 0.10


def find_home_search_icon(screenshot: str | Path) -> UiTarget | None:
    """Find one verified magnifier icon in the home header's top-right region.

    This is deliberately a visual fallback for builds whose accessibility tree
    omits the header. It derives the tap point from the detected circle and
    refuses ambiguous or incomplete shapes instead of guessing a coordinate.
    The caller must additionally verify that the current page is the XHS home
    feed before using the returned target.
    """

    screenshot = Path(screenshot)
    if not screenshot.is_file():
        return None
    encoded = np.fromfile(screenshot, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        return None

    height, width = image.shape[:2]
    roi_x1 = int(width * 0.82)
    roi_x2 = int(width * 0.985)
    roi_y1 = int(height * 0.02)
    roi_y2 = int(height * 0.10)
    roi = image[roi_y1:roi_y2, roi_x1:roi_x2]
    if roi.size == 0:
        return None

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    roi_gray = cv2.GaussianBlur(
        cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY),
        (5, 5),
        1.2,
    )
    min_radius = max(8, int(width * 0.010))
    max_radius = max(min_radius + 2, int(width * 0.028))
    circles = cv2.HoughCircles(
        roi_gray,
        cv2.HOUGH_GRADIENT,
        1.2,
        max(16, min_radius * 2),
        param1=100,
        param2=18,
        minRadius=min_radius,
        maxRadius=max_radius,
    )
    if circles is None:
        return None

    candidates: list[tuple[int, int, int]] = []
    for local_x, local_y, radius in np.round(circles[0]).astype(int):
        x = roi_x1 + int(local_x)
        y = roi_y1 + int(local_y)
        radius = int(radius)
        if not (int(width * 0.86) <= x <= int(width * 0.97)):
            continue
        if not _looks_like_magnifier(gray, x=x, y=y, radius=radius):
            continue
        candidates.append((x, y, radius))

    if len(candidates) != 1:
        return None
    x, y, radius = candidates[0]
    return UiTarget(
        x=x,
        y=y,
        bounds=Bounds(x - radius, y - radius, x + radius, y + radius),
        label="首页搜索",
        reason="home-search-visual-icon",
    )
