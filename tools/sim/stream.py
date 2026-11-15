"""把工创仿真画面推成 MJPEG 视频流，给 ROS 的 camera_node 当 http 摄像头。

Windows 上运行，自己启动仿真后端（Godot + WSL 物理）。
WSL 里用 tools/sim/run_sim.sh 启动，脚本会把 Windows 主机地址填进 camera_url。
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import radians
from pathlib import Path

import cv2

DEFAULT_APP = Path(r"D:\my_project\gongchuang\my_project")
# 强杀 stream.py 时仿真宿主可能变成孤儿，启动前按命令行清一遍
CLEAN_STALE = ("ps -eo pid,args | "
               "awk '/[a]lgorithm_world\\.sdf|[g]ripper_algorithm_host/ {print $1}' | "
               "xargs -r kill -9")


def clean_stale():
    """清掉上一次没退干净的 Gazebo/物理宿主，返回清掉的进程数。"""
    try:
        result = subprocess.run(['wsl', '-e', 'bash', '-lc', CLEAN_STALE],
                                capture_output=True, text=True, timeout=10)
    except OSError:
        return 0
    return len([line for line in result.stdout.splitlines() if line.strip()])



def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, default=DEFAULT_APP, help='原工程 my_project 目录')
    parser.add_argument('--bind', default='0.0.0.0', help='HTTP 监听地址')
    parser.add_argument('--port', type=int, default=8090, help='MJPEG 端口')
    parser.add_argument('--control-port', type=int, default=8091, help='STM32 指令控制端口')
    parser.add_argument('--fps', type=float, default=15, help='取帧频率')
    parser.add_argument('--pitch', type=float, default=24, help='镜头俯角，0 水平、向下为正')
    parser.add_argument('--quality', type=int, default=85, help='JPEG 质量')
    parser.add_argument('--only-block', default='', help='只显示这个物块，例如 block_green_01')
    return parser.parse_args()


class Frames:
    """只保留最新一帧，多个 HTTP 连接各自取。"""

    def __init__(self):
        self.condition = threading.Condition()
        self.jpeg = None
        self.count = 0

    def put(self, jpeg):
        with self.condition:
            self.jpeg = jpeg
            self.count += 1
            self.condition.notify_all()

    def latest(self, after):
        """等一帧新的；超时就把现有帧原样返回。"""
        with self.condition:
            self.condition.wait_for(lambda: self.count != after, timeout=5)
            return self.jpeg, self.count


class Control:
    """接收假 STM32 转发来的指令，转成仿真后端的 D / C / G。"""

    def __init__(self, port, client, mapping):
        self.client = client
        self.mapping = mapping
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(('0.0.0.0', port))
        self.server.listen(1)

    def serve(self):
        while True:
            connection, _ = self.server.accept()
            with connection:
                with connection.makefile('r', encoding='utf-8') as stream:
                    for line in stream:
                        self.handle(line.strip())

    def handle(self, line):
        parts = line.split()
        try:
            if parts[0] == 'D' and len(parts) == 3:
                self.client.command(f'D {float(parts[1]):.4f} {float(parts[2]):.4f}')
            elif parts[0] == 'C' and len(parts) == 2:
                degrees = max(0.0, min(self.mapping['camera_max_deg'], float(parts[1])))
                joint = self.mapping['camera_joint_0'] + radians(degrees)
                self.client.command(f'C {joint:.6f}')
            elif parts[0] == 'G' and len(parts) == 2:
                self.client.command(f'G {1 if int(parts[1]) else 0}')
        except (ValueError, OSError):
            pass


class Handler(BaseHTTPRequestHandler):
    frames = None

    def do_GET(self):
        if self.path == '/':
            self.reply_text('Gongchuang sim MJPEG：/video 是视频流，/status 是帧数。\n')
        elif self.path == '/status':
            self.reply_text(json.dumps({'frames': self.frames.count}) + '\n', 'application/json')
        elif self.path == '/video':
            self.stream()
        else:
            self.send_error(404)

    def reply_text(self, text, content_type='text/plain; charset=utf-8'):
        body = text.encode()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def stream(self):
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        seen = 0
        try:
            while True:
                jpeg, seen = self.frames.latest(seen)
                if jpeg is None:
                    continue
                self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n')
                self.wfile.write(f'Content-Length: {len(jpeg)}\r\n\r\n'.encode())
                self.wfile.write(jpeg)
                self.wfile.write(b'\r\n')
        except OSError:
            return

    def log_message(self, *args):
        pass


def host_address():
    """WSL 看 Windows 用的地址，和 tools/sim/run_sim.sh 里一致。"""
    try:
        result = subprocess.run(
            ['wsl', '-e', 'bash', '-lc', "ip route show default | awk '{print $3}'"],
            capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except OSError:
        return ''


def main():
    args = parse_args()
    sys.path.insert(0, str(args.app_root))
    from tools.sim.gripper_backend import GripperBackend, camera_mapping

    mapping = camera_mapping()
    pitch = max(0.0, min(args.pitch, mapping['camera_max_deg']))
    joint = mapping['camera_joint_0'] + radians(pitch)
    frames = Frames()
    Handler.frames = frames
    if args.only_block:
        # 给 Godot 侧开关用，只显示一个物块
        os.environ['GC_ONLY_BLOCK'] = args.only_block
    stale = clean_stale()
    if stale:
        print(f'[SimStream] 清掉 {stale} 个上次残留的仿真进程', flush=True)
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f'[SimStream] 视频流 http://{args.bind}:{args.port}/video', flush=True)
    backend = GripperBackend(threading.Event())
    print('[SimStream] 启动仿真，首次约 30 秒', flush=True)
    client = backend.start()
    try:
        # 中位看到的是白地面，先用固定俯角对准场上的物块。
        client.command(f'C {joint:.6f}')
        control = Control(args.control_port, client, mapping)
        threading.Thread(target=control.serve, daemon=True).start()
        print(f'[SimStream] 控制端口 {args.control_port}，相机俯角 {pitch:g} 度，'
              f'Windows 地址 {host_address() or "未知"}', flush=True)
        period = 1 / args.fps
        count = 0
        while True:
            start = time.monotonic()
            _, image = client.frame()
            ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, args.quality])
            if ok:
                frames.put(encoded.tobytes())
                count += 1
                if count % 100 == 0:
                    print(f'[SimStream] 已推送 {count} 帧', flush=True)
            delay = period - (time.monotonic() - start)
            if delay > 0:
                time.sleep(delay)
    except KeyboardInterrupt:
        print('[SimStream] 手动停止', flush=True)
    finally:
        backend.close()
        server.shutdown()
        print('[SimStream] 已关闭仿真', flush=True)


if __name__ == '__main__':
    main()
