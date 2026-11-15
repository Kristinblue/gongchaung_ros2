#include "communication_pkg/my_ct_protocol.hpp"
#include "communication_pkg/my_uart.hpp"

#include <chrono>
#include <cstdint>
#include <stdexcept>
#include <rclcpp/rclcpp.hpp>
#include <robot_interfaces/msg/command.hpp>
#include <robot_interfaces/msg/feedback.hpp>
#include <robot_interfaces/msg/state.hpp>

using namespace std::chrono_literals;
using Command = robot_interfaces::msg::Command;
using Feedback = robot_interfaces::msg::Feedback;
using State = robot_interfaces::msg::State;

// ROS 和下位机之间的桥。发动作走 robot/command，回包走 robot/feedback。
class SerialNode : public rclcpp::Node {
public:
  SerialNode() : Node("serial_node") {
    const auto device = declare_parameter("uart.device", "/dev/ttyS6");
    const auto baudrate = declare_parameter("uart.baudrate", 115200);
    const auto max_pitch_deg = declare_parameter("max_pitch_deg", 80);
    if (max_pitch_deg < 0 || max_pitch_deg > 80) throw std::invalid_argument("[Serial] max_pitch_deg 要在 0～80 之间");
    // 保留最后一条状态，感知和任务节点晚一点启动也可以收到当前队伍、串口状态等。
    state_pub_ = create_publisher<State>("robot/state", rclcpp::QoS(1).transient_local());
    feedback_ = create_publisher<Feedback>("robot/feedback", 10);
    // callback：收到 MyCMD 的命令，交给下面的 command_callback()。
    sub_ = create_subscription<Command>("robot/command", 10, [this, max_pitch_deg](const Command &message) {
      command_callback(message, max_pitch_deg);
    });
    // callback：每 10 ms 调 read() 检查回包。非阻塞打开串口，没数据时立即返回。
    timer_ = create_wall_timer(10ms, [this] { read(); });
    if (!my_uart_.open(device, baudrate) || !send(6, 0) || !send(1, 0)) {
      disconnect();
      throw std::runtime_error("[Serial] 无法初始化串口 " + device);
    }
    state_.connected = true;
    state_pub_->publish(state_);
    RCLCPP_INFO(get_logger(), "[Serial] %s %s", device.c_str(), std::to_string(baudrate).c_str());
  }
  ~SerialNode() override {
    if (my_uart_.is_open()) send(6, 0);
  }

private:
  // 收到 MyCMD 发布的动作后，检查参数，再按协议写串口。
  // code=0 是 ROS 心跳，只更新时间，串口不会发出这条指令。
  void command_callback(const Command &message, int64_t max_pitch_deg) {
    if (!state_.connected) return;
    if (message.code == 0) {
      last_command_ = std::chrono::steady_clock::now();
      return;
    }
    if (message.code < 1 || message.code > 6 ||
        (message.code == 3 && (message.value < 0 || message.value > 1)) ||
        (message.code == 4 && (message.value < 0 || message.value > max_pitch_deg))) return;
    // 开始一次新的相对转向前，把串口和解析器中积压的字节清掉，免得读到旧的转向完成反馈。
    if (message.code == 5) {
      if (!my_uart_.clear_input()) {
        disconnect();
        return;
      }
      parser_.clear();
    }
    if (!send(message.code, message.value)) {
      disconnect();
      return;
    }
    // 这里记录的是发给舵机的目标角度和时间。感知节点根据时间等相机画面稳定。
    if (message.code == 4 && (!state_.camera_known || state_.camera_deg != message.value)) {
      state_.camera_known = true;
      state_.camera_deg = message.value;
      state_.camera_changed = now();
      state_pub_->publish(state_);
    }
    if (message.code == 1 || message.code == 2 || message.code == 5) moving_ = true;
    if (message.code == 6) moving_ = false;
    last_command_ = std::chrono::steady_clock::now();
  }

  // SimpleProtocol 打包，MyUART 只负责把字节写出去。
  bool send(uint8_t code, int16_t value) {
    const auto frame = SimpleProtocol::pack(code, value);
    return my_uart_.write(frame.data(), frame.size());
  }

  void disconnect() {
    if (my_uart_.is_open() && state_.connected) send(6, 0);
    my_uart_.close();
    state_.connected = false;
    state_pub_->publish(state_);
  }

  void read() {
    if (!my_uart_.is_open()) return;
    // 运动期间超过 750 ms 没有收到动作或心跳，由串口节点发停车。
    if (moving_ && std::chrono::steady_clock::now() - last_command_ > 750ms) {
      if (!send(6, 0)) { disconnect(); return; }
      moving_ = false;
    }
    uint8_t data[256];
    const auto count = my_uart_.read(data, sizeof(data));
    if (count < 0) { disconnect(); return; }
    if (count == 0) return;
    parser_.feed(data, count);
    while (auto packet = parser_.parse()) {
      Feedback message;
      message.code = packet->code;
      message.value = packet->value;
      feedback_->publish(message);
      if (message.code == 1 && (message.value == 0 || message.value == 1)) {
        state_.team = message.value == 0 ? "red" : "blue";
        state_pub_->publish(state_);
      } else if (message.code == 2 && message.value >= 0 && message.value <= 360 &&
                 (!state_.angle_known || state_.angle_deg != message.value)) {
        state_.angle_deg = message.value;
        state_.angle_known = true;
        state_pub_->publish(state_);
      }
    }
  }

  MyUART my_uart_;
  ProtocolParser parser_;
  bool moving_{false};
  std::chrono::steady_clock::time_point last_command_{};
  State state_;
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
