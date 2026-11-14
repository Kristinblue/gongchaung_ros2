"""在电脑上用 onnxruntime 跑 YOLOv8，接口与 ``utils.yolov8.YOLOv8`` 完全一致。

为什么要这个类：
    派上用 RKNN（``utils/yolov8.py``），电脑上没有 ``rknnlite``，但两者的
    输入输出格式一模一样——``predict(image) -> (boxes, classes, scores)``，
    而且框已经还原到传入图像的坐标。所以上层业务代码只认这个接口，
    换检测器时一行都不用改。

前处理和 NMS 直接复用 ``utils/yolov8.py``，不重复实现。
"""

import ast

import numpy as np

from .yolov8 import nms_boxes, preprocess


class YOLOv8Onnx:
    """同步调用 onnx 模型，图像和检测结果都使用 NumPy 数组。"""

    def __init__(self, model_path, input_size=(640, 640), pad_color=(114, 114, 114), providers=None, cpu_threads=2):
        """加载 onnx 模型并读取内嵌的类别名。

        Args:
            model_path: ``.onnx`` 模型路径。
            input_size: 模型输入的 (宽, 高)，需与导出时一致。
            pad_color: letterbox 补边颜色，默认灰色。
            providers: onnxruntime 执行后端，默认 CPU。
            cpu_threads: CPU推理线程数，避免与物理后台争抢所有核心；0为自动。

        Raises:
            ValueError: 输入尺寸不正确。
            FileNotFoundError: 模型文件不存在。
        """
        self.input_size = tuple(input_size)
        if len(self.input_size) != 2 or any(not isinstance(size, int) or size <= 0 for size in self.input_size):
            raise ValueError("[YOLOv8Onnx] 输入尺寸必须是两个正整数，顺序为宽、高")
        self.pad_color = pad_color
        self.model_path = str(model_path)

        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = int(cpu_threads)
        options.inter_op_num_threads = 1
        options.add_session_config_entry('session.intra_op.allow_spinning','0')
        self._session = ort.InferenceSession(self.model_path, sess_options=options, providers=providers or ['CPUExecutionProvider'])
        self._input_name = self._session.get_inputs()[0].name
        self.labels = self._read_labels(self._session)

    @staticmethod
    def _read_labels(session) -> list:
        """从模型 metadata 里读出类别名，读不到时回退到按索引编号。

        Args:
            session: onnxruntime 的 InferenceSession。

        Returns:
            类别名列表。
        """
        raw = session.get_modelmeta().custom_metadata_map.get('names', '')
        labels = []
        if raw:
            try:
                parsed = ast.literal_eval(raw)
                if isinstance(parsed, dict):
                    labels = [str(parsed[key]) for key in sorted(parsed)]
            except (ValueError, SyntaxError):
                labels = [part.strip() for part in str(raw).split(',') if part.strip()]
        if not labels:
            shape = session.get_outputs()[0].shape
            count = max(1, int(shape[1]) - 4) if len(shape) == 3 and isinstance(shape[1], int) else 1
            labels = [f'class_{index}' for index in range(count)]
        return labels

    def predict(self, image, conf=0.25, iou=0.45):
        """同步完成前处理、推理、NMS 和坐标还原，不修改输入图像。

        Args:
            image: 一张 uint8 BGR NumPy 图像，也可以是 ROI 切片。
            conf: 最低置信度，范围 0~1。
            iou: 非极大值抑制阈值，范围 0~1。

        Returns:
            tuple: (boxes, classes, scores)。框为 (目标数, 4) 的数组，
                每行是输入图像上的 [x1, y1, x2, y2]；类别和分数各为 (目标数,)。
                无目标时返回三个空数组。

        Raises:
            ValueError: 阈值不正确。
        """
        if not 0 <= conf <= 1 or not 0 <= iou <= 1:
            raise ValueError("[YOLOv8Onnx] 阈值必须在 0~1 之间")

        model_input, ratio, padding = preprocess(image, self.input_size, self.pad_color)
        # preprocess 给的是 (1, 高, 宽, 3) 的 RGB uint8，onnx 要 (1, 3, 高, 宽) 的 0~1 浮点。
        blob = model_input.transpose(0, 3, 1, 2).astype(np.float32) / 255.0
        prediction = self._session.run(None, {self._input_name: blob})[0]
        # 导出形状是 (1, 4 + 类别数, 框数)，转成“每个框一行”更好筛。
        rows = np.asarray(prediction)[0].T

        centers = rows[:, :4]
        class_scores = rows[:, 4:]
        classes = class_scores.argmax(axis=1)
        scores = class_scores.max(axis=1)
        keep = scores >= conf
        if not np.any(keep):
            empty_boxes = np.zeros((0, 4), dtype=np.float32)
            return empty_boxes, np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float32)

        centers, classes, scores = centers[keep], classes[keep], scores[keep]

        # cx, cy, w, h 转成左上角、右下角。
        boxes = np.empty_like(centers)
        boxes[:, 0] = centers[:, 0] - centers[:, 2] / 2
        boxes[:, 1] = centers[:, 1] - centers[:, 3] / 2
        boxes[:, 2] = centers[:, 0] + centers[:, 2] / 2
        boxes[:, 3] = centers[:, 1] + centers[:, 3] / 2

        # 与 rknn 版一致：按类别分别做 NMS，再按分数从高到低排序。
        indices = []
        for class_id in np.unique(classes):
            picked = np.flatnonzero(classes == class_id)
            indices.extend(picked[nms_boxes(boxes[picked], scores[picked], iou)])
        indices = np.asarray(indices, dtype=np.int64)
        indices = indices[np.argsort(scores[indices])[::-1]]
        boxes, classes, scores = boxes[indices], classes[indices], scores[indices]

        # 减去补边、除以缩放比例，还原到传入图像的坐标。
        boxes = boxes - np.asarray([padding[0], padding[1], padding[0], padding[1]])
        boxes = boxes / ratio
        boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0, image.shape[1] - 1)
        boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0, image.shape[0] - 1)
        return boxes.astype(np.float32), classes.astype(np.int64), scores.astype(np.float32)

    def name_of(self, class_id: int) -> str:
        """把类别编号换成名字，越界时返回 ``class_编号``。

        Args:
            class_id: 类别编号。

        Returns:
            类别名。
        """
        if 0 <= class_id < len(self.labels):
            return self.labels[class_id]
        return f'class_{class_id}'

    def close(self):
        """释放推理会话，可重复调用。"""
        self._session = None
