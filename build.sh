#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")"
source /opt/ros/humble/setup.bash
colcon build --base-paths src --symlink-install --parallel-workers 2 --cmake-args -DCMAKE_BUILD_TYPE=Release
