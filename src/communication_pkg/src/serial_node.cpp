#include <array>
#include <chrono>
#include <cerrno>
#include <cstdint>
#include <fcntl.h>
#include <poll.h>
#include <stdexcept>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>
#include <vector>
#include <rclcpp/rclcpp.hpp>
#include <communication_pkg/msg/command.hpp>
#include <communication_pkg/msg/feedback.hpp>
#include <communication_pkg/msg/state.hpp>

using namespace std::chrono_literals;
using Command = communication_pkg::msg::Command;
using Feedback = communication_pkg::msg::Feedback;
using State = communication_pkg::msg::State;
using Frame = std::array<uint8_t,6>;

static uint8_t checksum(const uint8_t *data) {
  return data[0] + data[1] + data[2] + data[3] + data[4];
}

class SerialNode : public rclcpp::Node {
public:
  SerialNode() : Node("serial_node") {
    const auto device = declare_parameter("device", "/dev/ttyS6");
    state_pub_ = create_publisher<State>("robot/state", rclcpp::QoS(1).transient_local());
    feedback_ = create_publisher<Feedback>("robot/feedback", 10);
    sub_ = create_subscription<Command>("robot/command", 10, [this](const Command &message) {
      if (state_.connected && message.code == 0) {
        last_command_ = std::chrono::steady_clock::now();
        return;
      }
      if (!state_.connected || message.code < 1 || message.code > 6 ||
          (message.code == 3 && (message.value < 0 || message.value > 1)) ||
          (message.code == 4 && (message.value < 0 || message.value > 80))) return;
      if (message.code == 5 && ::tcflush(fd_, TCIFLUSH) != 0) { disconnect(); return; }
      if (message.code == 5) input_.clear();
      if (!send(message.code, message.value)) {
        disconnect();
        return;
      }
      if (message.code == 4 && (!state_.camera_known || state_.camera_deg != message.value)) {
        state_.camera_known = true;
        state_.camera_deg = message.value;
        state_.camera_changed = now();
        state_pub_->publish(state_);
      }
      if (message.code == 1 || message.code == 2 || message.code == 5) moving_ = true;
      if (message.code == 6) moving_ = false;
      last_command_ = std::chrono::steady_clock::now();
    });
    timer_ = create_wall_timer(10ms, [this] { read(); });
    fd_ = ::open(device.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
    termios config{};
    if (fd_ < 0 || ioctl(fd_, TIOCEXCL) != 0 || tcgetattr(fd_, &config) != 0) {
      disconnect();
      throw std::runtime_error("[Serial] 无法独占串口 " + device);
    }
    cfmakeraw(&config);
    config.c_cflag |= CLOCAL | CREAD;
    cfsetispeed(&config, B115200);
    cfsetospeed(&config, B115200);
    if (tcsetattr(fd_, TCSANOW, &config) != 0 || !send(6, 0) || !send(1, 0)) {
      disconnect();
      throw std::runtime_error("[Serial] 无法初始化串口 " + device);
    }
    state_.connected = true;
    state_pub_->publish(state_);
    RCLCPP_INFO(get_logger(), "[Serial] %s 115200", device.c_str());
  }
  ~SerialNode() override {
    if (fd_ >= 0) {
      send(6, 0);
      ::close(fd_);
    }
  }

private:
  bool send(uint8_t code, int16_t value) {
    const uint16_t raw = static_cast<uint16_t>(value);
    Frame frame{0xaa, 0x55, code, uint8_t(raw), uint8_t(raw >> 8), 0};
    frame.back() = checksum(frame.data());
    for (size_t sent = 0; sent < frame.size();) {
      const auto count = ::write(fd_, frame.data() + sent, frame.size() - sent);
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

  void disconnect() {
    if (fd_ >= 0) {
      if (state_.connected) send(6, 0);
      ::close(fd_);
    }
    fd_ = -1;
    state_.connected = false;
    state_pub_->publish(state_);
  }

  void read() {
    if (fd_ < 0) return;
    if (moving_ && std::chrono::steady_clock::now() - last_command_ > 750ms) {
      if (!send(6, 0)) { disconnect(); return; }
      moving_ = false;
    }
    uint8_t data[256];
    const auto count = ::read(fd_, data, sizeof(data));
    if (count < 0 && errno != EAGAIN && errno != EINTR) { disconnect(); return; }
    if (count <= 0) return;
    input_.insert(input_.end(), data, data + count);
    while (input_.size() >= 6) {
      if (input_[0] != 0xaa || input_[1] != 0x55 || input_[5] != checksum(input_.data())) {
        input_.erase(input_.begin());
        continue;
      }
      Feedback message;
      message.code = input_[2];
      const int raw = input_[3] | (input_[4] << 8);
      message.value = static_cast<int16_t>(raw < 32768 ? raw : raw - 65536);
      input_.erase(input_.begin(), input_.begin() + 6);
      feedback_->publish(message);
      if (message.code == 1 && (message.value == 0 || message.value == 1)) {
        state_.team = message.value == 0 ? "red" : "blue";
        state_pub_->publish(state_);
      }
    }
  }

  int fd_{-1};
  bool moving_{false};
  std::chrono::steady_clock::time_point last_command_{};
  State state_;
  std::vector<uint8_t> input_;
  rclcpp::Publisher<State>::SharedPtr state_pub_;
  rclcpp::Publisher<Feedback>::SharedPtr feedback_;
  rclcpp::Subscription<Command>::SharedPtr sub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  try {
    rclcpp::spin(std::make_shared<SerialNode>());
  } catch (const std::exception &error) {
    RCLCPP_ERROR(rclcpp::get_logger("Serial"), "%s", error.what());
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
}
