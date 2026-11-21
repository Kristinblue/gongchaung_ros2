"""用紫色定位单个安全区，再用多边形内部的红蓝像素判断颜色。"""

from dataclasses import dataclass, field

import cv2
import numpy as np


GAUSSIAN_KERNEL_SIZE = 3
CLOSE_KERNEL_SIZE = 5
CLOSE_KERNEL = np.ones((CLOSE_KERNEL_SIZE, CLOSE_KERNEL_SIZE), np.uint8)
FRAME_EDGE_MARGIN = 3
NEARBY_GAP_RATIO = .45
MIN_FRAGMENT_RATIO = .12
MIN_VISIBLE_INTERIOR = .14
RED_LIMITS = {'h_min': 155, 'h_max': 2, 's_min': 70, 's_max': 255, 'v_min': 35, 'v_max': 255}
BLUE_LIMITS = {'h_min': 98, 'h_max': 145, 's_min': 22, 's_max': 150, 'v_min': 35, 'v_max': 255}
MIN_COLOR_FRACTION = .12

DEFAULTS = {
    'h_min':125, 'h_max':155,
    's_min':100, 's_max':255,
    'v_min':25, 'v_max':255,
}


@dataclass
class Safety:
    """一帧的安全区属性、状态和调试数据。"""

    flag: str = 'safety'
    status: dict[str, bool] = field(default_factory=lambda: {'detected': False, 'full': False, 'ok': False})
    roi: tuple[int, int, int, int] | None = None
    points: np.ndarray | None = None
    mask: np.ndarray | None = None
    red_mask: np.ndarray | None = None
    blue_mask: np.ndarray | None = None
    red_fraction: float = 0.
    blue_fraction: float = 0.
    purple_fraction: float = 0.

    def draw_result(self, image):
        """生成紫色掩膜、红蓝掩膜和叠画多边形的三张调试图。"""
        mask = np.zeros(image.shape[:2], np.uint8)
        colors = np.zeros_like(image)
        overlay = image.copy()
        if self.roi is None:
            return mask, colors, overlay

        x1, y1, x2, y2 = self.roi
        mask[y1:y2, x1:x2] = self.mask
        if self.red_mask is not None:
            colors[y1:y2, x1:x2, 2] = self.red_mask
            colors[y1:y2, x1:x2, 0] = self.blue_mask
        if self.points is not None:
            color = (0, 220, 255) if self.status['full'] else (0, 130, 255)
            cv2.polylines(overlay, [self.points], True, color, 2, cv2.LINE_AA)
            cv2.polylines(colors, [self.points], True, (150, 150, 150), 1, cv2.LINE_AA)
        return mask, colors, overlay


class SafetyDetector:
    """在整张图上找紫边，再在安全区多边形内判色。"""

    def __init__(self, settings=None):
        self.settings = DEFAULTS | (settings or {})

    def detect(self, image):
        """识别一帧，返回 Safety，坐标使用原图像素。"""
        height, width = image.shape[:2]
        original_purple, closed = self._purple_mask(image)
        roi, hull = self._find_roi(closed)
        safety = Safety(roi=roi)
        if roi is None:
            return safety

        x1, y1, x2, y2 = roi
        safety.mask = closed[y1:y2, x1:x2]
        if cv2.contourArea(hull) < max(650, height * width * .001):
            return safety

        points = cv2.approxPolyDP(hull, .004 * cv2.arcLength(hull, True), True)
        margin = min(x1, y1, width - x2, height - y2)
        _, sides, _ = cv2.minAreaRect(hull)
        has_depth = min(sides) >= .075 * max(sides)
        safety.status['detected'] = True
        safety.status['full'] = bool(margin >= FRAME_EDGE_MARGIN and has_depth)
        safety.points = points[:, 0]
        self._classify_color(image, original_purple, safety)
        return safety

    def _purple_mask(self, image):
        """返回紫色阈值掩膜和闭运算补缝后的掩膜。"""
        smoothed = cv2.GaussianBlur(image, (GAUSSIAN_KERNEL_SIZE, GAUSSIAN_KERNEL_SIZE), 0)
        hsv = cv2.cvtColor(smoothed, cv2.COLOR_BGR2HSV)
        mask = self._hsv_mask(hsv, self.settings)
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, CLOSE_KERNEL)
        return mask, closed

    @staticmethod
    def _hsv_mask(hsv, limits):
        """按一组HSV阈值生成掩膜，H使用0～179，允许跨越色相零点。"""
        low = (limits['h_min'], limits['s_min'], limits['v_min'])
        high = (limits['h_max'], limits['s_max'], limits['v_max'])
        if low[0] <= high[0]:
            return cv2.inRange(hsv, low, high)
        # 跨过零点时，先筛 S/V，再从掩膜中扣掉两段红色之间的色相。
        sv = cv2.inRange(hsv, (0, low[1], low[2]), (179, high[1], high[2]))
        middle = cv2.inRange(cv2.extractChannel(hsv, 0), high[0] + 1, low[0] - 1)
        return cv2.subtract(sv, middle, dst=sv)

    @staticmethod
    def _find_roi(mask):
        """把最大紫块和附近够大的紫块一起圈起来，返回搜索框和凸包。"""
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, None

        regions = [(contour, cv2.contourArea(contour)) for contour in contours]
        anchor, area = max(regions, key=lambda region: region[1])
        if area < 40:
            return None, None

        x, y, w, h = cv2.boundingRect(anchor)
        gap = NEARBY_GAP_RATIO * max(w, h)
        left, top, right, bottom = x - gap, y - gap, x + w + gap, y + h + gap
        min_fragment_area = max(40, area * MIN_FRAGMENT_RATIO)
        selected = [anchor]
        for contour, fragment_area in regions:
            if contour is anchor or fragment_area < min_fragment_area:
                continue
            # 始终和最大紫块比，避免通过碎片把搜索框一路扩到远处。
            px, py = contour[:, 0].T
            if np.any((left <= px) & (px <= right) & (top <= py) & (py <= bottom)):
                selected.append(contour)

        hull = cv2.convexHull(np.concatenate(selected))
        x, y, w, h = cv2.boundingRect(hull)
        return (x, y, x + w, y + h), hull

    def _classify_color(self, image, purple, safety):
        """统计多边形内红、蓝、紫像素各占整个多边形的比例。"""
        x1, y1, x2, y2 = safety.roi
        interior = np.zeros((y2 - y1, x2 - x1), np.uint8)
        points = safety.points - np.array((x1, y1), dtype=np.int32)
        cv2.fillPoly(interior, [points], 255)
        area = cv2.countNonZero(interior)
        cv2.subtract(interior, purple[y1:y2, x1:x2], dst=interior)
        count = cv2.countNonZero(interior)
        safety.purple_fraction = (area - count) / area
        safety.status['full'] = safety.status['full'] and count >= area * MIN_VISIBLE_INTERIOR
        if not count:
            return

        hsv = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
        red = self._hsv_mask(hsv, RED_LIMITS)
        cv2.bitwise_and(red, interior, dst=red)
        blue = cv2.bitwise_and(self._hsv_mask(hsv, BLUE_LIMITS), interior)
        red_count, blue_count = cv2.countNonZero(red), cv2.countNonZero(blue)
        safety.red_mask, safety.blue_mask = red, blue
        safety.red_fraction, safety.blue_fraction = red_count / area, blue_count / area
        min_pixels = area * MIN_COLOR_FRACTION
        red_count = red_count if red_count >= min_pixels else 0
        blue_count = blue_count if blue_count >= min_pixels else 0
        if red_count != blue_count:
            safety.flag = 'r_safety' if red_count > blue_count else 'b_safety'
            safety.status['ok'] = safety.status['full']
