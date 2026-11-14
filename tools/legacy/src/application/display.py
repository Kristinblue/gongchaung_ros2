"""摄像头处理画面，两端共用，只读取算法结果，不参与控制。"""

import cv2
import numpy as np


def draw_frame(image, task, draw_boundary=True):
    """返回叠加检测结果的画面副本，原图继续用于算法处理。"""
    frame = image.copy()
    if draw_boundary:
        draw_background(frame,task.detect.background_filter)
    boxes, classes, scores = task.detect.detections
    colors = {'green':(65,190,80),'orange':(0,145,255),'blue':(255,190,90),'black':(160,100,230),'bsafe':(255,140,50),'rsafe':(60,70,235)}
    for box, class_id, score in zip(boxes,classes,scores):
        name = task.detect.labels[int(class_id)]
        color = colors.get(name,(0,220,220))
        x1,y1,x2,y2 = [int(value) for value in box]
        cv2.rectangle(frame,(x1,y1),(x2,y2),color,2)
        cv2.putText(frame,f'{name} {score:.2f}',(x1,max(18,y1-6)),cv2.FONT_HERSHEY_SIMPLEX,.6,color,2,cv2.LINE_AA)
    cv2.drawMarker(frame,(int(task.x0),int(task.y0)),(40,50,240),cv2.MARKER_CROSS,22,2)
    status = task.status()
    stage = status['stage']
    if status['goto_stage']:
        stage += f" {status['goto_stage']} {task.state}"
    draw_target(frame,task)
    actual = task._feedback.get('camera_deg')
    angle = task.camera_deg if actual is None else actual
    lines = [stage,f'cam_angle: {angle:.1f}']
    for row,text in enumerate(lines):
        cv2.putText(frame,text,(12,25+25*row),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,0),3,cv2.LINE_AA)
        cv2.putText(frame,text,(12,25+25*row),cv2.FONT_HERSHEY_SIMPLEX,.6,(30,210,250),1,cv2.LINE_AA)
    return frame


def draw_target(image, task):
    """只标注S2当前帧已确认的最终目标，不把S1候选或旧目标当结果。"""
    if task.state!='track' or not task.go_to.view_ready(task._now):
        return
    goto = task.go_to
    target = goto.rank2_target
    if target is None or not target.get('observed',True) or goto.rank2_hits<goto.config.get('confirm_frames',3):
        return
    height,width = image.shape[:2]
    x1,y1,x2,y2 = np.asarray(target['box'],dtype=int)
    x1,x2 = np.clip([x1,x2],0,width-1)
    y1,y2 = np.clip([y1,y2],0,height-1)
    color = (0,255,255)
    cv2.rectangle(image,(x1,y1),(x2,y2),color,3,cv2.LINE_AA)
    cv2.putText(image,'target',(x1+5,min(height-5,y1+23)),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,0,0),4,cv2.LINE_AA)
    cv2.putText(image,'target',(x1+5,min(height-5,y1+23)),cv2.FONT_HERSHEY_SIMPLEX,.7,color,2,cv2.LINE_AA)


def draw_background(image, background_filter):
    """画当前帧的水平过滤线，不修改算法结果。"""
    row = background_filter.last['cutoff_y']
    if not background_filter.enabled or row is None:
        return
    height,width = image.shape[:2]
    y = max(0,min(height-1,int(round(row))))
    color = (0,210,255)
    cv2.line(image,(0,y),(width-1,y),color,2,cv2.LINE_AA)
