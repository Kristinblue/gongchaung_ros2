# ROS 2 功能包

| 包 | 职责 |
| --- | --- |
| `desktop_server_pkg` | HTTP 预览、状态和设置 |
| `communication_pkg` | STM32 串口、协议和反馈 |
| `vision_pkg` | C++ 采图和感知，Python YOLO |
| `action_pkg` | 打散、GoTo、到位停车 |

## 环境

Windows 用 WSL2 Ubuntu 22.04，香橙派 5 Plus 用 Ubuntu Jammy ARM64。两端使用 ROS 2 Humble、C++17、Python 3.10 和 OpenCV。ROS 软件源配置好后，在仓库根目录执行：

```bash
sudo apt install ros-humble-ros-base ros-humble-rosidl-default-generators ros-humble-ament-cmake-python \
  python3-colcon-common-extensions libopencv-dev python3-opencv python3-venv
bash tools/build.sh
```

## 电脑

`bash tools/run.sh` 后打开 [预览](http://localhost:18080)，点击「使用电脑摄像头」。手机 IP Webcam 用 `bash tools/run.sh source:=http camera_url:=http://手机IP:8080/video`。

在 WSL 跑 YOLO 时，先执行 `python3 -m venv --system-site-packages tools/.venv` 和 `tools/.venv/bin/python -m pip install "numpy<2" onnxruntime`，然后给启动命令加 `model:=/绝对路径/best.onnx`。

## 香橙派

用 `ssh pio` 或 `ssh pio-relay`，在 `~/my_ws/gongchuang_ros2` 拉取并编译。首次使用派上已有的 RKNNLite wheel 和模型：

```bash
bash tools/setup_pi.sh ~/rknn-toolkit2/rknn-toolkit-lite2/packages/*cp310*.whl \
  ~/my_ws/gongchuang/my_project/assets/models/11_11/train5.rknn
bash tools/run.sh source:=usb camera_device:=/dev/video0 model:="$PWD/tools/models/train5.rknn"
```

按 `v4l2-ctl --list-devices` 选择实际 USB 摄像头。Windows 用 `ssh -N -L 18080:127.0.0.1:18080 pio-relay` 转发（有线换 `pio`），再打开预览。

实车联调在启动命令中加 `uart:=/dev/ttyS6`，用 `ros2 service call /task/start std_srvs/srv/Trigger '{}'` 开始，`/task/stop` 停止。
