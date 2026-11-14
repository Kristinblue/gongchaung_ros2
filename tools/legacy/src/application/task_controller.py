"""
这里负责整体的逻辑框架,以及各种类的构建让main看起来清爽，或者包一些别的
"""

import time
import yaml

from src.application.my_cmd import MyCMD, FLAG
from src.application.init_dis import InitDisributor
from src.application.grab.go_to import GoTo
from src.application.detect.get_objs import GetObjs

STOP = 'stop'


class Task:
    """逐帧调度出发、搜寻与追踪；已删除的抓放流程不恢复。"""

    def __init__(self, width=1280, height=720, cmd=None, time_debug=False, config_path=None, detector=None, team=None):
        """主程序传入MyCMD，测试可注入同动作接口。"""
        with open(config_path or 'project_config.yaml','r',encoding='utf8') as stream:
            self.config = yaml.safe_load(stream)
        self.cmd = cmd if cmd is not None else MyCMD()
        self.width, self.height, self.time_debug = width, height, time_debug
        self.team, self.notes = team, []
        self.x0 = self.config.get('point',{}).get('x0',width/2)
        self.y0 = self.config.get('point',{}).get('y0',550)
        self.detect = GetObjs(self.config,detector,width,height)
        self.distributor = InitDisributor(self.cmd,self.config.get('distribute',{}))
        trans = self.config.setdefault('trans',{})
        self.go_to = GoTo(self.x0,self.y0,width,height,first=trans.get('first',True),config=trans,cmd=self.cmd,team=team)
        self.state, self.camera_deg = 'distribute', self.distributor.angle
        self.frame_count = 0
        self._feedback, self.payload = {}, []
        self._now = time.monotonic()
        self._last_frame_id = None
        if team is None:
            self.cmd.get_flag()
            self._note('查询队伍信息，不阻塞出发')
        self._change_state('distribute')

    def process_frame(self, frame, now=None, frame_id=None, feedback=None):
        """主循环每帧调用一次；内部不阻塞等待动作完成。"""
        self._now = time.monotonic() if now is None else now
        self._feedback = feedback or {}
        self._read_team()
        if frame is None or (frame_id is not None and frame_id==self._last_frame_id):
            self._stop_drive()
            if self.state in ('search','track'):
                self.go_to.reset()
                self.state = 'search'
            return self.status()
        self._last_frame_id = frame_id
        self.frame_count += 1
        # 初次打散只按时间执行，不调用物块检测或计数。
        if self.state=='distribute':
            if self.distributor.run():
                self._change_state('search')
            else:
                self._note(self.distributor.note)
            return self.status()
        if self.state==STOP:
            self._stop_drive()
            return self.status()
        try:
            objs = self.detect.run(frame,team=self.team,ready=self.go_to.view_ready(self._now),camera_deg=self._feedback.get('camera_deg',self.camera_deg))
            result = self.go_to.run(objs,now=self._now)
            self._record_camera(self.go_to.camera_value)
            self.state = STOP if result else self.go_to.state
            self._note(self.go_to.note)
        except Exception:
            self._change_state(STOP)
            raise
        return self.status()

    def _read_team(self):
        """新接收定义：FLAG=01，0红、1蓝。"""
        for cmd, data in self.cmd.read_feedback():
            if cmd==FLAG and self.team is None:
                self.team = {0:'red',1:'blue'}.get(int.from_bytes(data,'little',signed=True))
                if self.team is not None:
                    self.go_to.team = self.team
                    self._note(f'已确认队伍：{self.team}')
                    break

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

    def _record_camera(self, value):
        """记录相机位置指令；换位置清空旧像素记忆。"""
        if value!=self.camera_deg:
            self.camera_deg = value
            self.detect.reset()

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
        self.detect.close()
        self.cmd.close()
