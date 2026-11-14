# 项目说明

2027 年工创赛智能救援赛道。本仓只有上位机。负责机械、视觉和导航；板卡是香橙派 5 Plus。

- Windows 本地开发，WSL2 Ubuntu 22.04 / ROS 2 Humble 编译。派上 Ubuntu Jammy / ARM64 / Python 3.10。
- C++17，YOLO 保留 Python。HTTP 预览默认 640×360、10 fps。Windows 浏览器可接入电脑摄像头。
- 本地编辑前先拉取，冲突及时反馈。使用 `ssh pi` / `ssh pi-relay`，或以 orangepi 身份用 `ssh pio` / `ssh pio-relay`。
- 派上工程在 `/home/orangepi/my_ws/gongchuang_ros2`。原仓和派的 `my_configs` 独立。
- 保留我的原注释，不改下位机协议。Python docstring 用 Google 风格，调试信息用 [类名] 前缀。
- `logs/` 记时间、改动和关键命令。模型、账号私钥、本地配置和编译输出不入 Git。
- `legacy/` 是迁移前源码，作为对照。改训练、标注或数据前按原仓 TRAIN.md 的约定。
- 当前动作只迁移打散 → GoTo → 停车，抓取和投放后续补。
