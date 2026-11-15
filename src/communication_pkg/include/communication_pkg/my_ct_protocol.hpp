#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

class SimpleProtocol {
public:
  // 下位机协议一帧固定 6 字节：AA 55 | 命令 | 数值低位 高位 | 校验。
  using Frame = std::array<uint8_t, 6>;

  struct Message {
    uint8_t code;
    int16_t value;
  };

  static Frame pack(uint8_t code, int16_t value);
  static std::optional<Message> unpack(const uint8_t *data, std::size_t size);
};

class ProtocolParser {
public:
  void feed(const uint8_t *data, std::size_t size);
  std::optional<SimpleProtocol::Message> parse();
  void clear();

private:
  std::vector<uint8_t> input_;
};
