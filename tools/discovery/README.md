# 香橙派地址查询原型

候选地址是 `https://blueee.cn:18443/gongchuang/address`，独立使用 HTTPS 18443。地址服务和 Qt 客户端的 SSH 连接独立。

- 客户端可匿名 GET。派向同一路径带令牌 POST，只登记无线 IPv4。每 30 秒上报，90 秒未收到上报时查询返回空地址。
- 后端通过私有环境读取 `GONGCHUANG_DISCOVERY_TOKEN`，运行 `python3 server.py`，只监听 `127.0.0.1:18181`。反向代理使用 `nginx.conf.example`，启用前核对证书路径和云安全组。
- 派使用相同的上报令牌和 `GONGCHUANG_DISCOVERY_URL` 运行 `bash tools/discovery/report.sh`。令牌只保存在派和云端的私有环境文件。
- 查询服务尚未部署。Qt 客户端读取本机 SSH 配置，由其中的 `pio`、`pio-relay` 或 `pio-wired` 决定连接路径。
