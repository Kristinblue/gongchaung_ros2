"""
应用层再封装
内部是[MyUART]

把原本的cmd等封装起来，对外暴露动作接口

ROS 版的 MyCMD 发话题，由 SerialNode 调用 MyUART。
"""

from robot_interfaces.msg import Command, Feedback

# 分层说明：
#   MyCMD（本文件）只负责“要做什么动作”，把动作翻译成命令位和数值，
#   通过 /robot/command 话题发出去；真正的 6 字节打包、串口读写、
#   看门狗都在 C++ 的 serial_node 里。这样改动作逻辑不用碰串口，
#   改协议也不用碰任务代码。
#
#   动作命令（发）：01 前进/后退  02 转向  03 夹爪  04 相机俯角
#                  05 相对旋转  06 绝对角度校准  07 距离直行  08 停车  00 查询队伍
#   回包（收）：  00 队伍确认  01 绝对角度

# 相机端发送的命令位对应
# 动作与命令位的对应
GET_FLAG = Command.GET_FLAG #确认红蓝方，0为红方，1为蓝方
STRAIGHT = Command.STRAIGHT # 正数前进，负数后退。香橙派算完误差之后取负数再发过去。正数往前更符合直觉
TURN = Command.TURN # 正右负左

#爪子有限位，需映射角度，暂且先弄最大和最小吧
# 之后应该还要在单片机里面加对角度的判断，有些角度抓取物块不能完全闭合，应该是检测堵转或者实际角度？
GRAB= Command.GRAB # 0为开，1为关

# 摄像头角度：0度水平，向下为正；当前限位下整数指令范围0–80度。
CAM_ANGLE = Command.CAMERA

#角度旋转
TURN_ANGLE = Command.TURN_ANGLE # 以当前方向为基准，正数为右转角度，顺时针，负数左转
ANGLE_CALIB = Command.ANGLE_CALIB # 绝对角度校准，利用安全区的，之后具体规定
STRAIGHT_DIS = Command.STRAIGHT_DIS # 直线行驶，单位cm，正数前进，负数后退。
#可能是需要具体距离的，因为我想通过这个快速调整接近安全区的姿态
STOP = Command.STOP


# 接收的命令对应
FLAG = Feedback.FLAG #确认红蓝方，0为红方，1为蓝方
ANGLE = Feedback.ANGLE #得到绝对的角度，初始朝向必须准，暂且假设红色指向蓝色的为0度，逆时针增大，0-360度
# 需要


class MyCMD:
    """动作接口通过 ROS 发布，串口由 communication_pkg 持有。"""

    def __init__(self, publisher):
        self.publisher = publisher
        # 相对旋转是否完成，由 read_feedback() 按连续角度回包判断。
        self.turn_done = False
        self.angle = None
        self._turn_angle = 0
        self._turned = 0

    def _send(self, code: int, value: int):
        """发布 ROS2 命令消息，具体串口打包交给 SerialNode。"""
        # Command 中的具名常量本身就是整数，可以直接填入 code。
        # 协议里 value 是 int16，先夹到 -32768~32767，避免越界。
        self.publisher.publish(Command(code=code, value=max(-32768,min(32767,int(value)))))

    def set_forward_error(self, error_px: int):
        """发送前后方向的像素误差，正数向前，负数向后。"""
        self._send(Command.STRAIGHT, error_px)

    def set_turn_error(self, error_px: int):
        """发送转向像素误差，正数向右，负数向左。"""
        self._send(Command.TURN, error_px)

    def move_staight(self, speed:int):
        """前进/后退，正数前进，负数后退
        由像素决定，以及PID的参数
        不是严格的speed！！！！！
        """
        # speed 是像素误差，不是 m/s；实际速度由 STM32 的 PID 决定。
        self.set_forward_error(speed)

    def move_straight_dis(self, distance:int):
        """按厘米直行，正数前进，负数后退，由 STM32 执行。"""
        self._send(STRAIGHT_DIS, distance)

    def move_turn(self, speed:int):
        """转向，正右负左"""
        # 和前进一样，单位是像素误差，正右负左。
        self.set_turn_error(speed)

    def move_turn_a(self,angle:int):
        """直接发送相对转角，返回是否已接受请求。"""
        self._turn_angle = max(-32768, min(32767, int(angle)))
        self._turned = 0
        self.turn_done = self._turn_angle == 0
        if self._turn_angle:
            self._send(TURN_ANGLE, self._turn_angle)
        return True

    def read_feedback(self, feedback):
        """收到 01 角度后，累计本次实际转过的角度。"""
        if feedback.code != Feedback.ANGLE or not 0 <= feedback.value <= 360:
            return
        angle = feedback.value % 360
        if self._turn_angle and self.angle is not None:
            # 例如从 2° 顺时针转到 358°，差值是 -4°。命令正数表示顺时针。
            delta = (angle - self.angle + 180) % 360 - 180
            self._turned += -delta if self._turn_angle > 0 else delta
            if self._turned > 0 and self._turned >= abs(self._turn_angle) - 1:
                self.turn_done = True
                self._turn_angle = 0
        self.angle = angle

    def angle_calib(self, angle:int):
        """绝对角度校准，利用安全区的，之后具体规定"""
        self._send(ANGLE_CALIB, angle)

    def move_stop(self):
        """08停车，并清除旧的前进和转向误差，不改变夹爪。"""
        # 停车同时清掉 turn_done，避免旧的“转完了”状态影响下一次动作。
        self.turn_done = False
        self._turn_angle = 0
        self._send(STOP, 0)

    def grab(self, angle:int):
        """夹爪，0为开，1为关"""
        # 当前协议只有开/关两个值，抓取角度后面再补。
        self._send(GRAB, angle)

    def camera(self, angle:int):
        """相机俯角，单位度；0水平，向下为正。"""
        # 0~80 度，serial_node 还会按 max_pitch_deg 再检查一次。
        self._send(CAM_ANGLE, angle)

    def close(self):
        """停车。串口由通信节点负责关闭。"""
        # 这里只发停车，不关串口；串口的生命周期归 serial_node。
        self.move_stop()
