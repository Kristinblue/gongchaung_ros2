#!/usr/bin/env bash
set -euo pipefail

# 允许从任意目录运行，也可以通过 ~/.local/bin 下的软链接运行。
script=$(readlink -f -- "${BASH_SOURCE[0]}")
cd "$(dirname "$script")/.."
unit=gongchuang-preview

case "${1:-start}" in
  start)
    if systemctl --user is-active --quiet "$unit.service"; then
      echo "预览已经启动"
      exit 0
    fi
    if [[ ! -f install/local_setup.bash ]]; then
      echo "请先运行 bash "$PWD/tools/build.sh"" >&2
      exit 1
    fi
    systemd-run --user --unit="$unit" --collect --working-directory="$PWD" \
      /bin/bash "$PWD/tools/run.sh" source:=usb mode:=preview
    ;;
  stop)
    systemctl --user stop "$unit.service"
    ;;
  status)
    systemctl --user status "$unit.service" --no-pager
    ;;
  *)
    echo "用法: bash $script [start|stop|status]" >&2
    exit 2
    ;;
esac
