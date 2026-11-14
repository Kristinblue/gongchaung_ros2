# 项目说明

2027 年工创赛智能救援赛道。本仓只有上位机。负责机械、视觉和导航；板卡是香橙派 5 Plus。

- Windows 本地开发，WSL2 Ubuntu 22.04 / ROS 2 Humble 编译。派上 Ubuntu Jammy / ARM64 / Python 3.10。
- C++17，YOLO 保留 Python。HTTP 预览默认 640×360、10 fps。Windows 浏览器可接入电脑摄像头。
- 本地编辑前先拉取，冲突及时反馈。使用 `ssh pi` / `ssh pi-relay`，或以 orangepi 身份用 `ssh pio` / `ssh pio-relay`。
- 派上工程在 `/home/orangepi/my_ws/gongchuang_ros2`。原仓和派的 `my_configs` 独立。
- 不改下位机协议。Python docstring 用 Google 风格，调试信息用 [类名] 前缀。
- `tools/logs/` 记时间、改动和关键命令。模型、账号私钥、本地配置和编译输出不入 Git。里面专门存放做一些事情的记录，我通常会让你把日志写进去，要记录好时间，每一天的放一个文件夹里。如果是md就稍微整理一下，这种主要是给我看的，记录做过的事情，简单说明，以及那些命令，因为你只是替我做事了但我仍然需要学习这些命令；如果输入输出太多就放txt文件里
- 不要改我的注释，那都是我的心血
- `tools/legacy/` 是迁移前源码，作为对照。改训练、标注或数据前按原仓 TRAIN.md 的约定。
- 当前动作只迁移打散 → GoTo → 停车，抓取和投放后续补。
- Git 提交说明使用中文。
