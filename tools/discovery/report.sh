#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
url=${GONGCHUANG_DISCOVERY_URL:?请设置 HTTPS 上报地址}
token=${GONGCHUANG_DISCOVERY_TOKEN:?请设置上报令牌}
[[ "$url" == https://* && "$token" =~ ^[A-Za-z0-9_-]{32,}$ ]]
while true; do
  if payload=$(bash "$root/wifi_address.sh"); then
    # 令牌从标准输入传给 curl，避免出现在命令参数中。
    printf 'header = "Authorization: Bearer %s"\n' "$token" |
      curl --config - --proto '=https' --silent --show-error --fail --max-time 8 \
        -H 'Content-Type: application/json' --data-binary "$payload" "$url" >/dev/null || true
  fi
  sleep 30
done
