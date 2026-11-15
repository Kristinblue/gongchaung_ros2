"""

把检测出的物体再封装一下。
一个是这里我们做最近邻补法，并一直保留一个列表，存放看到的物体，需要搭配target_stablizer
这个列表相当于是记忆，各种物块以及它的标号，稳定器里面做了销毁处理。
物体记录的信息是：种类、编号（同类重复）、检测狂的box

"""

import math

from ..my_filter.target_stablizer import TargetStablizer


def bottom_center(obj):
    """返回检测框底边中心，坐标为当前图像像素。"""
    x1, _, x2, y2 = obj['box']
    return (x1+x2)/2, y2


def pixel_distance(first, second):
    """计算两个物体底边中心的距离。"""
    return math.dist(bottom_center(first),bottom_center(second))


def nearest_same_kind(target, objs, max_dist=150):
    """在当前可见的同类物体中找最近邻。"""
    candidates = [obj for obj in objs if obj['name']==target['name'] and obj.get('observed',True)]
    nearest = min(candidates,key=lambda obj:pixel_distance(target,obj),default=None)
    return nearest if nearest is not None and pixel_distance(target,nearest)<=max_dist else None


def make_target(box, class_id, name, score=1.):
    """把一次真实检测整理成后续模块共用的字典。"""
    return {'box':[float(value) for value in box],'class_id':int(class_id),'name':name,'score':float(score),'observed':True}


def to_targets(boxes, classes, scores, labels):
    """转换YOLO结果；不补造物体，不接受非法坐标。"""
    targets = []
    for box, kind, score in zip(boxes,classes,scores):
        kind = int(kind)
        if not 0<=kind<len(labels) or len(box)!=4 or not all(math.isfinite(float(value)) for value in box):
            continue
        if box[2]>box[0] and box[3]>box[1]:
            targets.append(make_target(box,kind,labels[kind],score))
    return targets


class Objs:
    """同类最近邻编号，复用原稳定器保留短暂丢失的物体。"""

    def __init__(self, width=1280, height=720, max_dist=150, lost_frames=6, edge_margin=8):
        self.width, self.height = width, height
        self.max_dist, self.lost_frames, self.edge_margin = max_dist, lost_frames, edge_margin
        self.reset()

    def update(self, detections):
        """更新物体列表；observed=False只用于记忆，不作为落框确认。"""
        current, used = [], set()
        for obj in detections:
            candidates = [old for old in self.objects if old['name']==obj['name'] and (old['name'],old['id']) not in used]
            nearest = min(candidates,key=lambda old:pixel_distance(old,obj),default=None)
            if nearest is not None and pixel_distance(nearest,obj)<=self.max_dist:
                number = nearest['id']
            else:
                number = self.numbers.get(obj['name'],0)+1
                self.numbers[obj['name']] = number
            key = obj['name'], number
            used.add(key)
            item = dict(obj,id=number,observed=True)
            stable = self.filters.setdefault(key,TargetStablizer(self.max_dist,self.lost_frames))
            x1,y1,x2,y2 = item['box']
            stable.update((x1,y1,x2,y2,(x1+x2)/2,(y1+y2)/2))
            current.append(item)
        for old in self.objects:
            key = old['name'], old['id']
            if key in used:
                continue
            x1,y1,x2,y2 = old['box']
            edge = x1<=self.edge_margin or y1<=self.edge_margin or x2>=self.width-self.edge_margin or y2>=self.height-self.edge_margin
            if not edge and self.filters[key].update(None) is not None:
                current.append(dict(old,observed=False))
        alive = {(obj['name'],obj['id']) for obj in current}
        self.filters = {key:value for key,value in self.filters.items() if key in alive}
        self.objects = current
        return current

    def reset(self):
        """换视角或重新开始时清空像素记忆，编号不跨相机视角关联。"""
        self.objects, self.filters, self.numbers = [], {}, {}
