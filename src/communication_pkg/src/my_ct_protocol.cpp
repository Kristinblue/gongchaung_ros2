#include "communication_pkg/my_ct_protocol.hpp"

// 前 5 个字节相加，返回 uint8_t，只保留和的低 8 位。
static uint8_t checksum(const uint8_t *data) {
  return data[0] + data[1] + data[2] + data[3] + data[4];
}

SimpleProtocol::Frame SimpleProtocol::pack(uint8_t code, int16_t value) {
  const uint16_t raw = static_cast<uint16_t>(value);
  Frame frame{0xaa, 0x55, code, uint8_t(raw), uint8_t(raw >> 8), 0};
  frame.back() = checksum(frame.data());
  return frame;
}

std::optional<SimpleProtocol::Message> SimpleProtocol::unpack(const uint8_t *data, std::size_t size) {
  if (size != Frame{}.size() || data[0] != 0xaa || data[1] != 0x55 || data[5] != checksum(data)) {
    return std::nullopt;
  }
  // 高字节左移 8 位再和低字节合并，还原协议里的有符号数。
  const int raw = data[3] | (data[4] << 8);
  return Message{data[2], static_cast<int16_t>(raw < 32768 ? raw : raw - 65536)};
}

void ProtocolParser::feed(const uint8_t *data, std::size_t size) {
  // 每次 read() 的字节数与协议帧无关。先拼到缓存，凑够 6 字节才尝试解析。
  input_.insert(input_.end(), data, data + size);
}

std::optional<SimpleProtocol::Message> ProtocolParser::parse() {
  constexpr auto frame_size = SimpleProtocol::Frame{}.size();
  while (input_.size() >= frame_size) {
    if (auto message = SimpleProtocol::unpack(input_.data(), frame_size)) {
      input_.erase(input_.begin(), input_.begin() + frame_size);
      return message;
    }
    // 帧头或校验对不上，就往后挪一个字节继续找。
    input_.erase(input_.begin());
  }
  return std::nullopt;
}

void ProtocolParser::clear() {
  input_.clear();
}
