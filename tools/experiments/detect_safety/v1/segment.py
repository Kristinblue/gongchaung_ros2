"""安全区颜色分割和四边形拟合，只接收图像和预选ROI。"""

import cv2
import numpy as np


GAUSSIAN_KERNEL_SIZE = 3
OPEN_KERNEL_SIZE = 3
FRAME_EDGE_MARGIN = 3

DEFAULTS = {
    'h_min':125, 'h_max':155,
    's_min':100, 's_max':255,
    'v_min':25, 'v_max':255,
}


def hsv_mask(hsv, limits):
    """按一组HSV阈值生成掩膜，H使用0～179，允许跨越色相零点。"""
    low = (limits['h_min'],limits['s_min'],limits['v_min'])
    high = (limits['h_max'],limits['s_max'],limits['v_max'])
    if low[0]<=high[0]:
        return cv2.inRange(hsv,low,high)
    first = cv2.inRange(hsv,(0,low[1],low[2]),high)
    second = cv2.inRange(hsv,low,(179,high[1],high[2]))
    return cv2.bitwise_or(first,second)


def purple_mask(image, settings):
    """平滑原图后用一组HSV阈值分割，随后做开运算去噪。"""
    smoothed = cv2.GaussianBlur(image,(GAUSSIAN_KERNEL_SIZE,GAUSSIAN_KERNEL_SIZE),0)
    hsv = cv2.cvtColor(smoothed,cv2.COLOR_BGR2HSV)
    mask = hsv_mask(hsv,settings)
    open_kernel = np.ones((OPEN_KERNEL_SIZE, OPEN_KERNEL_SIZE), np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel)


def fit_outer_quad(mask):
    """用掩膜中各白块的外轮廓拟合一个外接四边形。"""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, None

    hull = cv2.convexHull(np.concatenate(contours))
    if len(hull) < 4:
        return hull, None
    # 只允许外接面积增加25%，避免把不规则轮廓强行拉成四边形。
    quad = hull.astype(np.float32) if len(hull) == 4 else cv2.approxPolyN(
        hull.astype(np.float32), 4, epsilon_percentage=.25, ensure_convex=False)
    quad = quad.reshape(-1, 2)
    if len(quad) != 4 or not cv2.isContourConvex(quad):
        return hull, None
    if any(cv2.pointPolygonTest(quad, tuple(map(float, point)), True) < -.01 for point in hull[:, 0]):
        return hull, None
    return hull, quad


def segment_safety(image, rois, settings=None):
    """分割YOLO预选安全区，在各个ROI内独立拟合四边形。

    Args:
        image: 原始BGR图像，不修改输入。
        rois: 全图坐标的[x1,y1,x2,y2]列表；空列表不检测。
        settings: 覆盖DEFAULTS的阈值和比例参数。

    Returns:
        二值图、叠加四边形的预览和四边形全图坐标。
        roi_results 中的 ok 表示该 ROI 有可见掩膜，且掩膜未贴原图边缘。
        center 是拟合四边形四个角的平均位置，无四边形时为 None。hull 和 center 均使用全图坐标。
        整帧 ok 要求至少有一个 ROI，且全部 ROI 都看全。quads 保留所有成功的拟合，
        包括局部可见目标和外推到画面外的角点。投放对准前需检查对应目标的 ok。
    """
    config = dict(DEFAULTS)
    if settings is not None:
        config.update(settings)
    height,width = image.shape[:2]
    mask = np.zeros((height,width),np.uint8)
    quad_image = image.copy()
    quads = []
    roi_results = []
    for index, roi in enumerate(rois):
        x1,y1,x2,y2 = np.rint(roi).astype(int)
        x1,y1,x2,y2 = max(0,x1),max(0,y1),min(width,x2),min(height,y2)
        region = {'roi': [x1,y1,x2,y2], 'ok': False, 'center': None, 'hull': []}
        roi_results.append(region)
        if x2-x1<5 or y2-y1<5:
            continue
        local = purple_mask(image[y1:y2,x1:x2],config)
        mask[y1:y2,x1:x2] |= local
        left, top, box_width, box_height = cv2.boundingRect(local)
        if not box_width or not box_height:
            continue
        # 用整张画面的坐标判断，ROI 自身的边界不算出画。
        left, top = x1 + left, y1 + top
        margin = min(left, top, width - (left + box_width), height - (top + box_height))
        region['ok'] = bool(margin >= FRAME_EDGE_MARGIN)
        hull, quad = fit_outer_quad(local)
        hull = (hull + (x1, y1)).reshape(-1, 2).astype(np.int32)
        region['hull'] = hull.tolist()
        if quad is not None:
            quad = quad + np.array([x1, y1], dtype=np.float32)
            region['center'] = quad.mean(axis=0).tolist()
            quads.append({'points':quad.tolist(), 'roi_index':index, 'ok':region['ok']})
            color = (0, 220, 255) if region['ok'] else (0, 130, 255)
            cv2.polylines(quad_image, [np.rint(quad).astype(np.int32)], True, color, 2, cv2.LINE_AA)
            if not region['ok']:
                center = tuple(np.rint(region['center']).astype(int))
                cv2.drawMarker(quad_image, center, color, cv2.MARKER_CROSS, 14, 2, cv2.LINE_AA)
    ok = bool(roi_results) and all(region['ok'] for region in roi_results)
    return {'ok':ok,'roi_results':roi_results,'mask':mask,'quad_image':quad_image,'quads':quads}
