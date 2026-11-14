#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source /opt/ros/humble/setup.bash
source install/local_setup.bash
if [[ -x tools/.venv/bin/python3 ]]; then
  export VIRTUAL_ENV="$PWD/tools/.venv"
  export PATH="$VIRTUAL_ENV/bin:$PATH"
fi
exec ros2 launch desktop_server_pkg robot.launch.py "$@"
