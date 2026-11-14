"""
自己封装的数据集图像采集类

核心功能：一键开启采集，按时间戳自动建文件夹，按设定间隔抽帧保存图像
"""

import os
import time
import cv2
import numpy as np


class ImgsRecorder:
    """按间隔保存 OpenCV 图像的采集器，JPEG 编码和写入同步执行。"""

    def __init__(
        self,
        cap,
        path: str = "/home/orangepi/my_data",
        frame_name: str = "frame",
        enable: bool = True,
        interval: int = 10,
    ) -> None:
        """
        初始化图片采集器
        Args:
            cap: 原生 OpenCV 摄像头，用于读取实际宽高
            path: 数据集保存的【根目录】（每次录制会自动在这下面新建时间戳文件夹）
            frame_name: 保存文件名前缀，默认为 frame
            enable: 是否启用录制功能，默认为True
            interval: 抽帧间隔，默认为10
        """
        self.running = True
        self.base_path = path
        self.enable = enable
        self.frame_name = frame_name
        self.interval = interval
        if interval <= 0:
            raise ValueError("[ImgsRecorder] interval 必须大于 0")

        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # 记录本次拍摄的状态
        self.session_dir = None
        self.frame_count = 0  # 记录经历了多少帧
        self.saved_count = 0  # 记录实际保存了多少张

    def _set_session(self) -> None:
        """
        内部方法：初始化本次拍摄的专属文件夹
        """
        if self.enable:
            try:
                # 获取当前机器的时间戳
                timestamp = time.time_ns()

                # 纳秒时间戳避免同一秒内停止再启动时复用之前的目录。
                self.session_dir = os.path.abspath(
                    os.path.join(self.base_path, f"record_{timestamp}")
                )

                # 如果这个文件夹不存在，就自动新建它！
                if not os.path.exists(self.session_dir):
                    os.makedirs(self.session_dir)
                    print(
                        "[ImgsRecorder] 自动创建了数据集文件夹: "
                        f"{self.session_dir}"
                    )

                print(
                    f"[ImgsRecorder] 已初始化. 分辨率: "
                    f"{self.width}x{self.height}, 抽帧间隔: {self.interval}"
                )
            except Exception as error:
                print(f"[ImgsRecorder] 初始化失败: {error}")
                self.enable = False
                self.session_dir = None

    @staticmethod
    def _save_image(img, file_path: str) -> None:
        """使用 OpenCV 保存一张原始 BGR 图像。

        Args:
            img: uint8 BGR NumPy 数组，不包含 UI 的录制提示标记。
            file_path: JPEG 文件完整路径。

        Raises:
            TypeError: 输入不是 uint8 NumPy 数组。
            ValueError: 图像不是三通道 BGR。
            IOError: JPEG 写入失败。
        """
        if not isinstance(img, np.ndarray) or img.dtype != np.uint8:
            raise TypeError("[ImgsRecorder] img 必须是 uint8 NumPy 数组")
        if img.ndim != 3 or img.shape[2] != 3:
            raise ValueError("[ImgsRecorder] img 必须是三通道 BGR 图像")
        if not cv2.imwrite(file_path, img, [cv2.IMWRITE_JPEG_QUALITY, 95]):
            raise IOError(f"[ImgsRecorder] 图片保存失败: {file_path}")

    def record_frames(self, img) -> None:
        """
        执行抽帧保存（在主循环中持续调用）
        """
        if self.enable:
            # 1. 检查是否没有 session 文件夹（代表刚按下 START）
            if not self.session_dir:
                self._set_session()
                print("[ImgsRecorder] 开始录制（抽帧模式）。")

            # 2. 如果文件夹建立成功，开始处理传入的帧
            if self.session_dir is not None:
                self.frame_count += 1

                # 3. 抽帧存储
                if self.frame_count >= self.interval:
                    # 拼装文件名。使用 {:04d} 补齐 4 位数字，如 frame_0012.jpg，方便电脑排序查看
                    file_path = os.path.join(
                        self.session_dir,
                        f"{self.frame_name}_{self.saved_count:04d}.jpg",
                    )

                    # 调用 API 真正保存图片！
                    self._save_image(img, file_path)
                    if not os.path.isfile(file_path):
                        raise IOError(f"图片保存失败，文件不存在: {file_path}")

                    self.saved_count += 1
                    self.frame_count = 0

    def stop_recording(self) -> None:
        """
        停止录制，并重置参数等待下一次触发
        """
        if self.enable and self.session_dir:
            print(
                "[ImgsRecorder] 停止录制。"
                f"本次共抽帧保存了 {self.saved_count} 张高清图片。"
            )

            # 重置会话变量，确保下次点击 START 会新建一个时间戳文件夹
            self.session_dir = None
            self.frame_count = 0
            self.saved_count = 0
