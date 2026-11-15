"""在终端调用 MyCMD 的动作接口，串口收发交给 serial_node。"""

import time

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
from robot_interfaces.msg import Command

from communication_pkg.my_cmd import MyCMD


HELP = '''move_straight -30   前后误差，负值向前，正值向后
move_turn 10        转向误差，正值向右，负值向左
move_turn_a 30      相对转角（度），正值向右，负值向左
grab 0              夹爪，0 开，1 关
camera 20           相机俯角，0～80 度
angle_calib 90      设置当前绝对角度，06 暂用于模拟测试
move_stop / stop    停车
help / quit         查看命令 / 退出'''


class SerialTest(Node):
    def __init__(self):
        super().__init__('serial_test_node')
        self.publisher = self.create_publisher(Command, 'robot/command', 10)
        self.cmd = MyCMD(self.publisher)
        self.actions = {
            'move_straight': (self.cmd.move_staight, -32768, 32767),
            'move_staight': (self.cmd.move_staight, -32768, 32767),
            'move_turn': (self.cmd.move_turn, -32768, 32767),
            'move_turn_a': (self.cmd.move_turn_a, -32768, 32767),
            'grab': (self.cmd.grab, 0, 1),
            'camera': (self.cmd.camera, 0, 80),
            'angle_calib': (self.cmd.angle_calib, -32768, 32767),
            'set_angle': (self.cmd.angle_calib, -32768, 32767),
        }

    def run(self):
        """等串口节点接通，然后逐行读取测试命令。"""
        deadline = time.monotonic() + 3.0
        while not self.publisher.get_subscription_count():
            if time.monotonic() >= deadline:
                self.get_logger().error('[SerialTest] 串口节点未连接')
                return 1
            rclpy.spin_once(self, timeout_sec=0.1)

        print(HELP)
        while True:
            parts = input('cmd> ').split()
            if parts == ['quit']:
                return 0
            if parts in (['stop'], ['move_stop']):
                self.stop()
                print('[SerialTest] 已发布停车指令')
            elif parts == ['help']:
                print(HELP)
            elif len(parts) == 2 and parts[0] in self.actions:
                self.run_action(*parts)
            elif parts:
                print('[SerialTest] 输入 help 查看命令和参数')

    def run_action(self, name, argument):
        """把整数参数交给对应的 MyCMD 方法。"""
        action, low, high = self.actions[name]
        try:
            value = int(argument)
        except ValueError:
            print('[SerialTest] 参数请输入整数')
            return
        if not low <= value <= high:
            print(f'[SerialTest] {name} 参数范围为 {low} 到 {high}')
            return

        if name == 'move_turn_a' and value == 0:
            print('[SerialTest] 相对转角为 0，无需旋转')
            return
        if name in ('move_straight', 'move_staight', 'move_turn'):
            try:
                action(value)
                time.sleep(0.4)
            finally:
                self.stop()
            print(f'[SerialTest] 已发布 {name} {value} 和停车指令')
            return
        action(value)
        self.publisher.wait_for_all_acked(Duration(seconds=0.5))
        if name in ('angle_calib', 'set_angle'):
            print(f'[SerialTest] 已发布绝对角度 {value}，06 仅在模拟串口打包')
        else:
            print(f'[SerialTest] 已发布 {name} {value}')

    def stop(self):
        self.cmd.move_stop()
        self.publisher.wait_for_all_acked(Duration(seconds=0.5))


def main():
    # Ctrl+C 先触发 Python 的 finally，让前进测试能发出停车指令。
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = SerialTest()
    try:
        return node.run()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
