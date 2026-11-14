# 项目说明
这是2027工创赛的代码仓库，这里只包含上位机部分

## 环境说明
- 香橙派系统
- 语言：主要是c++

## 整体文件夹说明

### 源码

### 电脑客户端
qt框架做的，在这里面可以看到画面，更改一些值，显示代码的执行阶段，其他功能后续再加


虽然我已经有了好几种连接方式，有线无线都有，应该不会出问题，但还是保底的下位机加单独香橙派就能完成整个任务，电脑能控制是最好的，

### 日志

### 实验
对比一些方法，得到更高效率
- 找安全区的方法
-

### ROS 2 功能包

| 包 | 节点 |
| --- | --- |
| `desktop_server_pkg` | HTTP MJPEG、状态和设置 |
| `communication_pkg` | STM32 串口、协议和反馈 |
| `vision_pkg` | C++ 采图和感知，Python YOLO |
| `action_pkg` | 打散、GoTo、到位停车 |

`legacy/` 保留原工程代码和注释，`logs/` 记开发过程。

### 开发和预览

Windows 用 WSL2 Ubuntu 22.04，香橙派 5 Plus 用 Ubuntu Jammy ARM64。两端使用 ROS 2 Humble、C++17、Python 3.10 和 OpenCV。

```bash
# 已安装 ROS 2 Humble 后，一次性准备依赖
sudo apt install python3-colcon-common-extensions libopencv-dev python3-opencv python3-venv
git clone https://github.com/Kristinblue/gongchaung_ros2.git gongchuang_ros2
cd gongchuang_ros2
bash build.sh
bash run.sh
```

Windows 打开 [本地预览](http://localhost:8080)，点「使用电脑摄像头」。默认 640×360、10 fps，支持调整 JPEG 质量。也可用手机 IP Webcam：`bash run.sh source:=http camera_url:=http://手机IP:8080/video`，手机与运行 ROS 的电脑需互通。

### 香橙派

用 `ssh pio` 或 `ssh pio-relay`，工作区为 `~/my_ws/gongchuang_ros2`。更新后执行 `git pull --ff-only && bash build.sh`。首次使用派上已有的 RKNNLite wheel 和模型：

```bash
bash setup_pi.sh ~/rknn-toolkit2/rknn-toolkit-lite2/packages/*cp310*.whl \
  ~/my_ws/gongchuang/my_project/assets/models/11_11/train5.rknn
bash run.sh source:=usb camera_device:=/dev/video0 model:="$PWD/models/train5.rknn"
```

按 `v4l2-ctl --list-devices` 选择实际 USB 摄像头。电脑用 `ssh -N -L 8080:127.0.0.1:8080 pio-relay` 转发（有线换 `pio`），再打开本地预览。实车联调另加 `uart:=/dev/ttyS6`，由 `ros2 service call /task/start std_srvs/srv/Trigger '{}'` 开始、`/task/stop` 停止。正式 Qt 客户端后续接同一套 HTTP 接口。
