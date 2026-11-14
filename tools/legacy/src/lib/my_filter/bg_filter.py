"""
过滤背景防止误识别

摄像头抬的比较高的时候，会看到背景，可能误判，应当把这些全部去掉

需要知道此时的摄像头角度，这个摄像头是自己通过，串口发送控制的

发送cmd为
"""

import math

import numpy as np


class BackgroundFilter:
    """按镜头俯角过滤地平线上方的检测，不依赖仿真坐标或模型类型。"""

    def __init__(self, enabled=True, horizontal_fov_deg=70., horizon_margin_px=16., pitch_offset_deg=0., cy_ratio=.5):
        """设置相机近似内参，0度水平、90度朝下。

        Args:
            enabled: 是否启用。
            horizontal_fov_deg: 水平视场角，未标定时仅作近似。
            horizon_margin_px: 地平线向上留出的像素余量，避免误删远处目标。
            pitch_offset_deg: 舵机角到镜头实际俯角的修正。
            cy_ratio: 主点纵坐标占图像高度比例。
        """
        if not 0<horizontal_fov_deg<180 or horizon_margin_px<0 or not 0<=cy_ratio<=1:
            raise ValueError('[BackgroundFilter] 视场角、余量或主点比例不正确')
        self.enabled = bool(enabled)
        self.horizontal_fov_deg = float(horizontal_fov_deg)
        self.margin = float(horizon_margin_px)
        self.pitch_offset = float(pitch_offset_deg)
        self.cy_ratio = float(cy_ratio)
        self.last = {'removed':0,'cutoff_y':None,'pitch_deg':None}

    def cutoff(self, width, height, pitch_deg):
        """返回检测框底边允许的最小行；角度未知时不猜测背景范围。"""
        if not self.enabled or pitch_deg is None or not math.isfinite(float(pitch_deg)):
            return None
        pitch = float(pitch_deg)+self.pitch_offset
        if not -89.<pitch<89.:
            return 0. if pitch>=89. else float(height)
        focal = width/(2*math.tan(math.radians(self.horizontal_fov_deg)/2))
        return max(0.,min(float(height),height*self.cy_ratio-focal*math.tan(math.radians(pitch))-self.margin))

    def filter(self, boxes, classes, scores, image_shape, pitch_deg):
        """保留底边落在地面视域的框，跨越地平线的物体仍保留。

        Args:
            boxes: Nx4像素框，格式xyxy。
            classes: N个类别编号。
            scores: N个置信度。
            image_shape: 输入图像shape。
            pitch_deg: 优先用实际反馈；没有反馈时用最近发送的相机角。

        Returns:
            过滤后的boxes/classes/scores，保持原始顺序及坐标。
        """
        boxes = np.asarray(boxes).reshape(-1,4)
        classes, scores = np.asarray(classes), np.asarray(scores)
        if len(boxes)!=len(classes) or len(boxes)!=len(scores):
            raise ValueError('[BackgroundFilter] 框、类别和分数长度不同')
        row = self.cutoff(image_shape[1],image_shape[0],pitch_deg)
        keep = np.isfinite(boxes).all(axis=1) & (boxes[:,2]>boxes[:,0]) & (boxes[:,3]>boxes[:,1])
        if row is not None:
            keep &= boxes[:,3]>=row
        self.last = {'removed':int(len(boxes)-np.count_nonzero(keep)),'cutoff_y':row,'pitch_deg':float(pitch_deg) if pitch_deg is not None and math.isfinite(float(pitch_deg)) else None}
        return boxes[keep],classes[keep],scores[keep]
