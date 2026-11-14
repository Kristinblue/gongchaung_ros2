"""步骤耗时调试器模块。"""

import time


def _ticks_ms() -> int:
    """获取毫秒时间戳。

    Returns:
        当前单调时钟的毫秒数。
    """

    return time.monotonic_ns() // 1_000_000


class TimeDebugger:
    """记录步骤耗时的简单计时器。"""

    def __init__(self) -> None:
        """初始化计时器。"""

        self.time_debug = False
        self.start_time = 0

    def reset(self) -> None:
        """把当前时刻设为下一次计时的起点。"""

        self.start_time = _ticks_ms()

    def get_time_logs(self, label: str) -> int:
        """打印从最近一次 reset 到现在的耗时。

        Args:
            label: 打印时显示的标签。

        Returns:
            距离最近一次 reset 的毫秒数。
        """

        now = _ticks_ms()
        elapsed = now - self.start_time

        if self.time_debug:
            print(f"{label}: {elapsed} ms")

        return elapsed
