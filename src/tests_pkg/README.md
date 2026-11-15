# 单项测试

单项测试节点放在 `tests_pkg/nodes/`，目前只有靠近测试，对应原工程 `tests/single_tests/approach_test.py`。参数同样在 [robot.yaml](../robot_launch/config/robot.yaml)，按节点分组。

## 靠近

`approach_test_node` 对应原工程的单项靠近测试，每帧选指定颜色中底边中心离参考点最近的物块，输出左右和前后像素误差。找不到目标就输出停车。

在香橙派仓库根目录编译后运行。默认只输出误差，不接串口：

```bash
bash tools/build.sh
bash tools/run.sh approach color:=orange model:="$PWD/assets/models/train5.rknn"
```

另开一个派上的终端查看输出：

```bash
source /opt/ros/humble/setup.bash
source install/local_setup.bash
ros2 topic echo /approach_test/command
```

`code: 2` 是转向误差，`code: 1` 是前后误差，`code: 6` 表示停车。候选框可查看 `/approach_test/target`。已有视觉节点在跑时，也可单独运行 `ros2 run tests_pkg approach_test_node --ros-args --params-file src/robot_launch/config/robot.yaml`。

需要实车动起来时，先关闭其他动作节点，再给上述启动命令加 `uart:=/dev/ttyS6`。这个模式只启动靠近测试，不启动完整任务。用 `ros2 service call /approach_test/start std_srvs/srv/Trigger '{}'` 开始，`/approach_test/stop` 停止。测试沿用原来逐帧靠近的做法，加了误差限幅、丢目标及断流停车。
