"""开发验证：用 Windows 实际摄像头核对 HTTP 往返。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import time
from urllib.request import Request, urlopen

import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18080')
    parser.add_argument('--seconds', type=float, default=25.0)
    args = parser.parse_args()

    def request(path, data=None, content_type='application/x-www-form-urlencoded'):
        headers = {'X-Gongchuang-Client': 'verify', 'Content-Type': content_type}
        return urlopen(Request(args.url + path, data=data, headers=headers), timeout=15)

    def receive():
        with request('/video') as stream:
            assert 'multipart/x-mixed-replace' in stream.headers['Content-Type']
            matched = 0
            while matched < 4:
                assert stream.readline() == b'--frame\r\n'
                assert b'image/jpeg' in stream.readline()
                length = int(stream.readline().split(b':')[1])
                assert stream.readline() == b'\r\n'
                frame = cv2.imdecode(np.frombuffer(stream.read(length), np.uint8), cv2.IMREAD_COLOR)
                assert frame is not None
                matched += frame.shape[:2] == (360, 640)
                assert stream.read(2) == b'\r\n'

    with request('/status') as response:
        initial_quality = json.load(response)['jpeg_quality']
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    try:
        assert camera.isOpened(), '无法打开电脑摄像头'
        with request('/settings', b'jpeg_quality=57') as response:
            assert json.load(response)['jpeg_quality'] == 57
        with request('/status') as response:
            assert json.load(response)['jpeg_quality'] == 57
        with ThreadPoolExecutor(1) as pool:
            stream = pool.submit(receive)
            deadline = time.monotonic() + args.seconds
            uploads = 0
            while not stream.done() and time.monotonic() < deadline:
                ok, image = camera.read()
                assert ok
                ok, jpeg = cv2.imencode('.jpg', cv2.resize(image, (640, 360)))
                assert ok
                with request('/camera', jpeg.tobytes(), 'image/jpeg') as response:
                    assert response.status == 204
                uploads += 1
                time.sleep(.105)
            stream.result()
        print(f'通过：{uploads} 张实际摄像头图像上传、4 张 640×360 预览回传、设置读回。')
    finally:
        camera.release()
        with request('/settings', f'jpeg_quality={initial_quality}'.encode()):
            pass


if __name__ == '__main__':
    main()
