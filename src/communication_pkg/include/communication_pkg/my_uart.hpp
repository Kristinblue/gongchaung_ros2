#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <sys/types.h>

class MyUART {
public:
  MyUART() = default;
  ~MyUART();
  MyUART(const MyUART &) = delete;
  MyUART &operator=(const MyUART &) = delete;

  bool open(const std::string &device, int64_t baudrate);
  bool is_open() const;
  bool write(const uint8_t *data, std::size_t size);
  ssize_t read(uint8_t *data, std::size_t size);
  bool clear_input();
  void close();

private:
  // Linux 用 fd_ 这个整数代表已打开的串口，-1 表示没有打开。
  int fd_{-1};
};
