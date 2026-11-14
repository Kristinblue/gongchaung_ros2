"""瑞芯微 YOLOv8 示例的前后处理，输入和结果都是 NumPy 数组。

参照的官方例程
来源：https://github.com/airockchip/rknn_model_zoo/blob/main/examples/yolov8/python/yolov8.py
按官方的筛选、非极大值抑制、分布解码和三分支后处理组织。

"""

import cv2
import numpy as np


def preprocess(image, input_size=(640, 640), pad_color=(114, 114, 114)):
    """前处理letterbox
    保持比例缩放、补边，并将 BGR 转为带批次维度的 RGB。
    Args:
        image: 原始 BGR 图像，形状为 (高, 宽, 3)，类型为 uint8。
        input_size: 模型输入的 (宽, 高)，必须与模型转换时的尺寸一致。
        pad_color: 补边颜色，默认保持当前模型使用的灰色。

    Returns:
        tuple: (模型输入数组, 缩放比例, (左侧补边, 上侧补边))。
    """
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8:
        raise TypeError("[YOLOv8] 输入必须是 uint8 NumPy 数组")
    if image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) <= 0:
        raise ValueError("[YOLOv8] 输入必须是非空三通道图像")
    width, height = input_size
    if min(width, height) <= 0:
        raise ValueError("[YOLOv8] 模型输入尺寸必须大于 0")
    original_h, original_w = image.shape[:2]
    ratio = min(width / original_w, height / original_h)
    resized_w, resized_h = max(1, round(original_w * ratio)), max(1, round(original_h * ratio))
    left, top = (width - resized_w) // 2, (height - resized_h) // 2
    resized = cv2.resize(image, (resized_w, resized_h))
    padded = cv2.copyMakeBorder(resized, top, height - resized_h - top, left, width - resized_w - left, cv2.BORDER_CONSTANT, value=pad_color)
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    return rgb[None, ...], ratio, (left, top)


def filter_boxes(boxes, box_confidences, box_class_probs, conf):
    """根据类别最高分和置信度阈值筛选框。"""
    scores = np.max(box_class_probs, axis=-1) * box_confidences.reshape(-1)
    classes = np.argmax(box_class_probs, axis=-1)
    keep = scores >= conf
    return boxes[keep], classes[keep], scores[keep]


def nms_boxes(boxes, scores, iou):
    """保留高分框，抑制同一类别中重复的重叠框。"""
    x1, y1, x2, y2 = boxes.T
    areas = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        index = order[0]
        keep.append(index)
        others = order[1:]
        width = np.maximum(0, np.minimum(x2[index], x2[others]) - np.maximum(x1[index], x1[others]))
        height = np.maximum(0, np.minimum(y2[index], y2[others]) - np.maximum(y1[index], y1[others]))
        intersection = width * height
        overlap = intersection / np.maximum(areas[index] + areas[others] - intersection, 1e-9)
        order = others[overlap <= iou]
    return np.asarray(keep, dtype=np.int64)


def dfl(position):
    """把四条边的距离分布，通过归一化指数和期望转换为实际距离。"""
    batch, channels, height, width = position.shape
    bins = channels // 4
    values = position.reshape(batch, 4, bins, height, width).astype(np.float32)
    probabilities = np.exp(values - values.max(axis=2, keepdims=True))
    probabilities /= probabilities.sum(axis=2, keepdims=True)
    return (probabilities * np.arange(bins, dtype=np.float32)[None, None, :, None, None]).sum(axis=2)


def box_process(position, input_size):
    """将一个尺度的框分布解码成模型输入坐标下的四个边界。"""
    grid_h, grid_w = position.shape[2:]
    grid_x, grid_y = np.meshgrid(np.arange(grid_w), np.arange(grid_h))
    grid = np.stack((grid_x, grid_y))[None, ...]
    stride = np.asarray([input_size[0] / grid_w, input_size[1] / grid_h]).reshape(1, 2, 1, 1)
    distances = dfl(position)
    top_left = (grid + 0.5 - distances[:, :2]) * stride
    bottom_right = (grid + 0.5 + distances[:, 2:]) * stride
    return np.concatenate((top_left, bottom_right), axis=1)


def post_process(outputs, input_size=(640, 640), conf=0.25, iou=0.45):
    """解码三个尺度的输出，筛选分数并按类别去除重复框。

    Args:
        outputs: 瑞芯微优化模型的 6 或 9 个输出，布局为 (批次, 通道, 高, 宽)。
        input_size: 模型输入的 (宽, 高)。
        conf: 最低置信度，范围 0~1。
        iou: 非极大值抑制阈值，范围 0~1。

    Returns:
        tuple: (boxes, classes, scores)。框为 (目标数, 4) 的左上角、右下角坐标，
            仍相对于模型输入；类别和分数各为 (目标数,)。无目标时返回空数组。

    Raises:
        ValueError: 模型输出布局或阈值不正确。
    """
    if outputs is None or len(outputs) not in (6, 9):
        raise ValueError("[YOLOv8] 需要瑞芯微三分支模型的 6 或 9 个输出")
    if not 0 <= conf <= 1 or not 0 <= iou <= 1:
        raise ValueError("[YOLOv8] 阈值必须在 0~1 之间")
    boxes, class_probs = [], []
    branch_size = len(outputs) // 3
    for start in range(0, len(outputs), branch_size):
        position = np.asarray(outputs[start])
        classes = np.asarray(outputs[start + 1])
        if position.ndim != 4 or position.shape[0] != 1 or position.shape[1] % 4 or min(position.shape[1:]) <= 0:
            raise ValueError("[YOLOv8] 框分布必须是单批次、通道数为 4 的倍数的四维数组")
        if classes.ndim != 4 or classes.shape[0] != 1 or classes.shape[1] == 0 or classes.shape[2:] != position.shape[2:]:
            raise ValueError("[YOLOv8] 类别输出的网格尺寸必须与框分布一致")
        # 第三个输出是类别分数总和，官方 Python 示例不使用它。
        decoded = box_process(position, input_size)
        boxes.append(decoded.transpose(0, 2, 3, 1).reshape(-1, 4))
        class_probs.append(classes.transpose(0, 2, 3, 1).reshape(-1, classes.shape[1]))
    boxes = np.concatenate(boxes).astype(np.float32)
    class_probs = np.concatenate(class_probs)
    boxes, classes, scores = filter_boxes(boxes, np.ones(len(boxes)), class_probs, conf)
    keep = []
    for class_id in np.unique(classes):
        indices = np.flatnonzero(classes == class_id)
        keep.extend(indices[nms_boxes(boxes[indices], scores[indices], iou)])
    keep = np.asarray(keep, dtype=np.int64)
    keep = keep[np.argsort(scores[keep])[::-1]]
    return boxes[keep], classes[keep], scores[keep].astype(np.float32)


class YOLOv8:
    """同步调用瑞芯微模型，图像和检测结果都使用 NumPy 数组。"""

    def __init__(self, model_path, input_size=(640, 640), pad_color=(114, 114, 114)):
        """加载模型并初始化 NPU，整个使用过程只需初始化一次。

        Args:
            model_path: 已转换的 .rknn 模型文件路径。
            input_size: 模型输入的 (宽, 高)，需与模型转换配置一致。
            pad_color: 缩放后补边的颜色，默认灰色。

        Raises:
            ValueError: 模型输入尺寸不正确。
            RuntimeError: 模型加载或 NPU 初始化失败。
        """
        self.input_size = tuple(input_size)
        if len(self.input_size) != 2 or any(not isinstance(size, int) or size <= 0 for size in self.input_size):
            raise ValueError("[YOLOv8] 输入尺寸必须是两个正整数，顺序为宽、高")
        self.pad_color = pad_color

        from rknnlite.api import RKNNLite

        self._model = RKNNLite()
        try:
            ret = self._model.load_rknn(str(model_path))
            if ret != 0:
                raise RuntimeError(f"[YOLOv8] 模型加载失败: {ret}")
            ret = self._model.init_runtime(core_mask=RKNNLite.NPU_CORE_0_1_2)
            if ret != 0:
                raise RuntimeError(f"[YOLOv8] NPU 初始化失败: {ret}")
        except Exception:
            self.close()
            raise

    def predict(self, image, conf=0.25, iou=0.45):
        """同步完成前处理、推理、后处理和坐标还原，不修改输入图像。

        Args:
            image: 一张 uint8 BGR NumPy 图像，也可以是 ROI 切片。
            conf: 最低置信度，范围 0~1。
            iou: 非极大值抑制阈值，范围 0~1。

        Returns:
            tuple: (boxes, classes, scores)。框为 (目标数, 4) 的数组，
                每行是输入图像上的 [x1, y1, x2, y2]；类别和分数各为
                (目标数,) 的数组。无目标时返回三个空数组。

        Raises:
            RuntimeError: 模型已经关闭。
            ValueError: 阈值或模型输出布局不正确。
        """
        if self._model is None:
            raise RuntimeError("[YOLOv8] 模型已经关闭")
        if not 0 <= conf <= 1 or not 0 <= iou <= 1:
            raise ValueError("[YOLOv8] 阈值必须在 0~1 之间")
        model_input, ratio, padding = preprocess(image, self.input_size, self.pad_color)
        outputs = self._model.inference(inputs=[model_input])
        boxes, classes, scores = post_process(outputs, self.input_size, conf, iou)

        # 减去补边、除以缩放比例，把所有框一起还原到传入图像的坐标。
        boxes -= np.asarray([padding[0], padding[1], padding[0], padding[1]])
        boxes /= ratio
        boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0, image.shape[1] - 1)
        boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0, image.shape[0] - 1)
        return boxes, classes, scores

    def close(self):
        """释放 RKNNLite 资源，可重复调用。"""
        if self._model is not None:
            self._model.release()
            self._model = None
