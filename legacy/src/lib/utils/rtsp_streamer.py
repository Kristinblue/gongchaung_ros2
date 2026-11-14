"""GStreamer RTSP 视频推流模块。

主程序通过 :meth:`RtspStreamer.push` 提交最新的 BGR NumPy 数组，后台线程负责
H.264 编码和 RTSP 发送。模块不会打开摄像头，避免与主循环重复采集。
"""

import threading
import numpy as np

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import GLib, Gst, GstRtspServer


class _CameraRtspFactory(GstRtspServer.RTSPMediaFactory):
    """根据 RTSP 客户端连接创建 GStreamer 视频管道。"""

    def __init__(self, streamer):
        """初始化媒体工厂。

        Args:
            streamer: RtspStreamer，提供视频参数和最新图像帧。
        """
        super().__init__()
        self._streamer = streamer
        self.set_shared(True)
        self.set_launch(
            f"( appsrc name=video_src is-live=true block=false format=time max-buffers=2 "
            f"caps=video/x-raw,format=BGR,width={streamer.width},height={streamer.height},framerate={streamer.fps}/1 "
            f"! queue leaky=downstream max-size-buffers=2 "
            f"! videoconvert "
            f"! x264enc tune=zerolatency speed-preset=ultrafast bitrate={streamer.bitrate} key-int-max={streamer.fps} bframes=0 "
            f"! h264parse "
            f"! rtph264pay name=pay0 pt=96 config-interval=1 )"
        )
        self.connect("media-configure", self._on_media_configure)

    def _on_media_configure(self, _factory, media):
        """保存客户端连接后创建的 appsrc 元素。"""
        element = media.get_element()
        appsrc = element.get_by_name("video_src")
        self._streamer._set_appsrc(appsrc)
        media.connect("unprepared", self._on_media_unprepared)
        print("[RtspStreamer] RTSP 客户端已连接")

    def _on_media_unprepared(self, _media):
        """客户端全部断开后清除失效的 appsrc。"""
        self._streamer._set_appsrc(None)
        print("[RtspStreamer] RTSP 客户端已断开")


class RtspStreamer:
    """在后台线程中发布 RTSP 视频流。

    ``RTSP`` 是 Real Time Streaming Protocol（实时流传输协议）。主循环
    只调用 :meth:`push` 更新最新帧，编码速度不会反向阻塞主循环。
    """

    def __init__(self, width, height, fps=60, bitrate=4000, port=8554, path="cam"):
        """初始化 RTSP 推流器。

        Args:
            width: int，视频宽度，单位为像素。
            height: int，视频高度，单位为像素。
            fps: int，目标推流帧率。
            bitrate: int，H.264 目标码率，单位为 kbit/s。
            port: int，RTSP 服务监听端口。
            path: str，RTSP 地址中的流路径。
        """
        self.width = width
        self.height = height
        self.fps = fps
        self.bitrate = bitrate
        self.port = port
        self.path = path.strip("/")
        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._latest_sequence = 0
        self._pushed_sequence = -1
        self._frame_number = 0
        self._appsrc = None
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._startup_error = None
        self._running = False

    def start(self):
        """启动后台 RTSP 服务。

        Raises:
            RuntimeError: RTSP 服务在 5 秒内未启动，或监听端口失败。
        """
        if self._running:
            return

        self._ready.clear()
        self._startup_error = None
        self._running = True
        self._thread = threading.Thread(target=self._run, name="rtsp-streamer", daemon=True)
        self._thread.start()

        if not self._ready.wait(timeout=5.0):
            self._running = False
            raise RuntimeError("RTSP 服务启动超时")
        if self._startup_error is not None:
            self._running = False
            raise RuntimeError("RTSP 服务启动失败") from self._startup_error

    def push(self, image):
        """更新等待推流的最新图像。

        此方法不进行编码，只保存 ``numpy.ndarray`` 的引用并立即返回。下一帧
        到来时会覆盖旧引用，因此编码积压时不会不断增加内存占用。

        Args:
            image: numpy.ndarray，uint8 BGR 图像；提交后不要继续修改像素。

        Raises:
            ValueError: 图像尺寸与 RTSP 初始化尺寸不同。
        """
        if not self._running:
            return

        if not isinstance(image, np.ndarray) or image.dtype != np.uint8:
            raise TypeError("[RtspStreamer] image 必须是 uint8 NumPy 数组")
        frame = image
        expected_shape = (self.height, self.width, 3)
        if frame.shape != expected_shape:
            raise ValueError(f"RTSP 图像尺寸应为 {expected_shape}，实际为 {frame.shape}")

        with self._frame_lock:
            self._latest_frame = frame
            self._latest_sequence += 1

    def close(self):
        """停止 RTSP 服务并等待后台线程退出。"""
        if not self._running:
            return

        self._running = False
        if self._loop is not None:
            self._loop.quit()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._loop = None
        self._set_appsrc(None)
        print("[RtspStreamer] RTSP 服务已停止")

    def _run(self):
        """在后台线程运行 GStreamer GLib 事件循环。"""
        try:
            Gst.init(None)
            server = GstRtspServer.RTSPServer()
            server.set_service(str(self.port))
            factory = _CameraRtspFactory(self)
            server.get_mount_points().add_factory("/" + self.path, factory)
            source_id = server.attach(None)
            if source_id == 0:
                raise RuntimeError(f"无法监听 RTSP 端口 {self.port}")

            self._loop = GLib.MainLoop()
            interval_ms = max(1, round(1000 / self.fps))
            GLib.timeout_add(interval_ms, self._push_latest_frame)
            self._ready.set()
            print(f"[RtspStreamer] RTSP 服务已启动: rtsp://<香橙派IP>:{self.port}/{self.path}")
            self._loop.run()
        except Exception as exc:
            self._startup_error = exc
            self._ready.set()
            print(f"[RtspStreamer] RTSP 服务异常: {exc}")
        finally:
            self._running = False

    def _set_appsrc(self, appsrc):
        """更新当前 RTSP 媒体管道的 appsrc。"""
        self._appsrc = appsrc
        self._pushed_sequence = -1
        self._frame_number = 0

    def _push_latest_frame(self):
        """把最新图像写入 appsrc，由 GLib 定时器周期调用。"""
        if not self._running:
            return False
        if self._appsrc is None:
            return True

        with self._frame_lock:
            if self._latest_frame is None or self._latest_sequence == self._pushed_sequence:
                return True
            frame = self._latest_frame
            sequence = self._latest_sequence

        frame_bytes = frame.tobytes(order="C")
        buffer = Gst.Buffer.new_allocate(None, len(frame_bytes), None)
        buffer.fill(0, frame_bytes)
        duration = Gst.util_uint64_scale_int(1, Gst.SECOND, self.fps)
        buffer.pts = self._frame_number * duration
        buffer.dts = buffer.pts
        buffer.duration = duration

        result = self._appsrc.emit("push-buffer", buffer)
        if result == Gst.FlowReturn.OK:
            self._pushed_sequence = sequence
            self._frame_number += 1
        elif result != Gst.FlowReturn.FLUSHING:
            print(f"[RtspStreamer] 推帧失败: {result.value_nick}")
        return True
