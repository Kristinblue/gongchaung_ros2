"""
只分割本方安全区
取识别之后的box做ROI，还是用红蓝hsv划分吧，并且要做一次开运算，用大核，一边离的比较近以后也能去掉中间物块

之后在图上画出两个区域。
如何区分。应该在各个角度看，都是这个区域的中心x较小的为物资

用线段画出分割的边缘后，在内部用稍微大点的“supplies”“wounded”标识

分割完交给putin调整位置和投放


大概率会有一个问题，被物块遮挡和视角等原因，导致只能看到一个区域，和objs不太一样因为区域在视野中占的范围会比较大。
应该在这里额外加一个目标追踪，只要一开始能够划分两块，根据我们此次拿的物块，就去追踪目标区域，
依旧最近邻补法？丢帧保留，面积相近（从分割出来的区域中取）

"""

import cv2
import numpy as np

from ..my_filter.target_stablizer import TargetStablizer
from .objs import bottom_center


class SafetySplitter:
    """本方安全区ROI内分割两个区域，缺一块时沿用已经确定的身份。"""

    def __init__(self, config=None):
        self.config = config or {}
        self.filter = TargetStablizer(self.config.get('track_gate_px',200),self.config.get('lost_frames',6))
        self.reset()

    def reset(self, keep_confirmation=False, centered_kind=None):
        """新一趟不沿用上一趟或另一视角的区域身份。"""
        self.regions, self.last_target = {}, None
        self.centered_kind = centered_kind
        self.confirmed = keep_confirmation and getattr(self,'confirmed',False)
        self.note = '等待本方安全区的两个分区'
        self.filter.reset()

    def _regions(self, image, safe, team):
        """只在YOLO给出的本方安全区ROI里做HSV和开运算。"""
        height,width = image.shape[:2]
        if safe is None:
            if not self.confirmed:
                return []
            x1,y1,x2,y2 = 0,0,width,height
        else:
            x1,y1,x2,y2 = [int(value) for value in safe['box']]
        x1,y1,x2,y2 = max(0,x1),max(0,y1),min(width,x2),min(height,y2)
        if x2<=x1 or y2<=y1:
            return []
        hsv = cv2.cvtColor(image[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
        ranges = self.config.get('red_hsv',[[[0,60,40],[12,255,255]],[[168,60,40],[179,255,255]]]) if team=='red' else self.config.get('blue_hsv',[[[90,60,40],[135,255,255]]])
        mask = np.zeros(hsv.shape[:2],dtype=np.uint8)
        for low, high in ranges:
            mask |= cv2.inRange(hsv,np.asarray(low,dtype=np.uint8),np.asarray(high,dtype=np.uint8))
        size = max(1,int(self.config.get('open_kernel',9)))
        mask = cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((size,size),dtype=np.uint8))
        contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        result = []
        minimum = mask.size*self.config.get('min_area_ratio',.015)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area<minimum:
                continue
            x,y,w,h = cv2.boundingRect(contour)
            polygon = contour.reshape(-1,2)+[x1,y1]
            result.append({'box':[x+x1,y+y1,x+x1+w,y+y1+h],'center':(x+x1+w/2,y+y1+h/2),'area':area,'polygon':polygon.tolist(),'observed':True})
        return sorted(result,key=lambda obj:obj['area'],reverse=True)[:2]

    def mark_stored(self, image, objs, team):
        """已确认本方安全区后，以当前帧颜色轮廓排除区内物资，避免再捡回来。"""
        regions = self._regions(image,None,team)
        for obj in objs:
            obj['in_safe_zone'] = any(cv2.pointPolygonTest(np.asarray(region['polygon'],dtype=np.float32),bottom_center(obj),False)>=0 for region in regions)

    def observe_regions(self, image, objs, team):
        """在本帧安全区检测框内分区，并标出已经在区域里的物块。"""
        own = {'red':'rsafe','blue':'bsafe'}.get(team)
        safe = next((obj for obj in objs if obj['name']==own and obj.get('observed',True)),None)
        regions = self._regions(image,safe,team) if safe is not None else []
        if len(regions)==2:
            regions.sort(key=lambda region: region['center'][0])
            names = ('supplies','wounded') if self.config.get('supplies_on_left',True) else ('wounded','supplies')
            for region, name in zip(regions,names):
                region['name'] = name
        polygons = [np.asarray(region['polygon'],dtype=np.float32) for region in regions]
        for obj in objs:
            obj['in_safe_zone'] = any(cv2.pointPolygonTest(polygon,bottom_center(obj),False)>=0 for polygon in polygons)
        return regions

    def run(self, image, safe, team, kind='supplies'):
        """返回本次要投放的区域；保留的旧位置标为observed=False。"""
        # 已由YOLO确认本方安全区后，近处大面积裁边漏检时继续跟踪当前图像颜色。
        # 未确认前仍必须有YOLO的ROI，不把任何红/蓝色物块当作安全区。
        if safe is not None and safe.get('observed',True):
            self.confirmed = True
        candidates = self._regions(image,safe,team)
        if len(candidates)==2:
            left,right = sorted(candidates,key=lambda obj:obj['center'][0])
            if self.config.get('supplies_on_left',True):
                self.regions = {'supplies':left,'wounded':right}
            else:
                self.regions = {'supplies':right,'wounded':left}
            target = self.regions[kind]
        elif len(candidates)==1 and not self.regions and self.centered_kind==kind and candidates[0]['box'][0]<=image.shape[1]/2<=candidates[0]['box'][2]:
            # 已对准后仅直推/后退，换俯角只清坐标；居中的单个分区仍沿用已确认的身份。
            target = candidates[0]
        elif len(candidates)==1 and self.regions:
            candidate = candidates[0]
            nearest = min(self.regions,key=lambda name:np.linalg.norm(np.asarray(candidate['center'])-self.regions[name]['center']))
            previous = self.regions[nearest]
            ratio = candidate['area']/max(1.,previous['area'])
            distance = np.linalg.norm(np.asarray(candidate['center'])-previous['center'])
            target = candidate if nearest==kind and .3<=ratio<=3 and distance<=self.config.get('track_gate_px',200) else None
        else:
            target = None
        if target is not None:
            x1,y1,x2,y2 = target['box']
            stable = self.filter.update((x1,y1,x2,y2,*target['center']))
            if stable is not None and tuple(stable[:4])==(x1,y1,x2,y2):
                self.last_target = dict(target,name=kind)
                self.regions[kind] = target
                self.note = '目标投放区已确认'
                return self.last_target
        else:
            stable = self.filter.update(None)
        self.note = '投放区暂时丢失，保留位置但停车等待新分割'
        if stable is not None and self.last_target is not None:
            return dict(self.last_target,observed=False)
        self.last_target = None
        self.regions = {}
        return None
