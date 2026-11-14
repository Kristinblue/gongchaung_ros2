"""
my_ct_protocol.py
 定长协议
 结构：帧头(2B) + CMD(1B) + 数据(nB) + 校验(1B)
 核心逻辑：发送固定 TX_LEN，接收固定 RX_LEN
"""

class SimpleProtocol:
    SOF = b'\xAA\x55'        # 双帧头
    TX_LEN = 6              #  相机发送给单片机的固定总长度
    RX_LEN = 6               #  相机接收单片机的固定总长度


    @staticmethod
    def pack(cmd: bytes, data: bytes) -> bytes:
        """打包定长协议帧。
         这里的 cmd 必须是 1 字节。
         数据位长度会根据 TX_LEN 自动截断或补零。
        """
        #  计算数据位应有的固定长度：总长 - 帧头(2) - CMD(1) - 校验(1)
        data_fixed_len = SimpleProtocol.TX_LEN - 2 - 1 - 1
        
        #  1. 处理数据位：补齐或截断
        payload = bytearray(data) #bytes字节数组，创建后不可修改，bytearray可修改
        #Payload（有效载荷） 指数据传输或操作中承载实际功能或信息的主体部分，
        #与协议头、元数据等辅助内容区分。
        if len(payload) < data_fixed_len:
            payload.extend(b'\x00' * (data_fixed_len - len(payload)))
        else:
            payload = payload[:data_fixed_len]
        
        #  2. 拼接：头(2) + CMD(1) + 数据(2)
        #  注意：cmd[0:1] 确保只取第一个字节
        frame_pre = SimpleProtocol.SOF + cmd[0:1] + payload
        
        #  3. 计算校验和 (累加前 TX_LEN - 1 个字节)
        checksum = sum(frame_pre) & 0xFF
        
        #  4. 返回 6 字节完整帧
        return bytes(frame_pre + bytes([checksum]))

    @staticmethod
    def unpack(frame: bytes) -> tuple[bytes, bytes] | None:
        """解包一完整定长帧。
         严格校验 RX_LEN 长度。
         检验失败返回None
        """
        #  1. 长度校验
        if len(frame) != SimpleProtocol.RX_LEN:
            return None
    
        #  2. 帧头校验
        if frame[0:2] != SimpleProtocol.SOF:
            return None
        
        #  3. 校验和验证
        #  累加前 (RX_LEN - 1) 个字节
        received_checksum = frame[-1]
        calc_checksum = sum(frame[:-1]) & 0xFF
        
        if calc_checksum != received_checksum:
            return None

        #  4. 提取 CMD(1字节) 和 数据位
        #  结构：头(0,1), CMD(2), 数据(3...末尾-1), 校验(末尾)
        cmd = frame[2:3]
        data = frame[3:-1]

        return cmd, data


class ProtocolParser:
    """
    流式解析器：从字节流中提取固定长度 RX_LEN 的帧
    """
    def __init__(self):
        """初始化解析器，缓冲区为空。"""
        self._buffer = bytearray()

    def feed(self, data: bytes):
        """喂入新收到的字节数据，只是放入缓冲区"""
        self._buffer.extend(data)   

    def parse(self) -> tuple[bytes, bytes] | None:
        """尝试从缓冲区解析一帧。
         使用滑动窗口寻找双帧头，并截取固定 RX_LEN。
        """
        while len(self._buffer) >= SimpleProtocol.RX_LEN:
            pos = self._buffer.find(SimpleProtocol.SOF)

            if pos == -1:
                # 没找到完整帧头，保留末尾可能跨批次的 AA
                if self._buffer.endswith(b'\xAA'):
                    del self._buffer[:-1]
                else:
                    self._buffer.clear()

                return None

            if pos > 0:
                # 删除帧头前的垃圾数据
                del self._buffer[:pos]

                # 删除垃圾后，剩余数据可能已经不足一帧。
                # 回到 while 条件重新判断长度。
                continue #这个非常重要，而不是拿着切除后的数据继续判断

            # 运行到这里能够确定：
            # 1. 缓冲区长度至少为 RX_LEN
            # 2. 缓冲区从 AA 55 开始
            candidate = bytes(
                self._buffer[:SimpleProtocol.RX_LEN]
            )

            result = SimpleProtocol.unpack(candidate)

            if result is not None:
                del self._buffer[:SimpleProtocol.RX_LEN]
                return result

            # 当前帧头无法组成有效帧，只排除第一个 AA
            del self._buffer[0]

        return None
