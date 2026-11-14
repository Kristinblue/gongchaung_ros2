"""
目标稳定器。第二次积分赛搬过来的
对于大多数每一个识别到的物体，我们都做一点滤波。

如果检测框贴在边缘，就意味着可能可能是视野原因导致不见的，就不做了
否则，如果某个物体突然消失了，就保留它上一次的位置。连续丢失超过一定帧数（yaml里面），就认为它真的消失了。
"""

import math


class TargetStablizer:
    """过滤目标跳变，并在短暂丢失时保留上一次目标。"""

    def __init__(self, max_dist=50, max_lost_frames=10, center_indexes=(4, 5)):
        """初始化目标稳定器。

        Args:
            max_dist: 两帧之间允许的最大像素跳变。
            max_lost_frames: 允许丢失的最大帧数。
            center_indexes: 目标是 tuple 时，中心点 x、y 所在的位置。
        """

        self.max_dist = max_dist
        self.max_lost_frames = max_lost_frames
        self.center_indexes = center_indexes
        self.last_target = None
        self.lost_frame_count = 0

    def update(self, current_target):
        """输入当前帧目标，返回稳定后的目标。

        Args:
            current_target: 当前帧检测到的目标，支持带 center 属性的对象或 tuple。

        Returns:
            稳定后的目标；目标丢失太久时返回 None。
        """

        if current_target is not None:
            curr_c = self.get_center(current_target)
            if curr_c is None:
                return self._handle_lost()

            if self.last_target is None:
                self._record_valid(current_target)
                return current_target

            last_c = self.get_center(self.last_target)
            if last_c is None:
                self._record_valid(current_target)
                return current_target

            dist = math.sqrt((curr_c[0] - last_c[0]) ** 2 + (curr_c[1] - last_c[1]) ** 2)
            if dist <= self.max_dist:
                self._record_valid(current_target)
                return current_target

            return self._handle_lost()

        return self._handle_lost()

    def get_center(self, target):
        """获取目标中心点。"""

        center = getattr(target, "center", None)
        if center is not None:
            return center

        if hasattr(target, "x") and hasattr(target, "y") and hasattr(target, "w") and hasattr(target, "h"):
            return target.x + target.w // 2, target.y + target.h // 2

        if isinstance(target, (tuple, list)) and len(target) > max(self.center_indexes):
            return target[self.center_indexes[0]], target[self.center_indexes[1]]

        return None

    def _record_valid(self, target):
        """记录合法目标。"""

        self.last_target = target
        if hasattr(target, "approx") and hasattr(target.approx, "copy"):
            self.last_target.approx = target.approx.copy()
        self.lost_frame_count = 0

    def _handle_lost(self):
        """处理丢失目标。"""

        if self.last_target is not None:
            self.lost_frame_count += 1
            if self.lost_frame_count <= self.max_lost_frames:
                return self.last_target

            self.last_target = None
            self.lost_frame_count = 0
            return None

        return None

    def reset(self):
        """重置稳定器。"""

        self.last_target = None
        self.lost_frame_count = 0
