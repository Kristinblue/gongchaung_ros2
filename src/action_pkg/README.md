# 动作

参数集中在 [robot.yaml](../robot_launch/config/robot.yaml)，`task_node.ros__parameters` 下沿用 `point`、`distribute` 和 `trans`。感知节点也用 `trans.camera_settle_ms`。原 Python 配置在 `gongchuang/my_project/project_config.yaml`，可对照 `point`、`distribute`、`trans`。运行时修改 ROS 2 的 YAML，或用 `config:=/绝对路径/robot.yaml` 加载另一份。

通信包里的 [MyCMD](../communication_pkg/communication_pkg/my_cmd.py) 保留 `move_staight()`、`move_turn()`、`move_turn_a()` 等动作方法，将命令发到 `/robot/command`。转向完成回包从 `/robot/feedback` 交给 `MyCMD.read_feedback()`。

`task_node` 执行打散 → GoTo → 停车。单项靠近测试已拆到 [tests_pkg](../tests_pkg/README.md)。

## GoTo 和 STM32

`Task` 每收到一帧物块就调用 `GoTo.run()`。GoTo 用目标框底边中心和 `point.x0/y0` 算横向和前后像素误差，再调用 `MyCMD`。STM32 负责根据误差做 PID 控制。相对转向完成后，STM32 回 `05, 1`，`MyCMD` 将 `turn_done` 置为真。

命令编号和帧格式见[串口说明](../communication_pkg/README.md)。当前 `/task/start` 和 `/task/stop` 是服务。将来拆 GoTo 节点时，可以用 Action 管一次搜寻和靠近的目标、进度、结果和取消，逐帧像素误差仍走现有话题。

## 本场状态与复位

`TaskNode` 用 `/match/state` 发布当前阶段、已处理帧数和已确认目标。桌面预览通过这个话题获取阶段。运行正式任务时，在已加载工作区的终端查看状态或复位。

```bash
ros2 topic echo /match/state
ros2 service call /match/reset std_srvs/srv/Trigger '{}'
```

复位发布停车命令，清掉本场目标、计时和进度，然后回到等待开始的 `stop` 阶段。下一次 `/task/start` 需要先收到复位后的视觉帧。服务回复确认的是上位机复位，STM32 继续使用原有停车命令。
