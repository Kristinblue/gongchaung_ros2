"""检查香橙派 HTTP 预览；通过 SSH 转发后也能运行。"""
import argparse
import json
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18080')
    parser.add_argument('--no-video', action='store_true')
    args = parser.parse_args()
    with urlopen(args.url + '/status', timeout=5) as response:
        status = json.load(response)
    assert status['video_available'] == (not args.no_video), status
    if args.no_video:
        print('通过：服务在线，无视频输入。')
        return
    with urlopen(args.url + '/video', timeout=5) as stream:
        assert 'multipart/x-mixed-replace' in stream.headers['Content-Type']
        for _ in range(4):
            assert stream.readline() == b'--frame\r\n'
            assert b'image/jpeg' in stream.readline()
            length = int(stream.readline().split(b':')[1])
            assert stream.readline() == b'\r\n'
            jpeg = stream.read(length)
            assert jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9')
            assert stream.read(2) == b'\r\n'
    print('通过：收到 4 张 JPEG 预览。')


if __name__ == '__main__':
    main()
