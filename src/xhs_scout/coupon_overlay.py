from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .ui_automation import Bounds, UiTarget


COUPON_ACTIVITY = "XhsReactTranslucentActivity"


def coupon_overlay_text_present(text: str) -> bool:
    normalized = "".join((text or "").split())
    legacy_coupon = "恭喜获得" in normalized and (
        "关注并领取" in normalized or "立即使用" in normalized
    )
    claimed_merchant_coupon = (
        "恭喜你领券成功" in normalized and "立即使用" in normalized
    )
    return legacy_coupon or claimed_merchant_coupon


def find_coupon_close_button(screenshot: str | Path) -> UiTarget | None:
    """Return the one high-confidence circular X control in the coupon ROI.

    OCR is deliberately irrelevant and there is no coordinate fallback. A
    candidate needs a circular boundary and two crossing diagonal strokes;
    ambiguous screenshots fail closed.
    """

    screenshot = Path(screenshot)
    try:
        encoded = np.fromfile(screenshot, dtype=np.uint8)
    except OSError:
        return None
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        return None
    height, width = image.shape[:2]
    raw_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(raw_gray, (5, 5), 1.2)
    min_radius = max(10, int(width * 0.016))
    # The captured control is close to 2.5% of screen width. This narrow band
    # rejects card corners and floating CTA controls before shape validation.
    max_radius = max(min_radius + 3, int(width * 0.035))
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        1.2,
        max(16, min_radius * 2),
        param1=100,
        param2=25,
        minRadius=min_radius,
        maxRadius=max_radius,
    )
    if circles is None:
        return None

    def shape_scores(x: int, y: int, radius: int) -> tuple[float, float] | None:
        margin = radius + 3
        if x - margin < 0 or y - margin < 0 or x + margin >= width or y + margin >= height:
            return None
        patch = raw_gray[y - margin : y + margin + 1, x - margin : x + margin + 1]
        center = margin
        yy, xx = np.ogrid[: patch.shape[0], : patch.shape[1]]
        distance = np.sqrt((xx - center) ** 2 + (yy - center) ** 2)
        edges = cv2.Canny(cv2.GaussianBlur(patch, (3, 3), 0.8), 45, 130)

        ring = (distance >= radius * 0.78) & (distance <= radius * 1.18)
        circle_score = float(np.count_nonzero(edges[ring])) / max(
            1, int(np.count_nonzero(ring))
        )
        if circle_score < 0.16:
            return None

        inner_edges = edges.copy()
        inner_edges[distance > radius * 0.72] = 0
        lines = cv2.HoughLinesP(
            inner_edges,
            1,
            np.pi / 180,
            threshold=max(7, int(radius * 0.30)),
            minLineLength=max(8, int(radius * 0.55)),
            maxLineGap=max(2, int(radius * 0.16)),
        )
        if lines is None:
            return None

        orientations: dict[int, float] = {}
        for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
            dx = float(x2 - x1)
            dy = float(y2 - y1)
            length = float(np.hypot(dx, dy))
            if length == 0:
                continue
            angle = (float(np.degrees(np.arctan2(dy, dx))) + 180.0) % 180.0
            family = 1 if 28.0 <= angle <= 62.0 else -1 if 118.0 <= angle <= 152.0 else 0
            if not family:
                continue
            ux, uy = dx / length, dy / length
            cx1, cy1 = x1 - center, y1 - center
            cx2, cy2 = x2 - center, y2 - center
            perpendicular = abs(cx1 * uy - cy1 * ux)
            projections = (cx1 * ux + cy1 * uy, cx2 * ux + cy2 * uy)
            symmetry = min(abs(min(projections)), abs(max(projections))) / max(
                abs(min(projections)), abs(max(projections)), 1.0
            )
            if (
                perpendicular <= radius * 0.20
                and min(projections) <= -radius * 0.22
                and max(projections) >= radius * 0.22
                and symmetry >= 0.40
            ):
                orientations[family] = max(
                    orientations.get(family, 0.0), length / radius
                )
        if set(orientations) != {-1, 1}:
            return None

        core = distance <= radius * 0.15
        surround = (distance >= radius * 0.28) & (distance <= radius * 0.52)
        contrast = abs(
            float(np.mean(patch[core])) - float(np.median(patch[surround]))
        )
        if contrast < 18.0:
            return None
        x_score = min(orientations[-1], orientations[1], 2.0) / 2.0
        return circle_score, x_score

    validated: list[tuple[int, int, int, float, float]] = []
    for x, y, radius in np.round(circles[0]).astype(int):
        x, y, radius = int(x), int(y), int(radius)
        if (
            abs(x - width // 2) > max(8, int(width * 0.012))
            or not (int(height * 0.62) <= y <= int(height * 0.84))
            or not (min_radius <= radius <= max_radius)
        ):
            continue
        scores = shape_scores(x, y, radius)
        if scores is not None:
            validated.append((x, y, radius, scores[0], scores[1]))

    unique: list[tuple[int, int, int, float, float]] = []
    for candidate in sorted(
        validated, key=lambda item: item[3] + item[4], reverse=True
    ):
        if any(
            np.hypot(candidate[0] - item[0], candidate[1] - item[1])
            <= min(candidate[2], item[2]) * 0.45
            for item in unique
        ):
            continue
        unique.append(candidate)
    if len(unique) != 1:
        return None
    x, y, radius, circle_score, x_score = unique[0]
    return UiTarget(
        x=x,
        y=y,
        bounds=Bounds(x - radius, y - radius, x + radius, y + radius),
        label="优惠券关闭",
        reason=(
            "unique centered circular X coupon close button "
            f"(circle={circle_score:.2f}, x={x_score:.2f})"
        ),
    )
