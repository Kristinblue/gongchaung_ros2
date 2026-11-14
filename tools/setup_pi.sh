#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
wheel=${1:?用法: bash tools/setup_pi.sh /path/to/rknn_toolkit_lite2.whl [train5.rknn]}
python3 -m venv --system-site-packages tools/.venv
tools/.venv/bin/python -m pip install "numpy<2" "$wheel"
tools/.venv/bin/python -c 'import cv2, numpy; from rknnlite.api import RKNNLite'
if [[ $# -ge 2 ]]; then
  mkdir -p tools/models
  cp -n -- "$2" tools/models/train5.rknn
fi
