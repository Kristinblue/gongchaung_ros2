"""将串口收发放入子线程。
通用的串口类，移植过来的

对于发送数据子线程， 生产者是put_bytes(外部调用，或者sendfmt那里调用),
消费者是_sender_task(内部的牛马， 不管他)

tests里面有测试demo
"""

import queue
import struct
import threading

# 安装包名是 pyserial，但该库规定在 Python 中使用 serial 作为导入名。
import serial

from .my_ct_protocol import ProtocolParser, SimpleProtocol


class MyUART:
    """串口通信管理类。
    使用子线程异步收发数据，并集成定长协议的打包与解析。
    """

    def __init__(self, baudrate: int = 115200, device: str = "/dev/ttyS6") -> None:
        """初始化串口并启动收发线程。

        Args:
            baudrate: 波特率，默认 115200。
            device: Linux 串口设备文件，默认 ``/dev/ttyS6``。
        """
        self.baudrate = baudrate
        self.device = device
        self.serial_dev = None
        self._closed = threading.Event()

        # 只保留最新一帧，避免旧控制量在队列中积压。
        self._send_queue = queue.Queue(maxsize=1)
        # 接收数据可能被 read() 分成多块，不能只保留一个数据块。
        self._recv_queue = queue.Queue()
        self._parser = ProtocolParser()

        # 打开失败时 pyserial 会直接抛出 serial.SerialException。
        self._my_uart_init(baudrate, device)

        self._sender = threading.Thread(target=self._sender_task, daemon=True)
        self._receiver = threading.Thread(target=self._receiver_task, daemon=True)
        self._sender.start()
        self._receiver.start()

        print(f"[MyUART] 串口已打开：{device}，波特率：{baudrate}")

    def _my_uart_init(self, baudrate: int, device: str) -> None:
        """使用 pyserial 打开串口。

        Args:
            baudrate: 波特率。
            device: Linux 串口设备文件。
        """
        # serial.Serial() 属于第三方 pyserial 库，返回打开后的串口对象。
        # 8N1 表示 8 数据位、无校验（None）、1 停止位。
        self.serial_dev = serial.Serial(
            port=device,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS, #每个UART字符包含8个数据位
            parity=serial.PARITY_NONE, #Parity，奇偶校验；`PARITY_NONE` 表示不校验
            # 即115200 8N1
            stopbits=serial.STOPBITS_ONE,#停止位数量，这里为1
            timeout=0.1, #读取超时，s
            write_timeout=0.5, #发送超时，s
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

    def _sender_task(self) -> None:
        """循环取出发送队列中的数据并写入串口。"""
        while not self._closed.is_set():
            try:
                msg = self._send_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                # write() 属于 pyserial，参数为 bytes，返回写入的字节数。
                written = self.serial_dev.write(msg)
                if written != len(msg):
                    print(f"[MyUART] 数据未完整发送：{written}/{len(msg)} 字节")
            except serial.SerialException as error:
                if not self._closed.is_set():
                    print(f"[MyUART] 串口发送失败：{error}")
                self._closed.set()

    def put_bytes(self, msg: bytes) -> None:
        """将最新字节数据放入发送队列。如果你要单纯发字节的话可以用这个

        Args:
            msg: 要发送的字节串。

        Raises:
            TypeError: ``msg`` 不是 ``bytes``。
            RuntimeError: 串口已经停止或关闭。
        """
        # 先检查
        if not isinstance(msg, bytes):
            raise TypeError("msg 必须是 bytes")
        if self._closed.is_set():
            raise RuntimeError("串口已经停止或关闭")

        # 队列满时移除尚未发送的旧数据，再放入最新数据。
        while True:
            try:
                self._send_queue.put_nowait(msg)
                break
            except queue.Full:
                try:
                    self._send_queue.get_nowait()
                except queue.Empty:
                    pass

    def _receiver_task(self) -> None:
        """持续读取串口并把原始字节放入接收队列。"""
        while not self._closed.is_set():
            try:
                # in_waiting 属于 pyserial，返回接收缓冲区已有的字节数。
                waiting = self.serial_dev.in_waiting
                data = self.serial_dev.read(waiting or 1)
            except serial.SerialException as error:
                if not self._closed.is_set():
                    print(f"[MyUART] 串口接收失败：{error}")
                self._closed.set()
                continue

            if not data:
                continue

            self._recv_queue.put_nowait(data)

    def get_received(self) -> bytes | None:
        """非阻塞获取一块串口原始数据。

        Returns:
            收到的字节串；当前没有数据时返回 ``None``。
        """
        try:
            return self._recv_queue.get_nowait()
        except queue.Empty:
            return None



    """
    接下来是针对定长协议进行打包、提取帧和解析数据流。
    """

    def send_fmt_message(self, cmd: bytes, data: int | tuple | None, fmt: str = "<h") -> None:
        """按照指定格式打包并发送协议帧。

        Args:
            cmd: 一字节命令 ID。
            data: 整数、整数元组或 ``None``。
            fmt: Python 标准库 ``struct`` 的格式字符串。默认 ``"<h"``，
                ``<`` 表示小端字节序，``h`` 表示有符号 16 位整数。
            现在协议数据区为 2 字节，适合发送 0~65535 或有符号
            16 位整数。
        """
        if data is None:
            frame = SimpleProtocol.pack(cmd, b"")
        else:
            try:
                if isinstance(data, tuple):
                    fmt_data = struct.pack(fmt, *data)
                else:
                    fmt_data = struct.pack(fmt, data)
                frame = SimpleProtocol.pack(cmd, fmt_data)
            except (struct.error, TypeError) as error:
                print(f"[MyUART] 打包失败：{error}")
                return

        self.put_bytes(frame)

    def parse_received(self) -> list[tuple[bytes, bytes]]:
        """解析接收队列中当前已有的全部完整帧。

        Returns:
            ``(命令 ID, 数据字节串)`` 元组组成的列表；没有完整帧时返回
            空列表。
        """
        frames = []

        while True:
            raw = self.get_received()
            if not raw:
                break
            self._parser.feed(raw)

        while True:
            result = self._parser.parse()
            if not result:
                break
            frames.append(result)

        return frames
    def close(self, timeout: float = 1.0) -> None:
        """停止收发线程并关闭串口，可重复调用。"""
        self._closed.set()
        self._sender.join(timeout)
        self._receiver.join(timeout)
        if self._sender.is_alive() or self._receiver.is_alive():
            raise RuntimeError("[MyUART] 关闭超时，收发线程仍未退出")

        if self.serial_dev and self.serial_dev.is_open:
            self.serial_dev.close()
            print("[MyUART] 串口已关闭")
