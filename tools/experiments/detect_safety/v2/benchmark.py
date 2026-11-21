"""复跑安全区检测，记录整帧识别耗时和分类结果。"""

import csv
import json
from pathlib import Path
from time import perf_counter

import cv2
import matplotlib
import numpy as np

from segment import SafetyDetector

matplotlib.use('Agg')
from matplotlib import pyplot as plt
from matplotlib.font_manager import FontProperties


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'reports' / 'v2' / 'color'
REPEATS = 20
LABELS = {'bsafe': 'b_safety', 'rsafe': 'r_safety'}
EXAMPLES = ('frame_0355', 'frame_0684', 'frame_0973', 'frame_1230',
            'sim_safe_far_bsafe_20261022_03', 'sim_safe_far_rsafe_20261022_09')


def result_figure(examples):
    """展示补测原图、紫色掩膜、红蓝掩膜和多边形。"""
    fig, axes = plt.subplots(len(examples), 4, figsize=(13, 2 * len(examples)), squeeze=False, layout='constrained')
    for row, (name, image, result, truth) in enumerate(examples):
        purple, colors, overlay = result.draw_result(image)
        original = image.copy()
        if result.roi is not None:
            x1, y1, x2, y2 = result.roi
            cv2.rectangle(original, (x1, y1), (x2 - 1, y2 - 1), (70, 220, 160), 2)
        flag = result.flag if result.status['detected'] else '—'
        titles = (name.replace('sim_safe_far_', 'sim_far_').replace('_20261022', ''), '紫色掩膜', '红蓝掩膜',
                  f'{truth} → {flag} · full={result.status["full"]}')
        for axis, frame, title in zip(axes[row], (original, purple, colors, overlay), titles):
            if frame.ndim == 2:
                axis.imshow(frame, cmap='gray', vmin=0, vmax=255)
            else:
                axis.imshow(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            axis.set_title(title, fontsize=9)
            axis.set_axis_off()
    fig.savefig(OUTPUT / 'examples-extra.jpg', dpi=150)
    plt.close(fig)


def main():
    """预读图像并预热后，测量每帧的识别总耗时。"""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    detector = SafetyDetector(json.loads(Path(__file__).with_name('settings.json').read_text(encoding='utf-8')))
    frames = []
    examples = {}
    with (OUTPUT / 'classifications.csv').open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(['group', 'image', 'label', 'result', 'detected', 'full', 'ok', 'red_fraction', 'blue_fraction', 'purple_fraction'])
        for group in ('first', 'extra'):
            for path in sorted((ROOT / 'assets' / group).glob('*.jpg')):
                label_path = path.with_suffix('.json')
                if not label_path.is_file():
                    continue
                shapes = json.loads(label_path.read_text(encoding='utf-8-sig'))['shapes']
                sides = {shape['label'] for shape in shapes} & LABELS.keys()
                if len(sides) != 1:
                    continue
                truth = LABELS[sides.pop()]
                image = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
                frames.append(image)
                result = detector.detect(image)
                status = result.status
                flag = result.flag if status['detected'] else None
                writer.writerow([group, path.stem, truth, flag, status['detected'], status['full'], status['ok'],
                                 result.red_fraction, result.blue_fraction, result.purple_fraction])
                if path.stem in EXAMPLES:
                    examples[path.stem] = path.stem, image, result, truth

    elapsed = []
    for _ in range(REPEATS):
        for image in frames:
            start = perf_counter()
            detector.detect(image)
            elapsed.append((perf_counter() - start) * 1000)

    median, p95 = np.percentile(elapsed, [50, 95])
    with (OUTPUT / 'timing.csv').open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(['frames', 'repeats', 'median_ms', 'p95_ms'])
        writer.writerow([len(frames), REPEATS, round(median, 4), round(p95, 4)])
    print(f'{len(frames)} frames x {REPEATS} | OpenCV {cv2.__version__} | threads={cv2.getNumThreads()}')
    print(f'Total per frame: median {median:.2f} ms, P95 {p95:.2f} ms')
    if examples:
        plt.rcParams['font.family'] = FontProperties(fname=r'C:\Windows\Fonts\msyh.ttc').get_name()
        result_figure([examples[name] for name in EXAMPLES if name in examples])


if __name__ == '__main__':
    main()
