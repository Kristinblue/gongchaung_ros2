# Windows 客户端原型

白色界面，左边预览和设置，右边终端。打开 `dist/GongchuangClient.exe`，选 SSH 别名并连接，再点「启动预览」。首次使用需在香橙派编译工作区。Windows 只需系统 OpenSSH 客户端和本机 SSH 配置。

| 别名 | 用途 |
| --- | --- |
| `pio` | 无线局域网直连 |
| `pio-relay` | 云服务器中转 |
| `pio-wired` | 网线直连 |

客户端通过系统 OpenSSH 读取当前用户的 `%USERPROFILE%/.ssh/config`，包括地址、SSH 端口、密钥和跳板设置。客户端自动转发派上的预览端口 18080，界面只需选择别名并点击「连接」。

队友各自生成密钥，将公钥交给管理员添加到香橙派。用 `ssh -G pio-wired` 检查实际地址，用 `ssh pio-wired hostname` 验证登录。首次连接在终端核对主机指纹。无线和中转同理，切换为对应别名。

预览在香橙派后台运行，关闭客户端后可重新连接。要停止预览，在右侧终端执行 `systemctl --user stop gongchuang-preview.service`。启动日志可用 `journalctl _SYSTEMD_USER_UNIT=gongchuang-preview.service -n 30 --no-pager` 查看。

未接摄像头时显示「无视频输入」。YOLO 在线时可以调整置信度，「SSH 命令」使用当前别名执行单条命令。

## 构建

原型用 Qt 6.12.0（MinGW 64 位）编译。关闭客户端后，在 PowerShell 构建：

```powershell
./tools/laptop_server/build.ps1 -Qt D:/MySoftware/QT/6.12.0/mingw_64 -MinGW D:/MySoftware/QT/Tools/mingw1310_64
```
