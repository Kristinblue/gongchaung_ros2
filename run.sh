#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")"
source /opt/ros/humble/setup.bash
source install/local_setup.bash
if [[ -f .venv/bin/activate ]]; then source .venv/bin/activate; fi
exec ros2 launch desktop_server_pkg robot.launch.py "$@"
