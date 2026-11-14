"""
mipi_camera.py
[deprecated] 那个ov13855不好用，拖影严重，线长也不好控制，就用usb吧
MIPI CSI 摄像头模块 — GStreamer + RGA，输出 BGR NumPy 数组

基于 GStreamer 管道 + RGA 硬件加速（ctypes 直接调用 librga），
本模块保留 MIPI 摄像头的独立接口；USB 采集线程使用 utils.usb_camera.Camera。

架构：
    GStreamer 管道 → NV12 原始数据 → ctypes 调 c_RkRgaBlit → BGR numpy 数组
    ─────────────────────────────────────────────────────────────────
    不依赖 rgaconvert 插件，直接通过 ctypes 调 librga.so。
    只要 /dev/rga 和 librga.so 存在就能用，不挑 GStreamer 版本。

启动时自动探测 RGA，不可用时降级为 CPU 转换（videoconvert）。

作者: Kristin
日期: 2026.7.17
"""

import os
import subprocess
import threading
import ctypes
import numpy as np


# ========== RGA ctypes 封装 ==========
# 直接从 librga.so 调用 C 函数，绕过 GStreamer 插件版本问题

# ---- 格式常量（来自 rga.h）----
# NV12 = YCbCr 4:2:0 半平面格式：plane0 存 Y，plane1 存交替的 CbCr
RK_FORMAT_RGBA_8888      = 0x0
RK_FORMAT_RGBX_8888      = 0x1
RK_FORMAT_RGB_888        = 0x2
RK_FORMAT_BGRA_8888      = 0x3
RK_FORMAT_RGB_565        = 0x4
RK_FORMAT_RGBA_5551      = 0x5
RK_FORMAT_RGBA_4444      = 0x6
RK_FORMAT_BGR_888        = 0x7
RK_FORMAT_YCbCr_422_SP   = 0x8
RK_FORMAT_YCbCr_422_P    = 0x9
RK_FORMAT_YCbCr_420_SP   = 0xa   # ← 这就是 NV12
RK_FORMAT_YCbCr_420_P    = 0xb
RK_FORMAT_YCrCb_422_SP   = 0xc
RK_FORMAT_YCrCb_422_P    = 0xd
RK_FORMAT_YCrCb_420_SP   = 0xe   # ← NV21
RK_FORMAT_YCrCb_420_P    = 0xf

# 颜色空间模式
YUV2RGB_MODE_BT601 = 0     # BT.601 MPEG，摄像头默认用这个


class _RgaRect(ctypes.Structure):
    """rga_rect_t 结构体（来自 drmrga.h）"""
    _fields_ = [
        ("xoffset",  ctypes.c_int),
        ("yoffset",  ctypes.c_int),
        ("width",    ctypes.c_int),
        ("height",   ctypes.c_int),
        ("wstride",  ctypes.c_int),
        ("hstride",  ctypes.c_int),
        ("format",   ctypes.c_int),
        ("size",     ctypes.c_int),
    ]


class _RgaInfo(ctypes.Structure):
    """rga_info_t 结构体（来自 drmrga.h）

    我们只用到 fd、virAddr、format、rect、color_space_mode 这几个字段。
    其余字段按零值填充即可。
    """
    _fields_ = [
        ("fd",               ctypes.c_int),
        ("virAddr",          ctypes.c_void_p),
        ("phyAddr",          ctypes.c_void_p),
        ("hnd",              ctypes.c_uint),
        ("format",           ctypes.c_int),
        ("rect",             _RgaRect),
        ("blend",            ctypes.c_uint),
        ("bufferSize",       ctypes.c_int),
        ("rotation",         ctypes.c_int),
        ("color",            ctypes.c_int),
        ("testLog",          ctypes.c_int),
        ("mmuFlag",          ctypes.c_int),
        ("colorkey_en",      ctypes.c_int),
        ("colorkey_mode",    ctypes.c_int),
        ("colorkey_max",     ctypes.c_int),
        ("colorkey_min",     ctypes.c_int),
        ("scale_mode",       ctypes.c_int),
        ("color_space_mode", ctypes.c_int),
        ("sync_mode",        ctypes.c_int),
        # nn, dither, rop_code 等我们不需要，但 ctypes 需要完整大小匹配
        ("nn",               ctypes.c_byte * 24),   # rga_nn_t 占位
        ("dither",           ctypes.c_byte * 24),   # rga_dither_t 占位
        ("rop_code",         ctypes.c_int),
        ("rd_mode",          ctypes.c_int),
        ("is_10b_compact",   ctypes.c_ushort),
        ("is_10b_endian",    ctypes.c_ushort),
        ("in_fence_fd",      ctypes.c_int),
        ("out_fence_fd",     ctypes.c_int),
        ("core",             ctypes.c_int),
        ("priority",         ctypes.c_int),
        ("enable",           ctypes.c_ushort),
        ("handle",           ctypes.c_int),
        # mosaic_info, osd_info, pre_intr 占位
        ("_pad_mosaic",      ctypes.c_byte * 8),
        ("_pad_osd",         ctypes.c_byte * 96),
        ("_pad_pre_intr",    ctypes.c_byte * 16),
        ("mpi_mode",         ctypes.c_int),
        ("ctx_id",           ctypes.c_int),
        ("reserve",          ctypes.c_byte * 402),
    ]


def _load_librga():
    """加载 librga.so 并返回核心函数。

    Returns:
        dict: 包含 'init', 'blit', 'deinit' 三个函数指针，
              加载失败返回 None。
    """
    try:
        librga = ctypes.CDLL("lib64/librga.so.2")
    except OSError:
        try:
            librga = ctypes.CDLL("lib/aarch64-linux-gnu/librga.so.2")
        except OSError:
            return None

    # 初始化接口签名：c_RkRgaInit: int(void)
    c_init = librga.c_RkRgaInit
    c_init.restype = ctypes.c_int

    # 图像转换接口签名：c_RkRgaBlit: int(rga_info_t *src, rga_info_t *dst, rga_info_t *src1)
    c_blit = librga.c_RkRgaBlit
    c_blit.argtypes = [ctypes.POINTER(_RgaInfo), ctypes.POINTER(_RgaInfo), ctypes.POINTER(_RgaInfo)]
    c_blit.restype = ctypes.c_int

    # 释放接口签名：c_RkRgaDeInit: void(void)
    c_deinit = librga.c_RkRgaDeInit
    c_deinit.restype = None

    return {"init": c_init, "blit": c_blit, "deinit": c_deinit}


def _nv12_to_bgr_rga(nv12_data, width, height, rga_funcs):
    """使用 RGA 硬件将 NV12 数据转换为 BGR。

    原理：
        NV12 是 YCbCr 4:2:0 半平面格式：
        - plane0: Y 分量，width × height 字节
        - plane1: UV 分量交替存储，width × height / 2 字节（2×2 子采样）
        总大小 = width × height × 3 / 2

        c_RkRgaBlit 一次调用完成 NV12 → BGR 转换，RGA 硬件 DMA 操作，减少 CPU 颜色转换工作。

    Args:
        nv12_data: bytes, NV12 原始数据。
        width: int, 图像宽度。
        height: int, 图像高度。
        rga_funcs: dict, _load_librga() 返回的函数字典。

    Returns:
        numpy.ndarray or None: BGR 格式 (H, W, 3)，失败返回 None。
    """
    bgr_size = width * height * 3
    bgr_buf = ctypes.create_string_buffer(bgr_size)

    # ---- 构造 src info（NV12 输入）----
    src = _RgaInfo()
    src.fd = -1                            # -1 表示使用 virAddr
    src.virAddr = ctypes.cast(nv12_data, ctypes.c_void_p)  # 注意：需要 bytes 对象保持存活！
    src.format = RK_FORMAT_YCbCr_420_SP << 8  # NV12
    src.rect.xoffset = 0
    src.rect.yoffset = 0
    src.rect.width = width
    src.rect.height = height
    src.rect.wstride = width
    src.rect.hstride = height
    src.rect.format = RK_FORMAT_YCbCr_420_SP << 8
    src.color_space_mode = YUV2RGB_MODE_BT601

    # ---- 构造 dst info（BGR 输出）----
    dst = _RgaInfo()
    dst.fd = -1
    dst.virAddr = ctypes.cast(bgr_buf, ctypes.c_void_p)
    dst.format = RK_FORMAT_BGR_888 << 8
    dst.rect.xoffset = 0
    dst.rect.yoffset = 0
    dst.rect.width = width
    dst.rect.height = height
    dst.rect.wstride = width
    dst.rect.hstride = height
    dst.rect.format = RK_FORMAT_BGR_888 << 8
    dst.color_space_mode = YUV2RGB_MODE_BT601

    # ---- 调用 RGA 转换 ----
    ret = rga_funcs["blit"](
        ctypes.byref(src),
        ctypes.byref(dst),
        ctypes.POINTER(_RgaInfo)()  # src1 传 NULL
    )

    if ret != 0:
        return None

    # bytes → numpy BGR 数组
    return np.frombuffer(bgr_buf, dtype=np.uint8).reshape((height, width, 3))


class Camera:
    """MIPI CSI 摄像头，基于 GStreamer 管道 + RGA 硬件加速。

    自动降级机制：
        启动时自动探测 /dev/rga 和 librga.so。
        如果可用，GStreamer 输出 NV12 → RGA 硬件转 BGR，减少 CPU 颜色转换工作。
        如果不可用，GStreamer 用 videoconvert 做 CPU 转换。

    Attributes:
        _width: int, 摄像头画面宽度。
        _height: int, 摄像头画面高度。
        _device: str, V4L2 设备路径（如 /dev/video11）。
        _frame_bytes: int, 一帧数据的字节数（NV12 或 BGR，取决于模式）。
        _use_rga: bool, 是否使用 RGA 硬件加速。
        _gs_process: subprocess.Popen, GStreamer 子进程对象。
        _rga_funcs: dict or None, RGA 函数指针（仅 _use_rga=True 时）。
    """

    def __init__(self, width=1280, height=720, device="/dev/video11"):
        """初始化 MIPI CSI 摄像头。

        Args:
            width: int, 期望的图像宽度（像素）。
            height: int, 期望的图像高度（像素）。
            device: str, V4L2 设备路径。
                    Orange Pi 5 Plus 的 4 个 CSI 接口对应：
                    /dev/video11 → CSI0 (4-lane)
                    /dev/video21 → CSI1 (2-lane)
                    /dev/video22 → CSI2 (2-lane)
                    /dev/video23 → CSI3 (2-lane)
        """
        self._width = width
        self._height = height
        self._device = device
        self._gs_process = None
        self._running = False

        # ====== 0. 线程 + 帧缓存（非阻塞读取） ======
        # 帧缓存：子线程直接覆盖，主线程读取最新缓存帧
        self._current_img = None
        self._reader_thread = None

        # ====== 1. 探测 RGA 硬件加速 ======
        # 策略：
        #   (1) 检查 /dev/rga 设备节点是否存在
        #   (2) 加载 librga.so 并获取函数指针
        #   两个条件都满足才启用 RGA
        self._use_rga = False
        self._rga_funcs = None

        if os.path.exists("/dev/rga"):
            self._rga_funcs = _load_librga()
            if self._rga_funcs is not None:
                ret = self._rga_funcs["init"]()
                if ret == 0:
                    self._use_rga = True
                    print("[Camera] ✅ RGA 硬件加速已启用 — NV12→BGR 由 RGA 引擎完成，减少 CPU 颜色转换工作")
                else:
                    print(f"[Camera] ⚠️  RGA 初始化失败（返回码 {ret}），降级为 CPU 转换")
                    self._rga_funcs = None
            else:
                print("[Camera] ⚠️  无法加载 librga.so，降级为 CPU 转换")
        else:
            print("[Camera] ⚠️  /dev/rga 不存在，降级为 CPU 转换")

        # ====== 2. 构建 GStreamer 管道 ======
        # RGA 模式：v4l2src → NV12 → stdout（原始 NV12 数据，Python 侧用 RGA 转换）
        # CPU 模式：v4l2src → NV12 → videoconvert → BGR → stdout
        if self._use_rga:
            # RGA 模式：管道只输出 NV12，转换在 Python 侧完成
            # NV12 大小 = width × height × 3 / 2
            self._frame_bytes = width * height * 3 // 2
            converter = "identity"  # identity 什么都不做，数据原样通过
            out_format = "NV12"
            print("[Camera]   模式: GStreamer 输出 NV12 → Python RGA 转 BGR")
        else:
            # CPU 模式：GStreamer 内用 videoconvert 做转换
            self._frame_bytes = width * height * 3
            converter = "videoconvert"
            out_format = "BGR"
            print("[Camera]   模式: GStreamer videoconvert (CPU) 转 BGR")

        # 管道结构：
        # 管线流程：v4l2src → NV12 → identity/videoconvert → NV12/BGR → 标准输出
        gst_cmd = [
            "/usr/bin/gst-launch-1.0", "-q",
            "v4l2src", f"device={device}",
            "!", f"video/x-raw,format=NV12,width={width},height={height}",
            "!", converter,
            "!", f"video/x-raw,format={out_format}",
            "!", "fdsink", "fd=1", "sync=false"
        ]

        # ====== 3. 清理环境变量 ======
        clean_env = os.environ.copy()
        clean_env["PATH"] = ":".join(
            [p for p in clean_env.get("PATH", "").split(":") if "miniforge3" not in p]
        )
        if "LD_LIBRARY_PATH" in clean_env:
            del clean_env["LD_LIBRARY_PATH"]

        # ====== 4. 启动 GStreamer 子进程 ======
        print("[Camera] 🚀 正在启动 GStreamer 管道...")
        self._gs_process = subprocess.Popen(
            gst_cmd,
            stdout=subprocess.PIPE,
            bufsize=self._frame_bytes * 3,
            env=clean_env
        )
        print(f"[Camera] MIPI CSI 摄像头已就绪: {width}x{height}")

        # ====== 5. 启动后台读取线程 ======
        self._running = True
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True
        )
        self._reader_thread.start()
        print("[Camera] 后台读取线程已启动")

    # ========== 内部方法 ==========

    def _reader_loop(self):
        """后台线程：不断从 GStreamer 管道读帧，写入单槽。

        RGA 模式：读 NV12 原始数据 → ctypes 调 RGA 转 BGR → NumPy 数组
        CPU 模式：读 BGR 数据 → 直接得到 NumPy 数组

        帧缓存：直接覆盖 self._current_img，旧帧自动 GC。
        主线程 read() 返回缓存帧，首帧未到时返回 None。
        """
        while self._running:
            if self._gs_process is None or self._gs_process.stdout is None:
                break

            # 从 GStreamer 管道精确读取一帧原始数据
            raw_bytes = self._gs_process.stdout.read(self._frame_bytes)

            # 数据不完整 → 管道可能断开
            if not raw_bytes or len(raw_bytes) != self._frame_bytes:
                print("[Camera] ❌ 画面流中断")
                self._running = False
                break

            if self._use_rga:
                # RGA 模式：NV12 → BGR（硬件加速）
                frame_bgr = _nv12_to_bgr_rga(
                    raw_bytes, self._width, self._height, self._rga_funcs
                )
                if frame_bgr is None:
                    continue  # RGA 转换失败，跳过这帧
            else:
                # CPU 模式：BGR 数据直接 reshape
                frame_bgr = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(
                    (self._height, self._width, 3)
                )

            frame_bgr.setflags(write=False)
            img = frame_bgr

            # 直接覆盖，旧帧自动 GC，主线程首次读取仍可能拿到 None
            self._current_img = img

        print("[Camera] 后台读取线程退出")

    # ========== 基础公共接口（当前数据采集工具使用 usb_camera）==========

    def read(self, copy=True):
        """读取最新一帧，返回 NumPy 数组（非阻塞）。

        帧缓存机制：子线程不断覆盖 self._current_img，
        首帧未到或采集已停止时返回 None；多次读取可能得到同一帧。

        Args:
            copy: bool, 是否返回独立副本。默认 True。
                  True → 返回 self._current_img.copy()，可以安全地在上面绘图，
                          修改副本不会影响摄像头线程的内部帧。
                  False → 返回只读内部引用，省去本次取帧的复制，
                          省一次 2.7MB 内存拷贝。

        Returns:
            numpy.ndarray or None: 第一帧还没到时返回 None，否则返回最新帧。
        """
        frame = self._current_img
        if not self._running or frame is None:
            return None
        if copy:
            return frame.copy()
        return frame

    def close(self):
        """释放摄像头资源。

        1. 通知后台读取线程退出
        2. 终止 GStreamer 子进程，使管道 read() 返回
        3. 等待线程结束
        4. 释放 RGA 资源
        """
        self._running = False
        if self._gs_process is not None:
            if self._gs_process.poll() is None:
                self._gs_process.terminate()
            try:
                self._gs_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._gs_process.kill()
                self._gs_process.wait(timeout=2.0)

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2.0)
            if self._reader_thread.is_alive():
                raise RuntimeError("[Camera] MIPI 采集线程关闭超时")
            self._reader_thread = None
        if self._gs_process is not None:
            self._gs_process.stdout.close()
            self._gs_process = None
        self._current_img = None

        if self._rga_funcs is not None:
            self._rga_funcs["deinit"]()
            self._rga_funcs = None

        print("[Camera] MIPI CSI 摄像头已释放")

    def width(self):
        """
        Returns:
            int: 摄像头画面宽度（像素）。
        """
        return self._width

    def height(self):
        """
        Returns:
            int: 摄像头画面高度（像素）。
        """
        return self._height

    def is_opened(self):
        """摄像头是否正常打开。

        Returns:
            bool: True 表示摄像头已打开且 GStreamer 管道在运行。
        """
        return self._gs_process is not None and self._gs_process.poll() is None
