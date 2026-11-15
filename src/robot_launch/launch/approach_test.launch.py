from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    """沿用 robot.launch.py 的相机和预览配置，切换为单项靠近测试。"""
    robot = Path(get_package_share_directory('robot_launch')) / 'launch/robot.launch.py'
    return LaunchDescription([
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(robot)),
                                 launch_arguments={'mode': 'approach'}.items()),
    ])
