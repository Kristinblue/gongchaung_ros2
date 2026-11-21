"""香橙派地址登记服务。部署在 HTTPS 反向代理之后。"""
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, HTTPServer
from ipaddress import IPv4Address, IPv4Network
import json
import os
import time

TOKEN = os.environ['GONGCHUANG_DISCOVERY_TOKEN'].encode()
if len(TOKEN) < 32:
    raise ValueError('上报令牌至少 32 字节')
NETWORKS = tuple(map(IPv4Network, ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')))
TTL = 90


class Discovery(BaseHTTPRequestHandler):
    wifi_ip = None
    expires = 0

    def reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != '/gongchuang/address':
            self.reply(404, {})
            return
        self.reply(200, {'wifi_ip': self.wifi_ip if time.monotonic() < self.expires else None})

    def do_POST(self):
        if self.path != '/gongchuang/address':
            self.reply(404, {})
            return
        authorization = self.headers.get('Authorization', '').encode()
        if not compare_digest(authorization, b'Bearer ' + TOKEN):
            self.reply(403, {})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 256:
                raise ValueError()
            ip = json.loads(self.rfile.read(length))['wifi_ip']
            if ip is not None:
                address = IPv4Address(ip)
                if not isinstance(ip, str) or not any(address in net for net in NETWORKS):
                    raise ValueError()
                ip = str(address)
        except (KeyError, TypeError, ValueError):
            self.reply(400, {})
            return
        Discovery.wifi_ip = ip
        Discovery.expires = time.monotonic() + TTL
        self.reply(200, {'ok': True})


class Server(HTTPServer):
    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(3)
        return sock, address


if __name__ == '__main__':
    with Server(('127.0.0.1', int(os.environ.get('GONGCHUANG_DISCOVERY_PORT', '18181'))), Discovery) as server:
        server.serve_forever()
