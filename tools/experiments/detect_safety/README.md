---
date created: 2026-11-14  13：55
date modified: 2026-11-14  15：52
---
# 安全区外框算法迭代


`reports/` 存放测速、掩膜对照、截图和复测数据。v1 与 v2 的窗口共用 `assets/first` 里的原有样图。
还没完善好.大概效果这样。
![[file-20261114155155102.png]]

抗光照干扰效果非常不错！

v1 流程为 YOLO 预选 → 3×3 高斯模糊 → 单组 HSV 掩膜 → 3×3 开运算 → `findContours` → 凸包 → `approxPolyN` 外接四边形。暖光造成的部分断口由凸包跨过。

- **霍夫直线 → 凸包。** 霍夫容易产生断线和重线，需要再合并。对同一 ROI 的所有外轮廓点一起求凸包，直接跨过白块间的断口。`approxPolyN` 可以指定四边并外包凸包。`approxPolyDP` 用距离容差控制简化，边数会变，也可能切掉凸包。
- **淘汰 `findNonZero`。** 两种取点方式得到相同凸包。48 张图的点数中位数由 58,586 降到 882，取点到拟合耗时从 13.44 降到 0.37 ms/ROI（OpenCV 单线程）。[测速记录](reports/opening_comparison/benchmark.json)
- **开运算用 3×3 方核。** 对照实验中，小于 20 像素的白块从 180 减到 41。5×5 会额外削掉一些细栏杆。[开运算对照](reports/opening_comparison/mask_comparison.jpg)
- **去掉闭运算。** 同一批 48 个 ROI，有无 7×7 闭运算都得到 48 个四边形。两组外框的 IoU 中位数为 99.91%，最低 91.88%。凸包本身能跨断口，因此默认只做开运算。这组数据衡量两种结果的差异，外框准确率需要角点标注验证。[闭运算对照](reports/closing_comparison/quad_comparison.jpg)

- **统一使用四边形。** 48 张复测均得到四边形，其中 37 张局部可见、11 张已看全。`ok` 由掩膜是否贴原图最外 3 像素决定。拟合角点可以延伸到画面外，返回坐标保留原值。[用户圈注截图](reports/closing_comparison/incomplete_safety_examples.png) · [效果对照](reports/frame_edge_check/comparison.jpg) · [复测记录](reports/frame_edge_check/results.json)
