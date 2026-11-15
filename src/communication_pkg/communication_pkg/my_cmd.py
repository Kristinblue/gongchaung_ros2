"""
队友必看必看必看！
应用层再封装
内部是[MyUART]

把原本的cmd等封装起来，对外暴露动作接口

ROS 版的 MyCMD 发话题，由 SerialNode 调用 MyUART。
"""

# 相机端发送的命令位对应
# 动作与命令位的对应
STRAIGHT = b'\x01' # 正数后退，负数往前
TURN = b'\x02' # 正右负做

#爪子有限位，需映射角度，暂且先弄最大和最小吧
# 之后应该还要在单片机里面加对角度的判断，有些角度抓取物块不能完全闭合，应该是检测堵转或者实际角度？
GRAB= b'\x03' # 0为开，1为关

# 摄像头角度：0度水平，向下为正；当前限位下整数指令范围0–80度。
CAM_ANGLE = b'\x04'

#角度旋转
TURN_ANGLE = b'\x05' # 以当前方向为基准，正数为右转角度，顺时针，负数左转
STOP = b'\x06'

# 接收的命令对应
FLAG = b'\x01' #确认红蓝方，0为红方，1为蓝方
ANGLE = b'\x02' #得到绝对的角度，初始朝向必须准，暂且假设红色指向蓝色的为0度，逆时针增大，0-360度
TURN_DONE = b'\x05'  # 接收数据1：本次相对旋转完成。
#初版代码里面陀螺仪的角度信息我们暂时先不用


from robot_interfaces.msg import Command


class MyCMD:
    """动作接口通过 ROS 发布，串口由 communication_pkg 持有。"""

    def __init__(self, publisher):
        self.publisher = publisher
        self.turn_done = False

    def _send(self, cmd, value):
        """在 ROS 话题上发送动作命令，由串口节点按原协议打包。"""
        self.publisher.publish(Command(code=cmd[0], value=max(-32768,min(32767,int(value)))))

    def move_staight(self, speed:int):
        """前进/后退，正数后退，负数往前
        由像素决定，以及PID的参数
        不是严格的speed！！！！！
        """
        self._send(STRAIGHT, speed)

    def move_turn(self, speed:int):
        """转向，正右负左"""
        self._send(TURN, speed)

    def move_turn_a(self,angle:int):
        """
        带角度的旋转
        """
        self.turn_done = False
        self._send(TURN_ANGLE,angle)

    def read_feedback(self, feedback):
        """消费一次串口反馈，记录相对转角完成。"""
        if feedback.code == TURN_DONE[0] and feedback.value == 1:
            self.turn_done = True

    def heartbeat(self):
        """维持通信节点的动作看门狗，不向下位机发送新动作。"""
        self._send(b'\x00', 0)

    def move_stop(self):
        """06停车，并清除旧的前进和转向误差，不改变夹爪。"""
        self.turn_done = False
        self._send(STOP, 0)

    def grab(self, angle:int):
        """夹爪，0为开，1为关"""
        self._send(GRAB, angle)

    def camera(self, angle:int):
        """相机俯角，单位度；0水平，向下为正。"""
        self._send(CAM_ANGLE, angle)

    def close(self):
        """停车。串口由通信节点负责关闭。"""
        self.move_stop()
