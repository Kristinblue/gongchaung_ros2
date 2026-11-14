"""
my_ui_ann.py — my_ui.py 的逐行注释版
=====================================
本文件是 my_ui.py 的完整拷贝，在此基础上加了极其详细的注释。
每一行代码、每一个概念都解释清楚。

阅读顺序建议：
  1. 先看文件头的"PyQt 核心概念速览"
  2. 再看 __init__ 方法（窗口是怎么建起来的）
  3. 然后看 show() 和 _update_display()（画面是怎么显示的）
  4. 最后看 add_button / add_label / add_slider（控件是怎么加的）

作者: Kristin
日期: 2026.7.17
"""

# ===================================================================
#  PyQt 核心概念速览（先读这里！）
# ===================================================================
#
# 你只要理解这五个东西，就能看懂整个文件：
#
# 1. QApplication — 应用程序本身
#    - 不是窗口，是整个程序
#    - 负责连接操作系统、接收鼠标键盘事件、管理所有窗口
#    - 一个程序只能有一个。创建第二个会报错
#    - 创建方式: app = QApplication(sys.argv)
#    - 启动方式: app.exec_()  → 进入事件循环，阻塞直到窗口关闭
#
# 2. QWidget — 窗口 / 控件
#    - 一切可见的东西都是 QWidget 的子类
#    - QLabel（文字/图片标签）、QPushButton（按钮）、QSlider（滑块）
#      都是 QWidget 的子类
#    - 每个控件可以设置位置大小、样式、父子关系
#    - 创建方式: widget = QWidget()
#    - 显示方式: widget.show() 或 widget.showFullScreen()

#
# 3. 信号与槽（Signal & Slot）— 事件处理
#    - 信号: 某件事发生了（按钮被点击、定时器到点、滑块值改变）
#    - 槽:   事件发生时要执行的函数
#    - 连接: signal.connect(slot_function)
#    - 例子:
#        btn.clicked.connect(my_function)       # 按钮点击 → 执行 my_function
#        timer.timeout.connect(update_display)  # 定时器到点 → 执行 update_display
#        slider.valueChanged.connect(on_change) # 滑块值变 → 执行 on_change
#
# 4. QTimer — 定时器
#    - 一个闹钟，每隔 N 毫秒触发一次 timeout 信号
#    - 创建: timer = QTimer()
#    - 设置回调: timer.timeout.connect(函数)
#    - 启动: timer.start(30)  # 每 30 毫秒触发一次
#    - 停止: timer.stop()
#
# 5. QVBoxLayout — 垂直布局
#    - 自动管理控件的位置和大小
#    - 从上到下排列，窗口缩放时自动调整
#    - 创建: layout = QVBoxLayout(window)
#    - 添加控件: layout.addWidget(label, stretch=1)
#      stretch=1 表示这个控件会占用所有剩余空间（撑满窗口）
#
# ===================================================================

import sys
import os
import numpy as np
from PyQt5.QtWidgets import (QApplication, QLabel, QWidget, QVBoxLayout,
                             QPushButton, QSlider)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QTimer, Qt

# 消除 PyQt 在终端打印的无用调试信息
# 不加这行的话，每次启动都会打印一堆 "QGtkStyle could not resolve..." 之类的东西
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.*=false"

# ================================================================
#  BTN_STYLE — 按钮统一样式
# ================================================================
# Qt StyleSheet 语法和网页 CSS 几乎一样。
# 这里定义三种状态的颜色：
#   普通状态：粉色 #FF69B4
#   鼠标悬停：亮粉 #FF1493
#   鼠标按下：暗粉 #C71585
# 所有按钮共用这个样式，修改一处就全部生效。
BTN_STYLE = """
    QPushButton {
        background-color: #FF69B4;
        color: white;
        border-radius: 10px;
        font-size: 18px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #FF1493;
    }
    QPushButton:pressed {
        background-color: #C71585;
    }
"""


class MyUI:
    """项目统一界面。

    一个全屏窗口同时承载：
    - 摄像头画面：show(img) 存入帧缓存，QTimer 每 30ms 自动渲染
    - 交互控件：add_button / add_label / add_slider

    用法示例：
        ui = MyUI()                                      # 1. 创建界面
        ui.add_button("退出", ui.quit, (50, 50, 200, 60))  # 2. 加个退出按钮

        sequence = 0
        while ui.is_running():
            img, number = cam.latest(sequence)            # 3. 从采集线程取最新帧
            if img is not None:
                sequence = number
                img = img.copy()                         # 4. 复制后直接用 OpenCV 绘图
                cv2.rectangle(img, (10, 10), (60, 60), (0, 255, 0), 2)
                ui.show(img)                             # 5. 显示
            ui.process_events()                          # 6. 处理窗口事件

    注意：show(img) 只是把图像存入帧缓存，不立即渲染。
          实际渲染由 QTimer 每 30ms 自动触发 _update_display()。
          这样做的好处是：show() 不阻塞，主循环可以继续做别的事。

    Attributes:
        _app: QApplication
            整个 PyQt 程序的大脑。一个程序只能有一个。
            负责连接操作系统、接收事件、管理所有窗口。
            如果外部已经创建了 QApplication，这里会复用。

        _window: QWidget
            全屏窗口。所有控件（标签、按钮、视频画面）都放在这个窗口上。
            窗口背景是黑色的。

        _layout: QVBoxLayout
            垂直布局管理器。自动管理控件在窗口中的位置。
            视频标签放在最上面，占满剩余空间。

        _widgets: list
            已添加的控件列表。用于 set_label() 查找控件。
            暂时不用它，被我deprcate哩！

        _video_label: QLabel
            视频显示标签。摄像头画面最终渲染到这个标签上。
            用 QVBoxLayout 填满整个窗口。

        _current_img: numpy.ndarray or None
            帧缓存。show(img) 存入最新帧的 numpy BGR 数组引用。
            _update_display() 从这里取出渲染。
            是引用不是拷贝，所以零内存开销。

        _timer: QTimer
            帧刷新定时器。每 30ms 触发一次 timeout 信号，
            信号连接到 _update_display()，自动渲染最新画面。
            30ms ≈ 33 FPS，比摄像头 60fps（16ms）慢一半，
            但人眼看不出区别，CPU 省一半。

        _running: bool
            界面是否正在运行。close() 时设为 False。
    """

    def __init__(self, fullscreen=True, title=""):
        """初始化界面。

        按顺序做五件事：
          1. 创建 QApplication（或复用已有的）
          2. 创建全屏窗口（黑色背景）
          3. 创建视频显示标签（QLabel，填满窗口）
          4. 创建帧刷新定时器（每 30ms 自动渲染）
          5. 标记界面已就绪

        Args:
            fullscreen: bool, 是否全屏。默认 True。
                        设为 False 时会显示 800×600 的普通窗口，
                        方便在电脑上调试（不用占满整个屏幕）。
            title: str, 窗口标题。只在非全屏时可见。
        """
        # ---- 初始化成员变量 ----
        self._fullscreen = fullscreen
        # 是否全屏
        self._current_img = None
        # 帧缓存，还没收到过图像所以是 None
        self._running = False
        # 界面还没启动完毕
        self._widgets = []
        # 控件列表，初始为空

        # ================================================================
        #  第1步：创建 QApplication（整个 PyQt 程序的大脑）
        # ================================================================
        #
        # QApplication 是整个 PyQt 程序的起点。它负责：
        #   - 连接操作系统的显示服务器（X11/Wayland）
        #   - 接收鼠标点击、键盘按下、窗口拖拽等事件
        #   - 把事件分发给对应的控件
        #   - 管理所有窗口、字体、颜色等全局资源
        #
        # 为什么全局只能有一个？
        #   因为操作系统只给你的程序分配一个到显示服务器的连接。
        #   创建两个 QApplication 就像一根电话线接了两个电话机，会冲突。
        #
        # QApplication.instance() 检查是不是已经有人创建过了。pyqt自带的方法
        # 如果返回 None，说明还没人创建 → 我们来创建。
        # 如果返回一个已有的实例，说明外部已经创建了 → 直接复用。
        self._app = QApplication.instance()
        # 检查是否已有 QApplication 实例
        if self._app is None:
            # 还没有人创建 → 我们来创建
            self._app = QApplication(sys.argv) #传递命令行参数
            # sys.argv 是命令行参数，PyQt 会从中提取一些自己的参数
            # （比如 -style=fusion 强制使用特定主题）

            # 启用触摸支持
            # 这俩属性让 PyQt 在触摸屏和鼠标之间自动转换：
            #   AA_SynthesizeTouchForUnhandledMouseEvents:
            #       鼠标事件没被处理时，自动转成触摸事件
            #   AA_SynthesizeMouseForUnhandledTouchEvents:
            #       触摸事件没被处理时，自动转成鼠标事件
            # 这样触摸屏和鼠标都能正常工作
            self._app.setAttribute(Qt.ApplicationAttribute.AA_SynthesizeTouchForUnhandledMouseEvents, True)
            self._app.setAttribute(Qt.ApplicationAttribute.AA_SynthesizeMouseForUnhandledTouchEvents, True)

        # ========================================
        #  第2步：创建窗口
        # ========================================
        #
        # QWidget() 创建一个空白窗口。
        # 这是最基础的窗口类，所有控件都放在它上面。
        # setStyleSheet("background-color: black;") 把窗口背景设为黑色。
        # 这样在摄像头画面还没出来时，屏幕是纯黑的，不会闪白屏。
        self._window = QWidget()
        # 创建空白窗口
        self._window.setStyleSheet("background-color: black;")
        # 设背景为黑色

        if fullscreen:
            # 全屏模式：窗口占满整个屏幕，没有标题栏、没有边框
            self._window.showFullScreen()
            # 让窗口全屏显示
        else:
            # 窗口模式：显示 800×600 的普通窗口
            # 适合在电脑上调试，不用占满整个屏幕
            self._window.resize(800, 600)
            # 设置窗口大小为 800×600
            if title:
                self._window.setWindowTitle(title)
                # 设置窗口标题（只在非全屏时可见）

        # ========================================
        #  第3步：创建布局和视频显示标签
        # ========================================
        #
        # QVBoxLayout 是垂直布局管理器。
        # 它自动管理控件在窗口中的位置和大小：
        #   - 控件从上到下排列
        #   - 窗口缩放时自动调整
        #
        # stretch=1 的含义：
        #   layout.addWidget(label, stretch=1)
        #   stretch 是"拉伸因子"。stretch=1 表示这个控件
        #   会占用所有剩余空间。因为只有一个控件，所以它会填满整个窗口。
        #
        # QLabel 是一个显示文字或图片的控件。
        # 我们用它来显示摄像头画面：
        #   - 初始时显示"等待图像..."（白色文字，居中）
        #   - 收到画面后，把 QLabel 的内容换成图像
        self._layout = QVBoxLayout(self._window)
        # 创建垂直布局，绑定到窗口

        self._video_label = QLabel("等待图像ing...")
        # 创建视频显示标签，初始文字是"等待图像..."
        self._video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 文字水平+垂直居中
        self._video_label.setStyleSheet("color: white; font-size: 20px;")
        # 白色文字，20px 大小
        self._layout.addWidget(self._video_label, stretch=1)
        # 把标签加入布局，stretch=1 让它占满整个窗口

        # ========================================
        #  第4步：创建帧刷新定时器
        # ========================================
        #
        # QTimer 是一个闹钟。我们设它每 30 毫秒响一次。
        # 每次响的时候，自动调用 _update_display() 渲染最新画面。
        #
        # 为什么是 30ms？
        #   - 摄像头 60fps = 每 16ms 产出一帧新图
        #   - 定时器 30ms = 每秒刷新约 33 次
        #   - 比摄像头慢一半，但人眼完全看不出区别
        #   - CPU 省一半：不会重复渲染同一帧画面
        #
        # 如果设成 16ms（60fps），定时器会和摄像头同步刷新，
        # 但两帧之间摄像头画面没变，白白浪费 CPU。
        #
        # timeout 信号 → connect → _update_display 槽函数
        # 这是 PyQt 信号与槽机制的经典用法。
        self._timer = QTimer()
        # 创建定时器
        self._timer.timeout.connect(self._update_display)
        # 定时器到点 → 自动调用 _update_display()
        self._timer.start(30)
        # 每 30 毫秒触发一次，≈ 33 FPS

        # ---- 标记界面已就绪 ----
        self._running = True
        mode = "全屏" if fullscreen else "窗口"
        print(f"[MyUI] {mode}界面已就绪")

    # ================================================================
    #  画面显示部分
    # ================================================================
    #
    # 这部分负责把摄像头画面渲染到屏幕上。
    # 设计思路：
    #   show(img) 只管"存"——把最新帧数据记下来
    #   _update_display() 只管"画"——把记下来的数据渲染到屏幕
    #   存和画是解耦的：
    #     - 你随时调用 show() 更新数据
    #     - 定时器每 30ms 自动调用 _update_display() 渲染
    #
    # 类比：
    #   摄影师每秒拍 60 张照片（摄像头）
    #   show() = 把最新照片塞进相框背后（没人看见）
    #   定时器 = 每 30ms 把相框翻过来给观众看一眼
    #   _update_display() = 翻相框的动作

    def show(self, img):
        """显示一张 NumPy 数组。

        输入是 OpenCV 使用的 BGR NumPy 数组。
        注意：这个方法只是把图像存入帧缓存（self._current_img），
        不立即渲染。实际渲染由 QTimer 每 30ms 自动触发。

        为什么要这样设计？
          1. show() 不阻塞，调用后立刻返回，主循环可以继续做别的事
          2. 定时器每 30ms 渲染一次，不会重复渲染同一帧
          3. 如果你调用 show() 比定时器快，中间的帧会被跳过（只保留最新帧）
             这正好就是我们要的效果——永远显示最新画面

        Args:
            img: numpy.ndarray，要显示的图像。
        """
        if img is None:
            return
            # 传了空图像进来，什么都不做

        # img 本身就是 numpy BGR 数组，这里只保存引用（不是拷贝！）
        # 把这个引用存到 self._current_img，零内存开销
        # QImage.Format_BGR888 是 Qt 原生支持的 BGR 格式，不需要颜色转换
        self._current_img = img
        # 存入帧缓存，等待定时器来渲染

    def _update_display(self):
        """内部方法：把帧缓存中的画面渲染到屏幕上。

        被 QTimer 每 30ms 自动调用一次（通过 timeout 信号连接）。
        渲染流程：
          numpy BGR 数组 → QImage → QPixmap → 缩放到窗口大小 → 贴到 QLabel

        每一步的细节：
          1. numpy BGR 数组
             这是 show(img) 存入的 self._current_img
             形状是 (height, width, 3)，dtype=uint8
             每个像素 3 个字节：B、G、R

          2. QImage(data, w, h, bytesPerLine, Format_BGR888)
             QImage 是 Qt 的"图像"对象
             data: 像素数据指针，指向 numpy 数组的内存
             w, h: 宽和高
             bytesPerLine: 每行多少字节。BGR 3 通道 × 宽度
             Format_BGR888: 告诉 Qt 这数据是 BGR 格式的，不用转换
             因为 Format_BGR888 是 Qt 原生支持的，所以这一步是零开销的

          3. QPixmap.fromImage(q_img)
             QPixmap 是 QImage 的"显示优化版"
             它把像素数据搬到显存（GPU 内存）里，渲染更快
             这一步会拷贝一次像素数据（从内存到显存）

          4. .scaled(label_width, label_height, KeepAspectRatio, SmoothTransformation)
             把图像缩放到 QLabel 的大小
             KeepAspectRatio: 保持宽高比，不会拉伸变形
             SmoothTransformation: 双线性插值，比最近邻插值更平滑

          5. self._video_label.setPixmap(pixmap)
             把缩放后的像素图贴到 QLabel 上
             用户就看到画面了

        注意：
          self._current_img.data 返回的是 memoryview（内存视图），
          指向 numpy 数组的原始内存。QImage 构造时不会拷贝这份数据，
          而是直接引用。所以 numpy 数组必须在 QImage 存活期间保持有效。
          这里 QImage 是局部变量，函数结束时销毁，在销毁前
          QPixmap.fromImage() 已经把数据拷到显存了，所以安全。
        """
        if self._current_img is None:
            return
            # 帧缓存是空的（还没调用过 show() 或者传了 None）
            # 什么都不画，等下次定时器触发

        h, w, ch = self._current_img.shape
        # 获取图像的高度、宽度、通道数
        # ch 应该是 3（BGR 三通道）

        # ---- 第1步：numpy 数组 → QImage ----
        # QImage 构造参数：
        #   第1个参数 data: 像素数据指针
        #       self._current_img.data 返回 numpy 数组的 memoryview
        #       这是一个指向原始内存的指针，零拷贝
        #   第2、3个参数 w, h: 宽度和高度
        #   第4个参数 bytesPerLine: 每行的字节数
        #       BGR 3 通道 × 宽度 = 每行像素数 × 每像素字节数
        #   第5个参数 format: 像素格式
        #       Format_BGR888 = 每像素 3 字节，B、G、R 顺序
        #       Qt 原生支持这个格式，不需要做颜色空间转换
        q_img = QImage(self._current_img.data, w, h, ch * w, QImage.Format_BGR888)

        # ---- 第2步：QImage → QPixmap（拷到显存）→ 缩放到窗口大小 ----
        # QPixmap.fromImage(q_img) 把 QImage 转成 QPixmap
        #   QPixmap 存在显存里，渲染时直接从显存读，比从内存读快很多
        #   这一步会拷贝像素数据（从内存到显存），是必要的开销
        #
        # .scaled(...) 把图像缩放到 QLabel 的大小
        #   如果图像和标签一样大，就不会缩放（零开销）
        #   如果图像更大或更小，会按比例缩放
        pixmap = QPixmap.fromImage(q_img).scaled(
            self._video_label.width(),
            # 标签的当前宽度（像素）
            self._video_label.height(),
            # 标签的当前高度（像素）
            Qt.AspectRatioMode.KeepAspectRatio,
            # 保持宽高比，不会把圆压成椭圆
            Qt.TransformationMode.SmoothTransformation
            # 双线性插值，放大缩小都平滑
            # 对比：Qt.FastTransformation 更快但有锯齿
        )

        # ---- 第3步：贴到标签上 ----
        # setPixmap() 把 QPixmap 设置到 QLabel 上
        # 用户就看到画面了
        self._video_label.setPixmap(pixmap)

    # ================================================================
    #  交互控件部分
    # ================================================================
    #
    # 这部分提供按钮、标签、滑块等控件的工厂方法。
    # 每个方法都返回 None（不返回控件对象），
    # 控件自动加到窗口上，不需要手动管理。
    #
    # 所有控件都放在 self._window 上，
    # 和视频显示标签共享同一个窗口。

    def add_button(self, text, callback, rect=None):
        """添加一个按钮。

        按钮使用统一的 BTN_STYLE 样式（粉色圆角）。
        鼠标悬停时变亮，按下时变暗。

        Args:
            text: str, 按钮上显示的文字。
            callback: callable, 点击按钮时要执行的函数。
                      比如 ui.quit（退出程序）、lambda: print("hello")。
            rect: tuple(x, y, w, h) or None, 按钮的位置和大小。
                   (x, y) 是按钮左上角在窗口中的坐标。
                   (w, h) 是按钮的宽度和高度。
                   如果传 None，按钮用自动布局（垂直排列，200×50 大小）。
        """
        # 创建 QPushButton 控件
        # 第1个参数 text: 按钮上显示的文字
        # 第2个参数 parent: 父控件，这里是 self._window
        #   指定父控件后，按钮就出现在这个窗口上
        #   窗口关闭时，所有子控件自动销毁
        btn = QPushButton(text, self._window)

        if rect is not None:
            # 用户指定了位置和大小 → 绝对定位
            x, y, w, h = rect
            # 解包：(x, y) = 左上角坐标，(w, h) = 宽高
            btn.setFixedSize(w, h)
            # 固定按钮大小为 w × h 像素
            btn.move(x, y)
            # 把按钮移到窗口的 (x, y) 位置
        else:
            # 用户没指定位置 → 使用默认大小
            btn.setFixedSize(200, 50)
            # 默认 200×50 像素

        # 使用顶部定义的 BTN_STYLE 统一样式
        # 修改 BTN_STYLE 一处，所有按钮全部生效
        btn.setStyleSheet(BTN_STYLE)

        # 信号与槽：按钮被点击 → 执行 callback
        # btn.clicked 是"按钮被点击"信号
        # .connect(callback) 把信号连接到槽函数
        # 当用户点击按钮时，PyQt 自动调用 callback()
        btn.clicked.connect(callback)

        # 把按钮加入控件列表，方便后续查找（比如 set_label）
        #self._widgets.append(btn)


    def add_label(self, text, pos=None, color="white"):
        """添加一个文字标签。

        标签用于显示状态信息、提示文字等。
        可以通过 set_label() 后续更新文字。

        Args:
            text: str, 标签显示的文字。
            pos: tuple(x, y) or None, 标签左上角在窗口中的坐标。
                 传 None 则使用自动布局。
            color: str, 文字颜色。可以是 "white"、"red"、"#FF69B4" 等。
        """
        # 创建 QLabel 控件
        # 第1个参数 text: 显示的文字
        # 第2个参数 parent: 父控件，这里是 self._window
        #   QLabel 和 QPushButton 一样，都是 QWidget 的子类
        #   指定 parent 后，标签就出现在这个窗口上
        label = QLabel(text, self._window)

        # 设置样式：文字颜色 + 字体大小
        # f-string 把 color 变量嵌入 CSS
        # 比如 color="white" → "color: white; font-size: 20px;"
        label.setStyleSheet(f"color: {color}; font-size: 20px;")

        if pos is not None:
            # 用户指定了位置 → 绝对定位
            x, y = pos
            label.move(x, y)
            # 把标签移到 (x, y) 位置

        # 加入控件列表
       # self._widgets.append(label)
        return label  #需要返回qlabel对象，就能直接用pyqt里内置的方法啦

    def add_slider(self, label_text, min_val, max_val, default, callback, pos=None):
        """添加一个带标签的滑块。

        滑块用于调节参数（比如亮度、对比度、阈值等）。
        包含一个文字标签 + 一个水平滑块。
        拖动滑块时，标签自动更新显示当前值，同时调用 callback。

        Args:
            label_text: str, 滑块旁边的标签文字。比如 "亮度"。
            min_val: int, 滑块最小值。
            max_val: int, 滑块最大值。
            default: int, 滑块默认值。
            callback: callable(int), 滑块值改变时调用的函数。
                      函数接收一个 int 参数（当前滑块值）。
            pos: tuple(x, y) or None, 滑块+标签的位置。
        """
        # ---- 创建标签 ----
        # 初始显示 "label_text: default"，比如 "亮度: 50"
        lbl = QLabel(f"{label_text}: {default}", self._window)
        lbl.setStyleSheet("color: white; font-size: 16px;")
        # 白色文字，16px 大小

        # ---- 创建滑块 ----
        # QSlider(Qt.Horizontal, parent) 创建水平滑块
        # Qt.Horizontal 表示水平方向（左右拖）
        # Qt.Vertical 是垂直方向（上下拖）
        slider = QSlider(Qt.Orientation.Horizontal, self._window)
        slider.setMinimum(min_val)
        # 最小值
        slider.setMaximum(max_val)
        # 最大值
        slider.setValue(default)
        # 当前值（初始位置）
        slider.setFixedSize(300, 30)
        # 固定大小 300×30 像素

        # 滑块的样式：
        #   groove:horizontal 滑槽（背景条）：
        #       8px 高，深灰 #333，圆角
        #   handle:horizontal 滑柄（拖动的圆钮）：
        #       20×20 大小，粉色 #FF69B4，圆形（border-radius: 10px）
        #       margin: -6px 0 让滑柄垂直居中在滑槽上
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
            # 用户指定了位置 → 绝对定位
            x, y = pos
            lbl.move(x, y)
            # 标签放在 (x, y)
            slider.move(x, y + 30)
            # 滑块放在标签下方 30px
        else:
            # 自动布局 → 加入垂直布局
            self._layout.addWidget(lbl)
            self._layout.addWidget(slider)

        # ---- 连接信号 ----
        # slider.valueChanged 是"滑块值改变"信号
        # 它会在用户拖滑块时自动触发，传当前值作为参数
        #
        # on_change(value) 是内部函数，做了两件事：
        #   1. 更新标签文字：lbl.setText(f"{label_text}: {value}")
        #   2. 调用用户的 callback(value)
        def on_change(value):
            lbl.setText(f"{label_text}: {value}")
            # 更新标签显示当前值
            callback(value)
            # 调用用户的回调函数

        slider.valueChanged.connect(on_change)
        # 滑块值改变 → 执行 on_change

        # 把标签和滑块都加入控件列表
        #self._widgets.extend([lbl, slider])

    #[deprecated]pyqt里qlabel本就是一个类，直接用label.setText()就可以更新文字了,我觉得没必要重开一个类
    #def set_label(self, index, text):
        """更新已有标签的文字。

        用于动态更新状态信息。比如：
          ui.set_label(0, f"FPS: {fps}")  # 更新第0个标签显示帧率

        Args:
            index: int, 标签的序号。按 add_label() 的调用顺序编号。
                   第1次调 add_label() 加的标签是 index=0，
                   第2次是 index=1，以此类推。
            text: str, 新文字。
        """
    """    count = 0
        # 计数器：当前是第几个 QLabel
        for w in self._widgets:
            # 遍历所有控件
            if isinstance(w, QLabel):
                # 是 QLabel 类型（注意：不是 QPushButton 或 QSlider）
                if count == index:
                    # 找到了！这就是第 index 个标签
                    w.setText(text)
                    # 更新文字
                    return
                    # 完成，退出
                count += 1
                # 还没找到，计数器+1
    """
    # ========================================
    #  生命周期
    # ========================================

    def close(self):
        """关闭界面。

        停止定时器、关闭窗口。
        注意：close() 只关闭界面，不退出程序。
              如果要完全退出程序（结束事件循环），用 quit()。
        """
        if self._running:
            self._timer.stop()
            # 停止定时器，不再刷新画面
            self._window.close()
            # 关闭窗口，释放窗口资源
            self._running = False
            # 标记已关闭
            print("[MyUI] 界面已关闭")

    def quit(self):
        """退出应用事件循环并关闭窗口。

        调用后会：
          1. 关闭界面（停止定时器+关闭窗口）
          2. 调用 app.quit() 结束事件循环
          3. 程序退出

        通常绑在"退出"按钮上：
          ui.add_button("退出", ui.quit)
        """
        self.close()
        # 先关闭界面
        self._app.quit()  # pyright: ignore[reportOptionalMemberAccess]
        # 结束事件循环，程序退出
