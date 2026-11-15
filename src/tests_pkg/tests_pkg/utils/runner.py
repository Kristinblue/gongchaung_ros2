"""测试节点共用的运行入口。"""

import rclpy


def run_node(node_class):
    """初始化、运行并收尾一个测试节点。

    Args:
        node_class: 继承 rclpy.node.Node 的节点类，无参构造。
    """
    rclpy.init()
    node = None
    try:
        node = node_class()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
