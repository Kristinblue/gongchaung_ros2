# STM32 通信

`communication_pkg/my_cmd.py` 给上层提供 `move_staight()`、`move_turn()` 等方法。`SerialNode` 打开串口，`MyUART` 读写字节，`SimpleProtocol` 和 `ProtocolParser` 打包和解析。

- `/robot/command` 接收上层命令。`/robot/feedback` 发布每个解析成功的回包。消息定义在 [robot_interfaces/msg](../robot_interfaces/msg)。
- `/robot/state` 保留最近的串口连接状态、红蓝方、相机指令角度和 STM32 上报的导航角度。首次收到导航角度后，`angle_known` 才为真。
- UART 使用 `robot.yaml` 中的 `uart.device` 和 `uart.baudrate`，默认 `/dev/ttyS6`、115200。STM32 帧固定为 `AA 55 | CMD | 数值低字节 | 数值高字节 | 校验`。数值是有符号 16 位整数，校验取前五字节累加的低八位。

| 命令 | 上位机发给 STM32 | STM32 发给上位机 |
| --- | --- | --- |
| `01` | 前后误差，负数向前、正数向后。启动时沿用 `01, 0` 查询队伍 | 队伍，0 红、1 蓝 |
| `02` | 转向误差，正数向右、负数向左 | 导航角度，单位度。沿用原定义，红区指向蓝区为 0，逆时针增加 |
| `03` | 夹爪，0 开、1 关 | |
| `04` | 相机俯角，0 度水平，向下为正 | |
| `05` | 相对转角，单位度，正数顺时针 | 数值 1 表示转向完成 |
| `06` | 停车 | |

`00` 是 ROS 心跳，只在上位机内部使用。
