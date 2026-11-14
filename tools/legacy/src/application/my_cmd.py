"""
队友必看必看必看！
应用层再封装
内部是[MyUART]

把原本的cmd等封装起来，对外暴露动作接口
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


from src.lib.communication.my_uart import MyUART
from src.lib.communication.my_ct_protocol import SimpleProtocol

class MyCMD :
    def __init__(self, my_uart=None):
        self.my_uart = my_uart if my_uart is not None else MyUART()
        self._commands = {STRAIGHT:0, TURN:0}
        self.turn_done = False

    def _send(self, cmd, value):
        """发送当前动作，避免串口最新帧队列丢掉同帧的前进或转向。"""
        if cmd == TURN_ANGLE or cmd == STOP:
            self._commands.pop(STRAIGHT, None)
            self._commands.pop(TURN, None)
        else:
            self._commands[cmd] = int(value)
        message = b''
        for key, data in self._commands.items():
            message += SimpleProtocol.pack(key, data.to_bytes(2, 'little', signed=True))
        if cmd == TURN_ANGLE or cmd == STOP:
            message += SimpleProtocol.pack(cmd, int(value).to_bytes(2, 'little', signed=True))
        self.my_uart.put_bytes(message)


    def move_staight(self, speed:int):
        """前进/后退，正数后退，负数往前
        由像素决定，以及PID的参数
        不是严格的speed！！！！！
        """
        self._commands.setdefault(TURN, 0)
        self._send(STRAIGHT, speed)

    def move_turn(self, speed:int):
        """转向，正右负左"""
        self._commands.setdefault(STRAIGHT, 0)
        self._send(TURN, speed)

    def move_turn_a(self,angle:int):
        """
        带角度的旋转
        """
        self.turn_done = False
        self._send(TURN_ANGLE,angle)

    def read_feedback(self):
        """消费本批反馈，保留队伍等其他消息交给总控。"""
        messages = self.my_uart.parse_received()
        for cmd, data in messages:
            if cmd == TURN_DONE and int.from_bytes(data,'little',signed=True) == 1:
                self.turn_done = True
        return messages

    def move_stop(self):
        """06停车，并清除旧的前进和转向误差，不改变夹爪。"""
        self._send(STOP, 0)

    def grab(self, angle:int):
        """夹爪，0为开，1为关"""
        self._send(GRAB, angle)

    def camera(self, angle:int):
        """相机俯角，单位度；0水平，向下为正。"""
        self._send(CAM_ANGLE, angle)

    def close(self):
        """停车并关闭串口，不改变夹爪开合状态。"""
        self.move_stop()
        self.my_uart.close()

    def get_flag(self):
        """确认红蓝方，0为红方，1为蓝方"""
        self.my_uart.send_fmt_message(FLAG, None, "<h")

    def get_angle(self):
        """得到绝对的角度，初始朝向必须准，暂且假设红色指向蓝色的为0度，逆时针增大，0-360度"""
        self.my_uart.send_fmt_message(ANGLE, None, "<h")
