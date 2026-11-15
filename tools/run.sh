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
if [[ ${1:-} == serial ]]; then
  export ROS_DOMAIN_ID=28 ROS_LOCALHOST_ONLY=1
  bridge_param=simulate:=true
  if [[ -n ${2:-} ]]; then
    bridge_param="uart.device:=$2"
  fi
  serial_prefix=$(ros2 pkg prefix communication_pkg)
  "$serial_prefix/lib/communication_pkg/serial_node" --ros-args -p "$bridge_param" &
  serial_pid=$!
  trap 'kill "$serial_pid" 2>/dev/null || true; wait "$serial_pid" 2>/dev/null || true' EXIT
  ros2 run tests_pkg serial_test_node
  exit
fi
launch=robot.launch.py
if [[ ${1:-} == approach ]]; then
  launch=approach_test.launch.py
  shift
fi
exec ros2 launch robot_launch "$launch" "$@"
