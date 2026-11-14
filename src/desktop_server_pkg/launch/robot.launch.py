from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
from pathlib import Path


def nodes(context):
    source = LaunchConfiguration('source').perform(context)
    model = LaunchConfiguration('model').perform(context)
    uart = LaunchConfiguration('uart').perform(context)
    url = LaunchConfiguration('camera_url').perform(context)
    if source not in ('browser', 'usb', 'http') or (source == 'http' and not url):
        raise ValueError('source: browser / usb / http（需要 camera_url）')
    if uart and (not model or source == 'browser'):
        raise ValueError('串口模式需提供 YOLO 模型和 USB / HTTP 摄像头')
    actions = [
        Node(package='desktop_server_pkg', executable='desktop_server_node', output='screen',
             parameters=[{'camera_source': source, 'port': LaunchConfiguration('port')}]),
        Node(package='vision_pkg', executable='perception_node', output='screen',
             parameters=[{'detect': bool(model)}]),
    ]
    if source != 'browser':
        actions.append(Node(package='vision_pkg', executable='camera_node', output='screen',
                            parameters=[{'device': LaunchConfiguration('camera_device'), 'url': url}]))
    if model:
        actions.append(Node(package='vision_pkg', executable='yolo_node', output='screen',
                            parameters=[{'model': model}]))
    if uart:
        actions.extend([
            Node(package='communication_pkg', executable='serial_node', output='screen',
                 parameters=[{'device': uart}]),
            Node(package='action_pkg', executable='task_node', output='screen',
                 parameters=[str(Path(get_package_share_directory('desktop_server_pkg')) / 'config/robot.yaml')]),
        ])
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('source', default_value='browser'),
        DeclareLaunchArgument('camera_url', default_value=''),
        DeclareLaunchArgument('camera_device', default_value='/dev/video0'),
        DeclareLaunchArgument('port', default_value='8080'),
        DeclareLaunchArgument('model', default_value=''),
        DeclareLaunchArgument('uart', default_value=''),
        OpaqueFunction(function=nodes),
    ])
