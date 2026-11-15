# 一键预览与 USB 摄像头实测

2026-11-15 11:14（UTC+8）

- Windows 客户端经现有 SSH 连接启动 `tools/preview.sh`，脚本用 `systemd-run --user` 把原图预览放到后台。香橙派已有工作区含未提交改动，本次在 `~/.local/share/gongchuang_ros2_preview` 单独编译，通过 `~/.local/bin/gongchuang-preview` 启动。
- 香橙派用 `bash tools/build.sh` 编完七个包。USB 摄像头主视频设备是 `/dev/video20`。通过客户端点「启动预览」，再用 `python tools/verify_preview.py --url http://127.0.0.1:<客户端转发端口>` 验证有线 SSH 连续收到 JPEG。
- 检查了 12 张 640×360 帧，内容有变化，平均灰度约为 4（0–255）。预览服务持续运行，当前画面较暗。
