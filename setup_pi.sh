#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")"
wheel=${1:?用法: bash setup_pi.sh /path/to/rknn_toolkit_lite2.whl [train5.rknn]}
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install "numpy<2" "$wheel"
.venv/bin/python -c 'import cv2, numpy; from rknnlite.api import RKNNLite'
if [[ $# -ge 2 ]]; then
  mkdir -p models
  cp -n -- "$2" models/train5.rknn
fi
