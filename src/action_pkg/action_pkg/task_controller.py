"""
这里负责整体的逻辑框架,以及各种类的构建让main看起来清爽，或者包一些别的
"""

import time

from .init_dis import InitDisributor
from .grab.go_to import GoTo

STOP = 'stop'


class Task:
    """逐帧调度出发、搜寻与追踪；已删除的抓放流程不恢复。"""

    def __init__(self, cmd, config):
        self.cmd = cmd
        self.team, self.notes = None, []
        point = config.get('point',{})
        self.x0, self.y0 = point.get('x0',640.), point.get('y0',550.)
        # Task 管阶段。InitDisributor 按时间打散，GoTo 按每帧的物块位置搜寻和靠近。
        self.distributor = InitDisributor(cmd,config.get('distribute',{}))
        trans = config.get('trans',{})
        self.go_to = GoTo(self.x0,self.y0,first=trans.get('first',True),config=trans,cmd=cmd)
        self.state, self.camera_deg = STOP, self.distributor.angle
        self.frame_count = 0

    def start(self):
        """重置任务，等待新帧推进打散。"""
        self.frame_count = 0
        self.camera_deg = self.distributor.angle
        self._change_state('distribute')

    def stop(self):
        """结束当前任务并停车。"""
        self._change_state(STOP)

    def reset(self):
        """停车并清空上位机的本场进度。"""
        self.stop()
        self.distributor.reset()
        self.go_to.reset()
        self.camera_deg = self.distributor.angle
        self.frame_count = 0
        self.notes.clear()

    def process_objects(self, objs, now=None):
        """接收当前帧的感知结果，不在任务内重新做推理。"""
        self._now = time.monotonic() if now is None else now
        if self.state==STOP:
            return self.status()
        self.frame_count += 1
        # 初次打散只按时间执行，不调用物块检测或计数。
        if self.state=='distribute':
            if self.distributor.run():
                self._change_state('search')
            else:
                self._note(self.distributor.note)
            return self.status()
        try:
            # GoTo 的返回值表示有没有到位。还在运行时，用 GoTo 自己的状态更新当前阶段。
            result = self.go_to.run(objs,now=self._now)
            self.camera_deg = self.go_to.camera_value
            self.state = STOP if result else self.go_to.state
            self._note(self.go_to.note)
        except Exception:
            self.stop()
            raise
        return self.status()

    def _change_state(self, state):
        """总控只切换任务；出发运动不再拆成几个阶段。"""
        self._stop_drive()
        self.state = state
        if state=='distribute':
            self.distributor.reset()
        elif state=='search':
            self.go_to.reset()
            self.go_to.team = self.team
        elif state=='track':
            self.go_to.start_track(self._now)

    def _stop_drive(self):
        """只停车，不自动打开或闭合夹爪。"""
        self.cmd.move_stop()

    def _note(self, text):
        """只打印变化的说明。"""
        if not self.notes or self.notes[-1]!=text:
            self.notes.append(text)
            self.notes[:] = self.notes[-100:]
            print('[Task] '+text)

    def status(self):
        """显示已有任务状态，不再伪造被删掉的抓放阶段。"""
        stage = 'init_dis' if self.state=='distribute' else 'goto' if self.state in ('search','track') else self.state
        goto_stage = {'search':'S1','track':'S2'}.get(self.state)
        return {'state':self.state,'stage':stage,'goto_stage':goto_stage,'team':self.team,'frames':self.frame_count,'camera_value':self.camera_deg,'note':self.notes[-1] if self.notes else '', 'rank1':round(self.go_to.rank1_score,2),'rank2':self.go_to.rank2_score}

    def close(self):
        """关闭动作接口。"""
        self.cmd.close()
