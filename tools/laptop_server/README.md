# Windows 客户端

解压 `GongchuangClient.zip` 后双击 `GongchuangClient.exe`。先在 WSL 或香橙派运行 `bash tools/run.sh`，客户端填写服务端口 18080。

- 本地预览直接连接 WSL。点击「浏览器摄像头」可以用电脑摄像头提供画面。
- 有线 SSH 与阿里云中转使用系统 OpenSSH。默认别名为 `pio`、`pio-relay`，也可以输入 `orangepi@地址`。先在系统终端确认 SSH 连接和密钥可用。
- 「SSH 命令」支持运行一条命令并显示输出。可用 `hostname` 验证连接。每次执行都建立独立会话。
- YOLO 在线时可以调整置信度。界面设置立即生效，重启后读取启动参数。

使用 Qt 6 和配套的 MinGW，关闭客户端后在 PowerShell 构建和打包：

```powershell
./tools/laptop_server/build.ps1 -Qt D:/MySoftware/QT/6.12.0/mingw_64 -MinGW D:/MySoftware/QT/Tools/mingw1310_64
```

ZIP 生成在本目录，含 Qt 运行库和插件。远程连接使用各自电脑上的 SSH 配置和密钥。
