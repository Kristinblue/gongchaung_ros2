"""安全区图片调试窗口；图片、模型路径和交互集中在这里。"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QEvent, QRectF, QPointF, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSpinBox, QToolTip, QVBoxLayout, QWidget

from segment import DEFAULTS, segment_safety

# 日常更换图片目录、模型时只改这里。不会读取或启动小车工程。
IMAGE_DIR = Path(__file__).resolve().parents[1] / 'assets' / 'first'
START_IMAGE = 'frame_0298.jpg'
MODEL_PATH = r'D:\my_project\deeplearning\yolov8_simple_use\pre_model\gongchuang\second\train5\best.onnx'
YOLO_CONF = 0.35
SETTINGS_FILE = Path(__file__).parent / 'settings.json'
SAFE_NAMES = ('bsafe', 'rsafe')


def read_image(path):
    """读取含中文路径的原图，保持BGR通道顺序。"""
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def sample_limits(pixels):
    """H取覆盖90%样本的最短圆周范围，S/V取P05–P95，避免179→0被展开成全色相。"""
    low, high = np.percentile(pixels, [5, 95], axis=0).astype(int)
    hues = np.sort(pixels[:, 0].astype(int))
    count = max(1, int(np.ceil(len(hues)*.9)))
    extended = np.concatenate((hues, hues+180))
    widths = extended[count-1:count-1+len(hues)]-hues
    start = int(np.argmin(widths))
    low[0], high[0] = extended[start]%180, extended[start+count-1]%180
    return low, high


def annotation_rois(path, shape):
    """只读同名标注，JSON优先；保留所有安全区实例。"""
    json_path = path.with_suffix('.json')
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding='utf-8'))
        boxes = []
        for item in data['shapes']:
            if item['label'] in SAFE_NAMES:
                points = np.asarray(item['points'])
                boxes.append([*points.min(axis=0), *points.max(axis=0)])
        return boxes
    height, width = shape[:2]
    boxes = []
    for line in path.with_suffix('.txt').read_text(encoding='utf-8-sig').splitlines():
        values = line.split()
        if len(values) == 5 and int(values[0]) in (4, 5):
            cx, cy, w, h = map(float, values[1:])
            boxes.append([(cx-w/2)*width, (cy-h/2)*height, (cx+w/2)*width, (cy+h/2)*height])
    return boxes


class Inference(QThread):
    """换图时推理一次；调HSV时复用结果，界面不等待模型加载。"""

    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, image, model=None):
        super().__init__()
        self.image, self.model = image, model

    def run(self):
        try:
            if self.model is None:
                from ultralytics import YOLO
                self.model = YOLO(MODEL_PATH, task='detect')
            result = self.model.predict(self.image, conf=YOLO_CONF, device='cpu', verbose=False)[0]
            boxes = []
            for box, kind in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.cls.cpu().numpy()):
                if result.names[int(kind)] in SAFE_NAMES:
                    boxes.append(box.tolist())
            self.completed.emit(boxes)
        except Exception as exc:
            self.failed.emit(str(exc))


class ImageView(QWidget):
    """等比例显示图片，并将鼠标框选换算回原图坐标。"""

    selected = pyqtSignal(object)

    def __init__(self, selectable=False):
        super().__init__()
        self.picture = None
        self.ok = None
        self.selection = self.start = None
        self.selectable = selectable
        self.setMinimumSize(280, 180)
        if selectable:
            self.setCursor(Qt.CrossCursor)

    def set_image(self, image, *, ok=None):
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        else:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        height, width = image.shape[:2]
        self.picture = QImage(image.data, width, height, image.strides[0], QImage.Format_RGB888).copy()
        self.ok = ok
        self.update()

    def image_rect(self):
        width, height = self.picture.width(), self.picture.height()
        scale = min(self.width()/width, self.height()/height)
        return QRectF((self.width()-width*scale)/2, (self.height()-height*scale)/2, width*scale, height*scale)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#13171e'))
        if self.picture is None:
            return
        rect = self.image_rect()
        painter.drawImage(rect, self.picture)
        if self.ok is not None:
            text = f'ok={self.ok}'
            metrics = painter.fontMetrics()
            width, height = metrics.horizontalAdvance(text)+16, metrics.height()+8
            badge = QRectF(rect.right()-width-8, rect.top()+8, width, height)
            painter.fillRect(badge, QColor('#13171e'))
            painter.setPen(QColor('#9be6ad' if self.ok else '#ffae83'))
            painter.drawText(badge, Qt.AlignCenter, text)
        if self.selection is not None:
            x1, y1, x2, y2 = self.selection
            scale = rect.width()/self.picture.width()
            painter.setPen(QPen(QColor('#ffcc66'), 2, Qt.DashLine))
            painter.drawRect(QRectF(rect.x()+x1*scale, rect.y()+y1*scale, (x2-x1)*scale, (y2-y1)*scale))

    def image_point(self, point):
        rect = self.image_rect()
        x = (point.x()-rect.x())*self.picture.width()/rect.width()
        y = (point.y()-rect.y())*self.picture.height()/rect.height()
        return int(np.clip(x, 0, self.picture.width())), int(np.clip(y, 0, self.picture.height()))

    def mousePressEvent(self, event):
        if self.selectable and self.picture and event.button() == Qt.LeftButton and self.image_rect().contains(event.pos()):
            self.start = self.image_point(event.pos())

    def mouseMoveEvent(self, event):
        if self.start is not None:
            x, y = self.image_point(event.pos())
            a, b = self.start
            self.selection = (min(a, x), min(b, y), max(a, x), max(b, y))
            self.update()

    def mouseReleaseEvent(self, event):
        if self.start is not None:
            self.mouseMoveEvent(event)
            self.start = None
            if self.selection[2]-self.selection[0] > 1 and self.selection[3]-self.selection[1] > 1:
                self.selected.emit(self.selection)


class Histogram(QWidget):
    """显示框选原图的H/S/V直方图，每个通道单独归一化。"""

    def __init__(self):
        super().__init__()
        self.values = None
        self.hover = None
        self.setMouseTracking(True)
        self.setMinimumHeight(270)

    def set_pixels(self, pixels):
        self.values = [np.bincount(pixels[:, i], minlength=bins) for i, bins in enumerate((180, 256, 256))]
        self.clear_hover()

    def plot_rect(self, index):
        """绘图和鼠标读数共用同一块坐标区域。"""
        return QRectF(48, index*self.height()/3+10, self.width()-64, self.height()/3-32)

    def clear_hover(self):
        self.hover = None
        QToolTip.hideText()
        self.update()

    def mouseMoveEvent(self, event):
        for index, (name, bins) in enumerate((('H', 180), ('S', 256), ('V', 256))):
            plot = self.plot_rect(index)
            if plot.contains(event.pos()):
                value = round((event.pos().x()-plot.left())*(bins-1)/plot.width())
                self.hover = (index, value)
                text = f'{name} = {value}'
                if self.values is None:
                    text += '\n先在左上原图框选取色'
                else:
                    hist = self.values[index]
                    count = int(hist[value])
                    text += f'\n像素数：{count}\n相对峰值：{100*count/max(1, hist.max()):.1f}%'
                QToolTip.showText(event.globalPos(), text, self, plot.toRect())
                self.update()
                return
        self.clear_hover()

    def leaveEvent(self, event):
        self.clear_hover()

    def resizeEvent(self, event):
        self.clear_hover()
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor('#131923'))
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        for i, (name, color, bins) in enumerate((('H', '#c48bff', 180), ('S', '#70dbc1', 256), ('V', '#f7d281', 256))):
            plot = self.plot_rect(i)
            painter.setPen(QColor(color))
            painter.drawText(8, int(plot.center().y()+4), name)
            for fraction, label in ((0, '100'), (.5, '50'), (1, '0')):
                y = plot.top()+plot.height()*fraction
                painter.setPen(QPen(QColor('#354052'), 1, Qt.DotLine))
                painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
                painter.setPen(QColor('#8794a8'))
                painter.drawText(QRectF(21, y-7, 23, 14), Qt.AlignRight | Qt.AlignVCenter, label)
            for value in (0, 45, 90, 135, 179) if bins == 180 else (0, 64, 128, 192, 255):
                x = plot.left()+plot.width()*value/(bins-1)
                painter.setPen(QPen(QColor('#354052'), 1, Qt.DotLine))
                painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
                painter.setPen(QColor('#8794a8'))
                painter.drawText(QRectF(x-14, plot.bottom()+3, 28, 17), Qt.AlignCenter, str(value))
            if self.values is None:
                continue
            hist = self.values[i]
            points = [QPointF(plot.left()+j*plot.width()/(bins-1), plot.bottom()-v/max(1, hist.max())*plot.height()) for j, v in enumerate(hist)]
            fill = QColor(color)
            fill.setAlpha(35)
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawPolygon(QPolygonF([plot.bottomLeft(), *points, plot.bottomRight()]))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(color), 1.5))
            painter.drawPolyline(QPolygonF(points))
            if self.hover is not None and self.hover[0] == i:
                point = points[self.hover[1]]
                painter.setPen(QPen(QColor('#dce7f7'), 1, Qt.DashLine))
                painter.drawLine(QPointF(point.x(), plot.top()), QPointF(point.x(), plot.bottom()))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(color))
                painter.drawEllipse(point, 3, 3)
                painter.setBrush(Qt.NoBrush)


class Window(QMainWindow):
    """四图对照、图片切换、阈值调节和鼠标取色。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle('安全区识别 · HSV 调试')
        self.resize(1500, 930)
        self.setFocusPolicy(Qt.StrongFocus)
        self.paths = sorted(p for p in IMAGE_DIR.iterdir() if p.suffix.lower() in ('.jpg', '.jpeg', '.png') and not p.name.startswith('_'))
        self.index = next((i for i, path in enumerate(self.paths) if path.name == START_IMAGE), 0)
        self.model = self.worker = None
        self.cache = {}
        self.rois = []
        self.result = None
        self.controls = {}
        self.sample_pixels = None
        self.settings = dict(DEFAULTS)
        if SETTINGS_FILE.exists():
            saved = json.loads(SETTINGS_FILE.read_text(encoding='utf8'))
            self.settings.update({key: saved[key] for key in DEFAULTS if key in saved})
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        left = QVBoxLayout()
        bar = QHBoxLayout()
        self.previous = QPushButton('← 上一张 A')
        self.next = QPushButton('下一张 D →')
        self.previous.clicked.connect(lambda: self.navigate(-1))
        self.next.clicked.connect(lambda: self.navigate(1))
        self.filename = QLabel()
        self.filename.setAlignment(Qt.AlignCenter)
        bar.addWidget(self.previous)
        bar.addWidget(self.filename, 1)
        bar.addWidget(self.next)
        left.addLayout(bar)
        grid = QGridLayout()
        self.views = []
        for index, title in enumerate(('01  原图 / ROI · 拖动取色', '02  紫色 HSV 二值图', '03  拟合四边形', '04  安全区位置')):
            panel = QGroupBox(title)
            inner = QVBoxLayout(panel)
            view = ImageView(index == 0)
            inner.addWidget(view)
            self.views.append(view)
            grid.addWidget(panel, index//2, index%2)
        self.views[0].selected.connect(self.sample_color)
        left.addLayout(grid, 1)
        self.status = QLabel('准备图片…')
        self.status.setObjectName('status')
        self.status.setWordWrap(True)
        left.addWidget(self.status)
        layout.addLayout(left, 1)
        side = QWidget()
        side.setFixedWidth(350)
        sidebar = QVBoxLayout(side)
        sidebar.setContentsMargins(0, 0, 0, 0)
        sidebar.setSpacing(10)
        sidebar.addWidget(QLabel('预选范围'))
        self.source = QComboBox()
        self.source.addItems(['YOLO 预选（实际推理）', '标注 ROI（对照）'])
        self.source.currentIndexChanged.connect(self.select_source)
        sidebar.addWidget(self.source)
        model_label = QLabel(f'模型：{Path(MODEL_PATH).parent.name}\n置信度：{YOLO_CONF} · bsafe / rsafe')
        model_label.setToolTip(MODEL_PATH)
        model_label.setObjectName('muted')
        sidebar.addWidget(model_label)
        thresholds = QGroupBox('紫色范围 · HSV')
        threshold_layout = QVBoxLayout(thresholds)
        fields = QGridLayout()
        for column, title in enumerate(('H 色相', 'S 饱和度', 'V 亮度'), 1):
            label = QLabel(title)
            label.setAlignment(Qt.AlignCenter)
            fields.addWidget(label, 0, column)
        for row, (bound, title) in enumerate((('min', '最小'), ('max', '最大')), 1):
            fields.addWidget(QLabel(title+' ['), row, 0)
            for column, (name, maximum) in enumerate((('h', 179), ('s', 255), ('v', 255)), 1):
                key = name+'_'+bound
                spin = QSpinBox()
                spin.setRange(0, maximum)
                spin.setValue(self.settings[key])
                spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
                spin.setAlignment(Qt.AlignCenter)
                spin.setKeyboardTracking(False)
                spin.setAccessibleName(f'{title} {name.upper()}')
                spin.valueChanged.connect(self.queue_refresh)
                fields.addWidget(spin, row, column)
                self.controls[key] = spin
            fields.addWidget(QLabel(']'), row, 4)
        threshold_layout.addLayout(fields)
        hint = QLabel('H：0–179　 S / V：0–255\nEnter / Esc 结束编辑，Ctrl+S 保存并退出输入')
        hint.setWordWrap(True)
        hint.setObjectName('muted')
        hint.setToolTip('H最小值大于最大值时，按跨越零点的色相范围处理。')
        threshold_layout.addWidget(hint)
        sidebar.addWidget(thresholds)
        actions = QHBoxLayout()
        save = QPushButton('保存参数  Ctrl+S')
        save.setObjectName('primary')
        reset = QPushButton('恢复默认')
        save.clicked.connect(self.save_settings)
        reset.clicked.connect(self.reset_settings)
        actions.addWidget(save)
        actions.addWidget(reset)
        sidebar.addLayout(actions)
        histogram_group = QGroupBox('Histogram · HSV')
        histogram_layout = QVBoxLayout(histogram_group)
        self.histogram = Histogram()
        histogram_layout.addWidget(self.histogram)
        self.sample_info = QLabel('H 色相：—\nS 饱和度：—\nV 亮度：—')
        self.sample_info.setWordWrap(True)
        self.sample_info.setObjectName('muted')
        histogram_layout.addWidget(self.sample_info)
        apply_sample = QPushButton('应用取色')
        apply_sample.clicked.connect(self.apply_sample)
        histogram_layout.addWidget(apply_sample)
        sidebar.addWidget(histogram_group)
        sidebar.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setFixedWidth(370)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        QApplication.instance().installEventFilter(self)
        if not self.paths:
            self.status.setText(f'没有图片：{IMAGE_DIR}')
            return
        self.load_image()
        self.setFocus()

    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def navigate(self, step):
        self.finish_editing()
        if self.paths and not self.busy():
            self.index = (self.index+step) % len(self.paths)
            self.load_image()

    def load_image(self):
        self.image = read_image(self.paths[self.index])
        kind = '仿真' if 'sim' in self.paths[self.index].name.lower() else '实拍'
        self.filename.setText(f'{self.index+1} / {len(self.paths)}   {kind} · {self.paths[self.index].name}')
        self.views[0].selection = None
        self.sample_pixels = None
        self.histogram.values = None
        self.histogram.clear_hover()
        self.sample_info.setText('H 色相：—\nS 饱和度：—\nV 亮度：—')
        self.select_source()

    def select_source(self):
        if not self.paths:
            return
        if self.source.currentIndex() == 1:
            self.rois = annotation_rois(self.paths[self.index], self.image.shape)
            self.refresh()
        elif self.index in self.cache:
            self.rois = self.cache[self.index]
            self.refresh()
        elif not self.busy():
            self.rois = []
            self.refresh()
            self.status.setText('正在运行 YOLO…首次加载模型需要稍等。')
            self.previous.setEnabled(False)
            self.next.setEnabled(False)
            self.worker = Inference(self.image, self.model)
            self.worker.completed.connect(self.inferred)
            self.worker.failed.connect(self.inference_error)
            self.worker.finished.connect(self.inference_finished)
            self.worker.start()

    def inferred(self, boxes):
        self.model = self.worker.model
        self.cache[self.index] = boxes
        if self.source.currentIndex() == 0:
            self.rois = boxes
            self.refresh()

    def inference_error(self, message):
        self.status.setText('YOLO错误：'+message+'；可切到标注ROI检查颜色。')

    def inference_finished(self):
        self.previous.setEnabled(True)
        self.next.setEnabled(True)

    def queue_refresh(self):
        self.timer.start(60)

    def refresh(self):
        if not self.paths:
            return
        self.settings.update({key: control.value() for key, control in self.controls.items()})
        self.result = segment_safety(self.image, self.rois, self.settings)
        original = self.image.copy()
        for box in self.rois:
            x1, y1, x2, y2 = np.asarray(box).astype(int)
            cv2.rectangle(original, (x1, y1), (x2, y2), (70, 220, 160), 2)
        quads = self.result['quads']
        quad_outline = np.zeros_like(self.image)
        for quad in quads:
            corners = np.rint(quad['points']).astype(np.int32)
            cv2.polylines(quad_outline, [corners], True, (255, 192, 85), 2, cv2.LINE_AA)
        for view, image in zip(self.views[:3], (original, self.result['mask'], quad_outline)):
            view.set_image(image)
        self.views[3].set_image(self.result['quad_image'], ok=self.result['ok'])
        source = 'YOLO' if self.source.currentIndex() == 0 else '标注对照'
        if self.rois:
            visible = '已看全' if self.result['ok'] else '待找全'
            partial = sum(bool(region['hull']) and not region['ok'] for region in self.result['roi_results'])
            complete = sum(quad['ok'] for quad in quads)
            self.status.setText(f'{source}：{len(self.rois)} 个安全区 · {visible} · '
                                f'局部外框 {len(quads)-complete}/{partial} · 完整外框 {complete}')
        else:
            self.status.setText(f'{source}未检出安全区，当前不进行颜色分割。可切换标注ROI对照。')

    def sample_color(self, rect):
        x1, y1, x2, y2 = rect
        self.sample_pixels = cv2.cvtColor(self.image[y1:y2, x1:x2], cv2.COLOR_BGR2HSV).reshape(-1, 3)
        self.histogram.set_pixels(self.sample_pixels)
        low, high = sample_limits(self.sample_pixels)
        hue = f'{low[0]}～179 或 0～{high[0]}' if low[0]>high[0] else f'{low[0]}～{high[0]}'
        self.sample_info.setText(f'H 色相：{hue}\nS 饱和度：{low[1]}～{high[1]}\nV 亮度：{low[2]}～{high[2]}')

    def apply_sample(self):
        if self.sample_pixels is not None:
            self.finish_editing()
            low, high = sample_limits(self.sample_pixels)
            for i, name in enumerate('hsv'):
                self.controls[name+'_min'].setValue(int(low[i]))
                self.controls[name+'_max'].setValue(int(high[i]))

    def save_settings(self):
        self.finish_editing()
        self.timer.stop()
        self.refresh()
        SETTINGS_FILE.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding='utf8')
        self.status.setText('参数已保存：'+str(SETTINGS_FILE))

    def reset_settings(self):
        self.settings = dict(DEFAULTS)
        for key, control in self.controls.items():
            control.setValue(self.settings[key])
        self.refresh()

    def eventFilter(self, watched, event):
        focus = QApplication.focusWidget()
        editor = focus.parentWidget() if isinstance(focus, QLineEdit) else focus
        if event.type() == QEvent.MouseButtonPress and isinstance(watched, QWidget):
            if isinstance(editor, QAbstractSpinBox) and not editor.rect().contains(editor.mapFromGlobal(event.globalPos())):
                self.finish_editing()
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_S and event.modifiers() == Qt.ControlModifier:
                self.save_settings()
                return True
            if isinstance(editor, QAbstractSpinBox) and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
                self.finish_editing()
                return True
            if not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier) and event.key() in (Qt.Key_A, Qt.Key_D):
                self.navigate(-1 if event.key() == Qt.Key_A else 1)
                return True
        return super().eventFilter(watched, event)

    def finish_editing(self):
        """提交输入并把焦点交还窗口，后续按键不再改变数值。"""
        focus = QApplication.focusWidget()
        editor = focus.parentWidget() if isinstance(focus, QLineEdit) else focus
        if isinstance(editor, QAbstractSpinBox):
            editor.interpretText()
            editor.lineEdit().deselect()
        if focus is not None:
            focus.clearFocus()
        self.setFocus(Qt.OtherFocusReason)

    def closeEvent(self, event):
        if self.busy():
            self.status.setText('等待当前图片推理结束后关闭…')
            self.worker.finished.connect(self.close)
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet('''
        QWidget {font-family: "Microsoft YaHei"; font-size: 13px; color: #dae2ee; background: #10151e;}
        QGroupBox {background: #181f2b; border: 1px solid #2c3748; border-radius: 9px; margin-top: 12px; padding: 12px 5px 5px; font-weight: bold;}
        QGroupBox::title {subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #c1cfe4;}
        QLabel {background: transparent;}
        QLabel#muted {color: #96a6bd; font-size: 12px;}
        QLabel#status {color: #a7c6f5; background: #182334; border-radius: 6px; padding: 9px;}
        QPushButton {background: #202c3d; border: 1px solid #34445c; border-radius: 6px; padding: 7px 10px;}
        QPushButton:hover {background: #2b3c54; border-color: #6083b1;}
        QPushButton:pressed {background: #344d6d;}
        QPushButton:disabled {color: #64748b;}
        QPushButton#primary {background: #375d95; border-color: #5079b1; color: #fff;}
        QPushButton#primary:hover {background: #426eab;}
        QSpinBox, QComboBox {background: #0f1724; border: 1px solid #37465c; border-radius: 5px; padding: 6px; min-height: 20px; selection-background-color: #486a9c;}
        QSpinBox:focus, QComboBox:focus {border-color: #8eaff0; background: #1b2a40;}
        QComboBox QAbstractItemView {background: #1c293b; selection-background-color: #375d95;}
        QScrollBar:vertical {background: #10151e; width: 9px;}
        QScrollBar::handle:vertical {background: #40526c; border-radius: 4px; min-height: 28px;}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height: 0;}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {background: #10151e;}
        QToolTip {color: #e5edf8; background: #26354a; border: 1px solid #607594; padding: 6px;}
    ''')
    window = Window()
    window.show()
    QTimer.singleShot(0, window.setFocus)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
