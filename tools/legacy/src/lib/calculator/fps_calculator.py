""" 
lib/calculator/fps_calculator.py
计算帧率
"""
import time

def _ticks_ms() -> int:
    """获取单调递增的毫秒计数。

    Returns:
        从系统单调时钟起点经过的整数毫秒数。
    """
    return time.monotonic_ns() // 1_000_000

class FPSCalculator:
    def __init__(self, cycles=30, fps_debug=True):
        """
        Args:
            cycles: 每多少帧计算一次平均帧率
            fps_debug: 是否自动打印
        """
        self.cycles = cycles
        self.fps_debug = fps_debug
        #初始化变量
        self.frame_count = 0
        self.total_time = 0
        self.last_time = None
        self.avg_ms = 0.0
        self.fps = 0.0

    def fps_tick(self):
        """
        每帧调用一次，返回 (avg_ms, fps)
        """
        curt_time = _ticks_ms()
        #处理第一次
        if self.last_time is None:
            self.last_time = curt_time
            return self.avg_ms, self.fps

        elapsed = curt_time - self.last_time
        self.total_time += elapsed
        self.frame_count += 1
        self.last_time = curt_time

        if self.frame_count >= self.cycles:
            self.avg_ms = self.total_time / self.cycles
            self.fps = 1000.0 / self.avg_ms
            if self.fps_debug:
                print(f"平均循环时间: {self.avg_ms:.2f} ms, 帧率: {self.fps:.1f} fps")
            # 重置
            self.frame_count = 0
            self.total_time = 0

        return self.avg_ms, self.fps

    def get_fps(self):
        return self.fps

    def get_avg_ms(self):
        return self.avg_ms