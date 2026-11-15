#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <sys/types.h>

// MyUART：把 Linux 串口（/dev/ttyS6、/dev/ttyUSB0 这类设备文件）包成一个类。
//
// 这一层只负责“打开、读、写、清缓存、关闭”，不关心字节是什么含义；
// 协议打包在 SimpleProtocol 里，ROS 话题和看门狗在 serial_node 里。
// 这样串口细节和业务逻辑分开，换板子或换串口只动这一个文件。
//
// 用法：作为 serial_node 的成员变量，构造函数里 open()，析构自动 close()。
class MyUART {
public:
  // 构造时不碰硬件，必须先调用 open() 才会真正打开串口。
  MyUART() = default;
  // 析构时自动 close()，所以 serial_node 不需要手动关。
  ~MyUART();
  // 禁止拷贝：fd_ 代表一个独占的串口，拷贝后两个对象会 close 同一个 fd。
  MyUART(const MyUART &) = delete;
  MyUART &operator=(const MyUART &) = delete;

  // 打开串口并配置成原始字节模式。
  // device 例如 "/dev/ttyS6"；baudrate 只支持 9600～230400 的常用值。
  // 成功返回 true；失败返回 false（内部会关掉 fd），不抛异常。
  bool open(const std::string &device, int64_t baudrate);
  // 串口是否处于打开状态，等价于 fd_ >= 0。
  bool is_open() const;
  // 把 size 个字节全部写出去，内部会处理“一次只写出一部分”的情况。
  // 返回 false 表示串口出错或超时，调用方应该断开连接。
  bool write(const uint8_t *data, std::size_t size);
  // 非阻塞读，最多读 size 个字节。
  // 返回值 >0 是实际读到的字节数，0 表示暂时没数据，<0 表示串口出错。
  ssize_t read(uint8_t *data, std::size_t size);
  // 丢掉串口接收缓冲区里还没读的旧字节，开始新的相对转向前会用到。
  bool clear_input();
  // 关闭串口；重复调用是安全的。
  void close();

private:
  // Linux 用 fd_ 这个整数代表已打开的串口，-1 表示没有打开。
  int fd_{-1};
};
