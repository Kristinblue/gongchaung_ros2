"""
rga
----------
Rockchip RGA 图像处理封装。

这个模块只负责处理已经存在于 NumPy 内存中的图像，不负责打开摄像头。
因此它既可以和 USB 摄像头一起使用，也可以单独测试。

当前实现使用 librga 的 im2d C 接口完成 BGR 图像缩放：

    NumPy BGR -> importbuffer_virtualaddr -> RGA imresize -> NumPy BGR

说明：
    1. 这不是 MIPI 摄像头模块。
    2. 这不会处理 MJPG/JPEG 解码。
    3. RGA 动态库和内核驱动必须来自相互匹配的系统版本。
"""

from __future__ import annotations

import ctypes
import os
from typing import Final

import numpy as np


# Rockchip rga.h 中的像素格式常量。
RK_FORMAT_RGB_888: Final[int] = 0x2
RK_FORMAT_BGR_888: Final[int] = 0x7

# im2d.h 中的默认插值模式和同步模式。
IM_INTERP_DEFAULT: Final[int] = 0
IM_SYNC: Final[int] = 1

# im2d 的成功返回值：IM_STATUS_SUCCESS=1，IM_STATUS_NOERROR=2。
_IM_STATUS_SUCCESS = {1, 2}


class RGAError(RuntimeError):
    """RGA 初始化或图像处理失败时抛出的异常。"""


class _ImHandleParam(ctypes.Structure):
    """im_handle_param_t：描述外部图像缓冲区。"""

    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("format", ctypes.c_uint32),
    ]


class _ImColorKeyRange(ctypes.Structure):
    """im_colorkey_range：im2d 结构体中的颜色键范围。"""

    _fields_ = [
        ("max", ctypes.c_int),
        ("min", ctypes.c_int),
    ]


class _ImNN(ctypes.Structure):
    """im_nn_t：im2d 结构体中的量化参数。"""

    _fields_ = [
        ("scale_r", ctypes.c_int),
        ("scale_g", ctypes.c_int),
        ("scale_b", ctypes.c_int),
        ("offset_r", ctypes.c_int),
        ("offset_g", ctypes.c_int),
        ("offset_b", ctypes.c_int),
    ]


class _RgaBuffer(ctypes.Structure):
    """rga_buffer_t：im2d 图像描述结构体。

    字段顺序来自 Rockchip librga 的 im2d_type.h。
    这里使用 importbuffer 返回的 handle，因此 vir_addr/fd 等字段
    由 wrapbuffer_handle_t 负责填写。
    """

    _fields_ = [
        ("vir_addr", ctypes.c_void_p),
        ("phy_addr", ctypes.c_void_p),
        ("fd", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("wstride", ctypes.c_int),
        ("hstride", ctypes.c_int),
        ("format", ctypes.c_int),
        ("color_space_mode", ctypes.c_int),
        ("global_alpha", ctypes.c_int),
        ("rd_mode", ctypes.c_int),
        ("color", ctypes.c_int),
        ("colorkey_range", _ImColorKeyRange),
        ("nn", _ImNN),
        ("rop_code", ctypes.c_int),
        ("handle", ctypes.c_uint32),
    ]


class RGA:
    """Rockchip RGA 图像处理器。

    Args:
        library: librga 动态库名称。默认使用系统动态链接器可找到的
            ``librga.so.2``，不依赖当前工作目录。

    Raises:
        RGAError: /dev/rga 不存在、动态库加载失败、接口缺失或初始化失败。

    Example:
        >>> rga = RGA()
        >>> output = rga.resize_bgr(input_bgr, 640, 480)
        >>> rga.close()
    """

    def __init__(self, library: str = "librga.so.2"):
        self._lib = None
        self._closed = False

        if not os.path.exists("/dev/rga"):
            raise RGAError("[RGA] /dev/rga 不存在")

        try:
            self._lib = ctypes.CDLL(library)
        except OSError as exc:
            raise RGAError(f"[RGA] 无法加载 {library}: {exc}") from exc

        self._configure_functions()
        self._init_rga()
        print(f"[RGA] 已初始化: {library}")

    def _configure_functions(self) -> None:
        """配置 librga C 函数的参数和返回值类型。"""
        try:
            init = self._lib.c_RkRgaInit
            deinit = self._lib.c_RkRgaDeInit
            import_buffer = self._lib.importbuffer_virtualaddr
            release_buffer = self._lib.releasebuffer_handle
            wrap_buffer = self._lib.wrapbuffer_handle_t
            resize = self._lib.imresize_t
        except AttributeError as exc:
            raise RGAError(
                "[RGA] librga 缺少 im2d 接口；当前库版本可能不是兼容版本"
            ) from exc

        init.argtypes = []
        init.restype = ctypes.c_int
        deinit.argtypes = []
        deinit.restype = None

        # C 接口版本：importbuffer_virtualaddr(void*, im_handle_param_t*).
        import_buffer.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ImHandleParam),
        ]
        import_buffer.restype = ctypes.c_uint32

        release_buffer.argtypes = [ctypes.c_uint32]
        release_buffer.restype = ctypes.c_int

        # rga_buffer_t 按值返回，im2d 的 imresize_t 也按值接收结构体。
        wrap_buffer.argtypes = [
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        wrap_buffer.restype = _RgaBuffer

        resize.argtypes = [
            _RgaBuffer,
            _RgaBuffer,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_int,
            ctypes.c_int,
        ]
        resize.restype = ctypes.c_int

        self._init = init
        self._deinit = deinit
        self._import_buffer = import_buffer
        self._release_buffer = release_buffer
        self._wrap_buffer = wrap_buffer
        self._resize = resize

    def _init_rga(self) -> None:
        """调用 librga 初始化函数。"""
        ret = self._init()
        if ret != 0:
            raise RGAError(f"[RGA] c_RkRgaInit 失败，返回码: {ret}")

    @staticmethod
    def _validate_bgr(image: np.ndarray) -> np.ndarray:
        """检查并整理 BGR NumPy 图像。

        Args:
            image: shape=(height, width, 3)、dtype=uint8 的 BGR 数组。

        Returns:
            numpy.ndarray: 连续存储的 BGR 数组。必要时会创建一个连续副本。

        Raises:
            TypeError: image 不是 NumPy 数组或 dtype 不正确。
            ValueError: image 不是三通道图像或尺寸无效。
        """
        if not isinstance(image, np.ndarray):
            raise TypeError("image 必须是 numpy.ndarray")
        if image.dtype != np.uint8:
            raise TypeError("image.dtype 必须是 numpy.uint8")
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("image 必须是 shape=(height, width, 3) 的 BGR 图像")
        if image.shape[0] <= 0 or image.shape[1] <= 0:
            raise ValueError("image 的宽高必须大于 0")
        return np.ascontiguousarray(image)

    def resize_bgr(
        self,
        image: np.ndarray,
        width: int,
        height: int,
    ) -> np.ndarray:
        """使用 RGA 缩放 BGR 图像。

        Args:
            image: BGR 格式的 NumPy 数组，dtype 必须为 uint8。
            width: 输出宽度，单位为像素。
            height: 输出高度，单位为像素。

        Returns:
            numpy.ndarray: RGA 输出的 BGR 数组，shape=(height, width, 3)。

        Raises:
            ValueError: 输出尺寸不合法。
            RGAError: 缓冲区导入、RGA 缩放或释放过程中失败。
        """
        if not isinstance(width, int) or not isinstance(height, int):
            raise TypeError("width 和 height 必须是 int")
        if width <= 0 or height <= 0:
            raise ValueError("width 和 height 必须大于 0")

        source = self._validate_bgr(image)
        source_height, source_width = source.shape[:2]
        target = np.empty((height, width, 3), dtype=np.uint8)

        source_param = _ImHandleParam(
            source_width,
            source_height,
            RK_FORMAT_BGR_888,
        )
        target_param = _ImHandleParam(width, height, RK_FORMAT_BGR_888)

        source_handle = self._import_buffer(
            source.ctypes.data_as(ctypes.c_void_p),
            ctypes.byref(source_param),
        )
        target_handle = self._import_buffer(
            target.ctypes.data_as(ctypes.c_void_p),
            ctypes.byref(target_param),
        )

        if not source_handle or not target_handle:
            if source_handle:
                self._release_buffer(source_handle)
            if target_handle:
                self._release_buffer(target_handle)
            raise RGAError("[RGA] importbuffer_virtualaddr 失败")

        try:
            source_buffer = self._wrap_buffer(
                source_handle,
                source_width,
                source_height,
                source_width,
                source_height,
                RK_FORMAT_BGR_888,
            )
            target_buffer = self._wrap_buffer(
                target_handle,
                width,
                height,
                width,
                height,
                RK_FORMAT_BGR_888,
            )

            ret = self._resize(
                source_buffer,
                target_buffer,
                0.0,
                0.0,
                IM_INTERP_DEFAULT,
                IM_SYNC,
            )
            if ret not in _IM_STATUS_SUCCESS:
                raise RGAError(f"[RGA] imresize_t 失败，返回码: {ret}")
        finally:
            source_ret = self._release_buffer(source_handle)
            target_ret = self._release_buffer(target_handle)
            if source_ret < 0 or target_ret < 0:
                raise RGAError(
                    f"[RGA] 释放缓冲区失败: source={source_ret}, target={target_ret}"
                )

        return target

    def close(self) -> None:
        """释放 RGA 进程级资源。"""
        if not self._closed:
            self._deinit()
            self._closed = True
            print("[RGA] 已释放")

    def __enter__(self) -> "RGA":
        """支持 ``with RGA() as rga`` 语法。"""
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """退出 with 代码块时释放 RGA。"""
        self.close()

    def __del__(self):
        """对象被回收时尽力释放资源。"""
        try:
            self.close()
        except Exception:
            # 解释器退出阶段依赖项可能已经被销毁，不能再抛异常。
            pass

