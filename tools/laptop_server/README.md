# Windows 客户端原型

白色界面，左边预览和设置，右边终端。打开 `dist/GongchuangClient.exe`，选 SSH 别名并连接，画面服务会按需启动。画面上方显示阶段或正在运行的测试节点名。首次使用需在香橙派编译工作区。Windows 只需系统 OpenSSH 客户端和本机 SSH 配置。

| 别名 | 用途 |
| --- | --- |
| `pio` | 无线局域网直连 |
| `pio-relay` | 云服务器中转 |
| `pio-wired` | 网线直连 |

客户端通过系统 OpenSSH 读取当前用户的 `%USERPROFILE%/.ssh/config`，包括地址、SSH 端口、密钥和跳板设置。客户端自动转发派上的预览端口 18080，界面只需选择别名并点击「连接」。

队友各自生成密钥，将公钥交给管理员添加到香橙派。用 `ssh -G pio-wired` 检查实际地址，用 `ssh pio-wired hostname` 验证登录。首次连接在终端核对主机指纹。无线和中转同理，切换为对应别名。

「测试节点」菜单列出 ROS 节点原名。选 `approach_test_node` 会启动 YOLO 和靠近测试，使用 `assets/models/train5.rknn`。误差发到 `/approach_test/command`。选 `camera_test_node` 会记录分辨率和实际帧率。客户端的靠近测试会发布运动命令，再由模拟串口打包。点「结束测试」回到原图。摄像头以 YUYV、10 fps 采图。

右侧「串口」页按一行一帧显示最近 100 帧十六进制数据。`TX` 是发出，`RX` 是收到的有效帧，`TX [SIM]` 是模拟模式下打包的帧。

SSH 终端会把输入命令和收到的标准输出、错误输出写到本机。下一次连接会覆盖记录，可以随时删除。

```powershell
Get-Content "$env:LOCALAPPDATA/Gongchuang/GongchuangClient/ssh-terminal.log" -Encoding utf8 -Wait -Tail 30
```

「无视频输入」表示派上预览服务在线，但最近两秒没有收到新帧。「正在重连视频」表示服务还有新帧，客户端正在重新打开视频流。断帧排查可同时看香橙派的 USB 取帧日志和 HTTP 状态。一键启动通过 `tools/preview_fastdds.xml` 给本机 ROS 图像传输预留共享内存。派上的启动和取帧日志可用 `journalctl _SYSTEMD_USER_UNIT=gongchuang-preview.service -n 30 --no-pager` 查看。

## 构建

原型用 Qt 6.12.0（MinGW 64 位）编译。关闭客户端后，在 PowerShell 构建：

```powershell
./tools/laptop_server/build.ps1 -Qt D:/MySoftware/QT/6.12.0/mingw_64 -MinGW D:/MySoftware/QT/Tools/mingw1310_64
```
