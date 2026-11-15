from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
from pathlib import Path

import yaml


def nodes(context):
    """读取这次启动传进来的参数，决定要启动哪些节点。"""
    def value(name):
        return LaunchConfiguration(name).perform(context)

    source, model, uart = value('source'), value('model'), value('uart')
    url, mode = value('camera_url'), value('mode')
    config = value('config')
    with open(config, encoding='utf-8') as stream:
        settings = yaml.safe_load(stream) or {}
    yolo = settings.get('inference_node', {}).get('ros__parameters', {}).get('yolo', {})
    model = model or yolo.get('model_path', '')
    trans = settings.get('task_node', {}).get('ros__parameters', {}).get('trans', {})
    camera = settings.get('camera_node', {}).get('ros__parameters', {})
    if source not in ('usb', 'http') or (source == 'http' and not url):
        raise ValueError('source: usb / http（需要 camera_url）')
    if mode not in ('preview', 'approach'):
        raise ValueError('mode: preview / approach')
    if uart and not model:
        raise ValueError('串口模式需提供 YOLO 模型和 USB / HTTP 摄像头')

    # 先读 robot.yaml，再用本次 launch 传进来的参数覆盖同名配置。
    def node(package, executable, **overrides):
        return Node(package=package, executable=executable, output='screen',
                    parameters=[config, overrides])

    # 默认链路：相机 → 感知节点转发画面 → HTTP 服务。
    actions = [
        node('desktop_server_pkg', 'desktop_server_node', camera_source=source, port=int(value('port'))),
        node('vision_pkg', 'perception_node', detect=bool(model), camera_settle_ms=trans.get('camera_settle_ms', 400)),
        node('vision_pkg', 'camera_node', device=value('camera_device'), url=url),
    ]
    # 有模型才做推理。串口由 uart 启用，靠近测试和正式任务只选其中一个。
    if model:
        actions.append(node('vision_pkg', 'inference_node', **{'yolo.model_path': model}))
    if uart:
        actions.append(node('communication_pkg', 'serial_node', max_pitch_deg=camera.get('max_pitch_deg', 80), **{'uart.device': uart}))
    if mode == 'approach':
        overrides = {'drive': bool(uart)}
        if value('color'):
            overrides['color'] = value('color')
        actions.append(node('tests_pkg', 'approach_test_node', **overrides))
    elif uart:
        actions.append(node('action_pkg', 'task_node'))
    return actions


def generate_launch_description():
    config = Path(get_package_share_directory('robot_launch')) / 'config/robot.yaml'
    return LaunchDescription([
        DeclareLaunchArgument('config', default_value=str(config)),
        DeclareLaunchArgument('source', default_value='usb'),
        DeclareLaunchArgument('camera_url', default_value=''),
        DeclareLaunchArgument('camera_device', default_value='auto'),
        DeclareLaunchArgument('port', default_value='18080'),
        DeclareLaunchArgument('model', default_value=''),
        DeclareLaunchArgument('uart', default_value=''),
        DeclareLaunchArgument('mode', default_value='preview'),
        DeclareLaunchArgument('color', default_value=''),
        OpaqueFunction(function=nodes),
    ])
