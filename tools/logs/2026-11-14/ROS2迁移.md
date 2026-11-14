# 2026-11-14 · ROS 2 迁移

- 四个功能包，Python 保留原 YOLO，C++ 负责采图、感知、串口、打散、GoTo 和 HTTP。原代码与注释保存在 `legacy/`。
- `bash build.sh` 在 WSL2 Humble 和香橙派 Humble 均编译通过。WSL 在 D 盘编译时曾提示小于 1 秒的文件时钟偏差。
- `bash run.sh` 本地服务使用 18080，避开 Windows 已占用的 8080。实拍电脑摄像头经 HTTP 上传与 MJPEG 回传，设置修改和读回通过。WSL 的 ONNX 和派上的 RKNN 都用 train5。
- `ssh -N -L 18085:127.0.0.1:18085 pio-relay` 测试云中转。首轮超时后复查 ROS 各图像话题，使用实际摄像头上传 7 张并收到 4 张 640×360 回传，设置读回通过。10 fps 是预览上限，本次未测稳定帧率或端到端延迟。
- 派上配置工作区 `~/my_ws/gongchuang_ros2`，用现有 GitHub SSH 身份跟踪 main。Windows Git HTTPS 走 HTTP/1.1、OpenSSL 和 Git v0 后拉取通过（仅本仓设置）。
- 当前派上没有识别到 USB UVC 摄像头。预览验证未打开实车串口，未跑实车抓放。
