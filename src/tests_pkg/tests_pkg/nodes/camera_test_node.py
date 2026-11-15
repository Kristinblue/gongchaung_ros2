"""订阅采图节点的画面，记录实际收到的帧率和分辨率。"""
import time

from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

from ..utils.runner import run_node


class CameraTest(Node):
    def __init__(self):
        super().__init__('camera_test_node')
        self.frames = 0
        self.size = None
        self.last_report = time.monotonic()
        self.create_subscription(Image, 'camera/image', self.on_frame, qos_profile_sensor_data)
        self.create_timer(1.0, self.report)

    def on_frame(self, image):
        self.frames += 1
        self.size = (image.width, image.height)

    def report(self):
        now = time.monotonic()
        if self.frames:
            width, height = self.size
            fps = self.frames / (now - self.last_report)
            self.get_logger().info(f'[CameraTest] {width}x{height} {fps:.1f} fps')
        else:
            self.get_logger().info('[CameraTest] 本秒未收到画面')
        self.frames = 0
        self.last_report = now


def main():
    run_node(CameraTest)
