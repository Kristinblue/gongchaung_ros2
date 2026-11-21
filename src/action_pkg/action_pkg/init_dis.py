"""
出发后直接前进打散物块。
初步设定离一堆物块较近的时候边前进边旋转

出发由下位机控制，给定出发区后小车走到大致两个安全区的中轴线上（与长边平行）
"""
#第一个塞到y分量的，负数就是往前
#第二个赛道x分量控制转向。这里我们搭配出一个比较合适的打散方法
BASE_FORWARD = -100
BASE_TURN = 250

from .utils.my_timer import MyTimer


class InitDisributor:
    """每帧按同一计时器执行一次运动，不使用视觉或机构反馈。"""

    def __init__(self, cmd, config=None):
        self.cmd = cmd
        config = config or {}
        self.base_forward = -abs(int(config.get('base_forward',BASE_FORWARD)))
        self.scatter_forward = -abs(int(config.get('scatter_forward',self.base_forward)))
        self.base_turn = int(config.get('base_turn',BASE_TURN))
        self.move_ms = float(config.get('move_ms',3000))
        self.scatter_ms = float(config.get('scatter_ms',5000))
        self.angle = float(config.get('angle',0))
        self.timer = MyTimer()
        self.reset()

    def run(self):
        """0–move_ms前进，之后前进并旋转，到总时长停车并返回True。"""
        if not self.timer.is_running:
            self.cmd.grab(1)
        self.timer.start()
        if self.timer.is_timeout(self.move_ms+self.scatter_ms):
            self.cmd.move_straight(0)
            self.cmd.move_turn(0)
            self.done, self.note = True, '初次打散结束'
            return True
        scattering = self.timer.is_timeout(self.move_ms)
        turn = self.base_turn if scattering else 0
        # 配置沿用原来的负值前进，发送时转换为正值前进。
        self.cmd.move_straight(-(self.scatter_forward if scattering else self.base_forward))
        self.cmd.move_turn(turn)
        self.note = '边前进边旋转' if turn else '向前打散'
        return False

    def remaining_s(self):
        """返回整个动作的剩余秒数，仅供显示。"""
        return max(0.,self.move_ms+self.scatter_ms-self.timer.get_elapsed())/1000

    def reset(self):
        """下次出发时重置计时；每帧run不重置起点。"""
        self.done, self.note = False, '准备初次打散'
        self.timer.reset()
