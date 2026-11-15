/*
hyf

*/
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
  // 不用数字直接赋值，是因为不同平台/驱动要求用 Bxxx 宏。
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

  // 先关掉可能已经打开的旧串口，避免 fd 泄漏。
  close();
  // O_RDWR 读写；O_NOCTTY 不把串口当成进程的控制终端；
  // O_NONBLOCK 非阻塞，read() 没数据时立刻返回，不会卡住 ROS 的定时器。
  fd_ = ::open(device.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
  termios config{};
  if (fd_ < 0 || ioctl(fd_, TIOCEXCL) != 0 || tcgetattr(fd_, &config) != 0) {
    // TIOCEXCL 让别的进程不能再打开同一个串口，防止两个节点抢串口。
    close();
    return false;
  }

  // 按原始字节读写，避免系统像处理终端输入那样解释换行等字符。
  cfmakeraw(&config);
  // CLOCAL：忽略调制解调器控制线；CREAD：允许接收。
  config.c_cflag |= CLOCAL | CREAD;
  // 分别设置输入、输出波特率，然后一次性写回驱动。
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
      // EAGAIN：发送缓冲区满了，等最多 20 ms 再试。
      // EINTR：被信号打断，重试即可。
      pollfd output{fd_, POLLOUT, 0};
      if (::poll(&output, 1, 20) <= 0) return false;
    } else {
      // 其他错误（比如串口被拔掉）直接失败，让调用方断开。
      return false;
    }
  }
  return true;
}

ssize_t MyUART::read(uint8_t *data, std::size_t size) {
  // 非阻塞模式：没有数据时 read() 返回 -1 且 errno 是 EAGAIN，这里当成“读到 0 个字节”。
  const auto count = ::read(fd_, data, size);
  if (count < 0 && (errno == EAGAIN || errno == EINTR)) return 0;
  return count;
}

bool MyUART::clear_input() {
  // TCIFLUSH：只清“已经收到但还没读走”的输入缓存，不影响还没发完的数据。
  return ::tcflush(fd_, TCIFLUSH) == 0;
}

void MyUART::close() {
  if (fd_ >= 0) ::close(fd_);
  fd_ = -1;
}
