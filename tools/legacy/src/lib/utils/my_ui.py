"""
my_ui.py
简单 UI 模块 — 封装 PyQt 界面

提供全屏显示画面、按钮、标签、滑块等控件，

作者: Kristin
日期: 2026.7.16
"""

import sys
import os
import numpy as np
from PyQt5.QtWidgets import (QApplication, QLabel, QWidget, QVBoxLayout,
                             QPushButton, QSlider, QShortcut)
from PyQt5.QtGui import QImage, QPixmap, QKeySequence
from PyQt5.QtCore import QTimer, Qt


# 消除 PyQt 在终端打印的无用调试信息
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.*=false"

# 按钮统一样式
BTN_STYLE = """
    QPushButton {
        background-color: #FFB6C1;   /* 浅粉色 (LightPink) */
        color: #333333;              /* 深灰色文字 */
        border-radius: 15px;         /* 圆角半径 = 按钮高度的一半 → 胶囊形状 */
        font-family: 'WenQuanYi Micro Hei', 'Arial', sans-serif;
        font-size: 28px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #FF69B4;   /* 亮粉色 (HotPink) */
    }
    QPushButton:pressed {
        background-color: #C71585;   /* 深粉色 (MediumVioletRed) */
    }
"""


class MyUI:
    """项目统一界面。

    一个全屏窗口同时承载：
    - 摄像头画面：show(img) 存入，QTimer 每 30ms 自动渲染
    - 交互控件：add_button / add_label / add_slider

    Attributes:
        _app: QApplication, PyQt 应用实例（全局唯一）。
        _window: QWidget, 全屏窗口。这是一个主窗口，其他控件都是他的儿子。然而，这个父亲也是Qwidget的儿砸！
        _layout: QVBoxLayout, 垂直布局管理器。
        _widgets: list, 已添加的控件列表。现在被我deprecate哩！暂时感觉不需要统一操作
        _video_label: QLabel, 用于显示摄像头画面的标签控件。
        _current_img: numpy.ndarray or None, 当前待显示的画面数据。
        _timer: QTimer, 帧刷新定时器（30ms ≈ 33 FPS）。
        _running: bool, 是否正在运行。
    """

    def __init__(self, fullscreen=True, title=""):
        """初始化界面。

        Args:
            fullscreen: bool, 是否全屏。默认 True。
                        False 时显示为普通窗口（方便调试）。
            title: str, 窗口标题（非全屏时可见）。
        """
        self._fullscreen = fullscreen
        self._current_img = None
        self._frame_source = None
        self._shortcuts = []
        self._running = False
        # ---- 创建 PyQt 应用 ----
        # QApplication 每个程序只能有一个。如果外部已经创建了，复用。
        self._app = QApplication.instance()
        if self._app is None:
            self._app = QApplication(sys.argv)
            self._app.setAttribute(Qt.AA_SynthesizeTouchForUnhandledMouseEvents, True)
            self._app.setAttribute(Qt.AA_SynthesizeMouseForUnhandledTouchEvents, True)

        # ---- 创建窗口 ----
        self._window = QWidget()
        self._window.setStyleSheet("background-color: black;")

        if fullscreen:
            self._window.showFullScreen()
        else:
            self._window.resize(800, 600)
            if title:
                self._window.setWindowTitle(title)

        # 初始化时缓存窗口尺寸，控件定位统一使用这两个值。
        self._window_width = self._window.width()
        self._window_height = self._window.height()

        # ---- 垂直布局 ----
        self._layout = QVBoxLayout(self._window)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # ---- 创建视频显示标签 ----
        # QVBoxLayout 把 QLabel 填满整个窗口
        self._video_label = QLabel("等待图像...")
        self._video_label.setAlignment(Qt.AlignCenter)
        self._video_label.setContentsMargins(0, 0, 0, 0)
        self._video_label.setStyleSheet("color: white; font-size: 20px;")
        self._layout.addWidget(self._video_label, stretch=1)

        # ---- 创建定时器 ----
        # 每 30ms 触发 _update_display，把最新画面渲染到屏幕上
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_display)
        self._timer.start(30)  # 每秒约刷新 33 次

        self._running = True
        mode = "全屏" if fullscreen else "窗口"
        print(f"[MyUI] {mode}界面已就绪")
        print(f"[MyUI] 界面大小: {self._window_width}x{self._window_height}")

    # ========== 画面显示（原 Display） ==========

    def _normalize_frame(self, img):
        """把输入统一成可显示的三通道 BGR 图像。

        Args:
            img: OpenCV 使用的 numpy.ndarray。

        Returns:
            numpy.ndarray: shape 为 (h, w, 3) 的 uint8 图像。
        """

        if not isinstance(img, np.ndarray):
            raise TypeError("img 必须是 numpy.ndarray")
        frame = img

        if frame.ndim == 2:
            frame = np.repeat(frame[:, :, None], 3, axis=2)
        elif frame.ndim == 3 and frame.shape[2] == 1:
            frame = np.repeat(frame, 3, axis=2)
        elif frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("img 的形状必须是 (h, w)、(h, w, 1) 或 (h, w, 3)")

        if frame.dtype != np.uint8:
            frame = frame.astype(np.uint8)

        return np.ascontiguousarray(frame)

    def show(self, img):
        """显示一张图像。
        用run就行，不需要在外面手动show了

        注意：这个方法只是把图像存入帧缓存，
        实际渲染由 QTimer 每 30ms 自动触发。

        Args:
            img: OpenCV 使用的 numpy.ndarray，要显示的图像；提交后不要继续修改像素。
        """
        if img is None:
            return

        # 统一成三通道 BGR，再交给 Qt 显示
        self._current_img = self._normalize_frame(img)

    def _update_display(self):
        """内部方法：把帧缓存中的画面渲染到屏幕上。

        被 QTimer 每 30ms 调用一次。
        将 numpy BGR 数组转为 QImage → QPixmap → 设置到 QLabel。

        知识点：
            QImage 构造参数：
                data: 像素数据指针（numpy 数组的 .data）
                w, h: 宽高
                bytesPerLine: 每行字节数 = 3 × 宽度
                Format_BGR888: 每个像素 3 字节、BGR 顺序（Qt 原生支持）

            QPixmap 是 QImage 的"显示优化版"，适合屏幕绘制。
            scaled() 把图像缩放到 QLabel 的大小。
            KeepAspectRatio: 保持宽高比不变形。
            SmoothTransformation: 双线性插值，画面更平滑。
        """
        if self._frame_source is not None:
            self.show(self._frame_source())

        if self._current_img is None:
            return

        h, w, ch = self._current_img.shape

        # numpy BGR → QImage（Format_BGR888，Qt 原生支持，零颜色转换）
        q_img = QImage(self._current_img.data, w, h, ch * w, QImage.Format_BGR888)

        # QImage → QPixmap → 缩放 → 显示
        pixmap = QPixmap.fromImage(q_img).scaled(
            self._video_label.width(),
            self._video_label.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self._video_label.setPixmap(pixmap)

    # ========== 交互控件（原 MyUI） ==========
    # 绝对坐标统一以 self._window（主窗口）的内容区左上角为原点 (0, 0)：
    # x 向右增大，y 向下增大，单位为像素。
    # 这里使用的是窗口内部坐标，不是屏幕全局坐标，也不是摄像头图像坐标。

    def in_window(self, pos, size):
        """把控件坐标限制在窗口内部。

        Args:
            pos: tuple(x, y), 控件左上角在主窗口内容区中的期望坐标。
            size: tuple(w, h), 控件自身的宽度和高度，单位为像素。

        Returns:
            tuple(int, int): 修正后的坐标，不会使控件超出窗口。
        """
        x, y = pos
        w, h = size
        safe_x = min(max(0, x), max(0, self._window_width - w))
        safe_y = min(max(0, y), max(0, self._window_height - h))
        return safe_x, safe_y

    def add_button(self, text, callback, rect=None):
        """添加一个按钮。

        Args:
            text: str, 按钮上显示的文字。
            callback: callable, 点击按钮时要执行的函数。
            rect: tuple(x, y, w, h) or None。
                x、y 是按钮左上角相对主窗口左上角的坐标；
                w、h 是按钮自身的宽度和高度，单位均为像素。
                如果为 None，不使用绝对坐标，由 QVBoxLayout 垂直排列。

        Returns:
            QPushButton: 创建好的 PyQt5 按钮对象。
        """
        btn = QPushButton(text, self._window)
        if rect is not None:
            try:
                x, y, w, h = rect
            except (TypeError, ValueError) as exc:
                raise ValueError("rect 必须是 (x, y, w, h)") from exc

            btn.setFixedSize(w, h)
            safe_x, safe_y = self.in_window((x, y), (w, h))
            btn.move(safe_x, safe_y)
        else:
            btn.setFixedSize(200, 50)
            # addWidget() 属于 PyQt5 的 QVBoxLayout。
            # 控件加入后，由布局管理器按添加顺序从上到下排列。
            self._layout.addWidget(btn)

        btn.setStyleSheet(BTN_STYLE)
        btn.clicked.connect(callback)

        # 主窗口已经在 __init__() 中显示。PyQt5 新建在“已显示父窗口”上的
        # 子控件默认仍是隐藏状态，必须主动调用 show() 才能看见。
        btn.show()

        # raise_() 属于 PyQt5 的 QWidget，用于把控件提升到同级控件最上层。
        # 方法名末尾的下划线是为了避开 Python 自带的 raise 异常关键字。
        # 这里确保按钮不会被用于显示摄像头画面的 QLabel 遮挡。
        btn.raise_()
        return btn

    def add_label(self, text, pos=None, color="white"):
        """添加一个文字标签。

        Args:
            text: str, 标签显示的文字。
            pos: tuple(x, y) or None。
                x、y 是文字标签左上角相对主窗口左上角的坐标。
                标签宽高由文字内容和字体自动计算。
                如果为 None，由 QVBoxLayout 自动排列。
            color: str, 文字颜色，如 "white"、"red"。
        """
        label = QLabel(text, self._window)
        label.setStyleSheet(f"color: {color}; font-size: 20px;")
        if pos is not None:
            try:
                x, y = pos
            except (TypeError, ValueError) as exc:
                raise ValueError("pos 必须是 (x, y)") from exc

            label.adjustSize()
            safe_x, safe_y = self.in_window(
                (x, y), (label.width(), label.height())
            )
            label.move(safe_x, safe_y)
            label.show()
            label.raise_()
        else:
            self._layout.addWidget(label)
        return label

    def add_slider(self, label_text, min_val, max_val, default, callback, pos=None):
        """添加一个带标签的滑块。

        Args:
            label_text: str, 滑块旁边的标签文字。
            min_val: int, 最小值。
            max_val: int, 最大值。
            default: int, 默认值。
            callback: callable(int), 滑块值改变时调用的函数。
            pos: tuple(x, y) or None。
                x、y 是“标签 + 滑块”整体左上角相对主窗口左上角的坐标，
                实际上也是标签左上角坐标；滑块位于 (x, y + 30)。
                滑块自身固定为 300×30 像素。
                如果为 None，标签和滑块分别交给 QVBoxLayout 垂直排列。
        """
        # 标签
        lbl = QLabel(f"{label_text}: {default}", self._window)
        lbl.setStyleSheet("color: white; font-size: 16px;")

        # 滑块
        slider = QSlider(Qt.Horizontal, self._window)
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(default)
        slider.setFixedSize(300, 30)
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 8px;
                background: #333;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                width: 20px;
                height: 20px;
                background: #FF69B4;
                border-radius: 10px;
                margin: -6px 0;
            }
        """)

        if pos is not None:
            try:
                x, y = pos
            except (TypeError, ValueError) as exc:
                raise ValueError("pos 必须是 (x, y)") from exc

            lbl.adjustSize()
            control_w = max(lbl.width(), slider.width())
            control_h = 30 + slider.height()
            safe_x, safe_y = self.in_window((x, y), (control_w, control_h))
            # pos 指向组合控件左上角：标签占上方，滑块向下偏移 30px。
            lbl.move(safe_x, safe_y)
            slider.move(safe_x, safe_y + 30)
            lbl.show()
            slider.show()
            lbl.raise_()
            slider.raise_()
        else:
            self._layout.addWidget(lbl)
            self._layout.addWidget(slider)

        # 滑块值改变时更新标签 + 回调
        def on_change(value):
            lbl.setText(f"{label_text}: {value}")
            callback(value)

        slider.valueChanged.connect(on_change)
        return slider

    # ========== 生命周期 ==========

    def run(self, frame_source=None):
        """进入 Qt 事件循环并持续刷新界面。

        Args:
            frame_source: callable 或 None。每次刷新时调用，返回一个
                numpy.ndarray 或 None；不需要自动取帧时传 None。

        Returns:
            int: Qt 事件循环的退出码，正常退出通常为 0。

        知识点：
            event loop（事件循环）负责处理键盘、触摸、窗口重绘和定时器。
            PyQt5 界面必须进入事件循环，窗口才会持续响应。
        """
        if frame_source is not None and not callable(frame_source):
            raise TypeError("frame_source 必须是 callable 或 None")

        self._frame_source = frame_source
        return self._app.exec_()

    def is_running(self):
        """判断界面是否还在运行。"""

        return self._running

    def process_events(self):
        """手动处理一次 Qt 事件。"""

        self._app.processEvents()

    def add_shortcut(self, key, callback):
        """添加一个窗口快捷键。
        用于键盘的，可以不用

        Args:
            key: str, Qt 能识别的按键名称，例如 ``"Q"`` 或 ``"Esc"``。
            callback: callable, 按下快捷键时执行的函数。

        Returns:
            QShortcut: 创建好的 PyQt5 快捷键对象。

        知识点：
            shortcut 的含义是“快捷键”。QShortcut 和 QKeySequence 都来自
            额外安装的 PyQt5，后者负责描述一个或一组按键。
        """
        shortcut = QShortcut(QKeySequence(key), self._window)
        shortcut.activated.connect(callback)
        self._shortcuts.append(shortcut)
        return shortcut

    def close(self):
        """关闭界面。

        停止定时器、关闭窗口。
        """
        if self._running:
            self._timer.stop()
            self._window.close()
            self._running = False
            print("[MyUI] 界面已关闭")

    def quit(self):
        """退出应用事件循环并关闭窗口。"""
        self.close()
        self._app.quit()  # pyright: ignore[reportOptionalMemberAccess]
