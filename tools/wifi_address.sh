#!/usr/bin/env bash
# 输出当前已连接的 Wi-Fi 的 IPv4，供云端地址查询使用。
set -euo pipefail
wifi=$(nmcli -t -f DEVICE,TYPE,STATE device status | awk -F: '$2=="wifi" && $3=="connected" {print $1; exit}')
if [[ -n "$wifi" ]]; then
  ip=$(ip -o -4 addr show dev "$wifi" scope global | awk 'NR==1 {split($4,a,"/"); print a[1]}')
  if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf '{"wifi_ip":"%s"}\n' "$ip"
    exit 0
  fi
fi
printf '{"wifi_ip":null}\n'
