#include "communication_pkg/my_uart.hpp"

#include <cerrno>
#include <fcntl.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

MyUART::~MyUART() {
  close();
}

bool MyUART::open(const std::string &device, int64_t baudrate) {
  // 这些是 Linux termios 提供的波特率常量。
  speed_t speed;
  switch (baudrate) {
    case 9600: speed = B9600; break;
    case 19200: speed = B19200; break;
    case 38400: speed = B38400; break;
    case 57600: speed = B57600; break;
    case 115200: speed = B115200; break;
    case 230400: speed = B230400; break;
    default: return false;
  }

  close();
  fd_ = ::open(device.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
  termios config{};
  if (fd_ < 0 || ioctl(fd_, TIOCEXCL) != 0 || tcgetattr(fd_, &config) != 0) {
    close();
    return false;
  }

  // 按原始字节读写，避免系统像处理终端输入那样解释换行等字符。
  cfmakeraw(&config);
  config.c_cflag |= CLOCAL | CREAD;
  if (cfsetispeed(&config, speed) != 0 || cfsetospeed(&config, speed) != 0 ||
      tcsetattr(fd_, TCSANOW, &config) != 0) {
    close();
    return false;
  }
  return true;
}

bool MyUART::is_open() const {
  return fd_ >= 0;
}

bool MyUART::write(const uint8_t *data, std::size_t size) {
  // 一次 write() 可能只写出部分数据，所以记住已经写了多少。
  for (std::size_t sent = 0; sent < size;) {
    const auto count = ::write(fd_, data + sent, size - sent);
    if (count > 0) {
      sent += count;
    } else if (count < 0 && (errno == EAGAIN || errno == EINTR)) {
      pollfd output{fd_, POLLOUT, 0};
      if (::poll(&output, 1, 20) <= 0) return false;
    } else {
      return false;
    }
  }
  return true;
}

ssize_t MyUART::read(uint8_t *data, std::size_t size) {
  const auto count = ::read(fd_, data, size);
  if (count < 0 && (errno == EAGAIN || errno == EINTR)) return 0;
  return count;
}

bool MyUART::clear_input() {
  return ::tcflush(fd_, TCIFLUSH) == 0;
}

void MyUART::close() {
  if (fd_ >= 0) ::close(fd_);
  fd_ = -1;
}
