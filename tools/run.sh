#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source /opt/ros/humble/setup.bash
source install/local_setup.bash
if [[ -x tools/.venv/bin/python3 ]]; then
  export VIRTUAL_ENV="$PWD/tools/.venv"
  export PATH="$VIRTUAL_ENV/bin:$PATH"
fi
export ROS_LOG_DIR="${ROS_LOG_DIR:-$PWD/tools/logs/ros}"
launch=robot.launch.py
if [[ ${1:-} == approach ]]; then
  launch=approach_test.launch.py
  shift
fi
exec ros2 launch robot_launch "$launch" "$@"
