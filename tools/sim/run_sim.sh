#!/usr/bin/env bash
# 用 Windows 上的仿真视频流启动 ROS，地址自动解析，不用手填 IP。
set -eo pipefail
cd "$(dirname "$0")/../.."
host=$(ip route show default | awk '{print $3}')
if [[ -z $host ]]; then
  echo "[run_sim] 找不到 Windows 主机地址，确认 WSL 网络正常" >&2
  exit 1
fi
exec bash tools/run.sh source:=http camera_url:="http://$host:${SIM_PORT:-8090}/video" "$@"
