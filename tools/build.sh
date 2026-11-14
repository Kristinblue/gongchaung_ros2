#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source /opt/ros/humble/setup.bash
colcon --log-base tools/logs/colcon build --base-paths src --symlink-install --parallel-workers 2 --cmake-args -DCMAKE_BUILD_TYPE=Release
