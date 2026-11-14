#include <chrono>
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>
#include <std_srvs/srv/trigger.hpp>
#include <communication_pkg/msg/command.hpp>
#include <communication_pkg/msg/feedback.hpp>
#include <communication_pkg/msg/state.hpp>
#include "go_to.hpp"

using namespace std::chrono_literals;
using Clock = std::chrono::steady_clock;
using Trigger = std_srvs::srv::Trigger;
using Command = communication_pkg::msg::Command;

class Task : public rclcpp::Node {
public:
  Task() : Node("task_node"), go_to_([this](uint8_t code, int16_t value) { send(code, value); }) {
    move_ms_ = declare_parameter("move_ms", 5000);
    scatter_ms_ = declare_parameter("scatter_ms", 7000);
    move_ = declare_parameter("base_forward", -100);
    scatter_ = declare_parameter("scatter_forward", -125);
    turn_ = declare_parameter("base_turn", 281);
    auto &p = go_to_.config;
    p.x = declare_parameter("x0", 640.);
    p.y = declare_parameter("y0", 550.);
    p.cam1 = declare_parameter("search_camera_1", 30);
    p.cam2 = declare_parameter("search_camera_2", 20);
    p.first = declare_parameter("first", true);
    p.confirm = declare_parameter("confirm_frames", 3);
    p.tolerance = declare_parameter("align_px", 20);
    commands_ = create_publisher<Command>("robot/command", 10);
    status_ = create_publisher<std_msgs::msg::String>("task/state", rclcpp::QoS(1).transient_local());
    state_ = create_subscription<communication_pkg::msg::State>("robot/state", rclcpp::QoS(1).transient_local(),
      [this](const communication_pkg::msg::State &state) {
        if (!state.connected && active_) stop();
        connected_ = state.connected;
        team_ = state.team;
      });
    feedback_ = create_subscription<communication_pkg::msg::Feedback>("robot/feedback", 10,
      [this](const communication_pkg::msg::Feedback &event) {
        if (event.code == 5 && event.value == 1) turn_done_ = true;
      });
    objects_ = create_subscription<GoTo::Objects>("vision/objects", rclcpp::SensorDataQoS().keep_last(1),
      [this](const GoTo::Objects &frame) { on_frame(frame); });
    start_ = create_service<Trigger>("task/start", [this](Trigger::Request::SharedPtr, Trigger::Response::SharedPtr reply) {
      if (!connected_ || active_ || Clock::now() - last_frame_ > 500ms) {
        reply->message = "需串口在线、新检测帧且任务处于停止状态";
        return;
      }
      send(6, 0);
      send(3, 1);
      started_ = Clock::now();
      go_to_.reset();
      active_ = true;
      publish("init_dis");
      reply->success = true;
    });
    halt_ = create_service<Trigger>("task/stop", [this](Trigger::Request::SharedPtr, Trigger::Response::SharedPtr reply) {
      stop();
      reply->success = true;
    });
    watchdog_ = create_wall_timer(100ms, [this] {
      if (!active_) return;
      if (Clock::now() - last_frame_ > 500ms) stop();
      else send(0, 0);
    });
    publish("stop");
  }

private:
  void on_frame(const GoTo::Objects &frame) {
    const auto age = (now() - rclcpp::Time(frame.header.stamp, get_clock()->get_clock_type())).seconds();
    if (age < 0 || age > .5 || rclcpp::Time(frame.header.stamp) <= last_stamp_) return;
    last_stamp_ = rclcpp::Time(frame.header.stamp);
    last_frame_ = Clock::now();
    if (!active_) return;
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(last_frame_ - started_).count();
    if (elapsed < move_ms_ + scatter_ms_) {
      const bool scatter = elapsed >= move_ms_;
      send(1, scatter ? scatter_ : move_);
      send(2, scatter ? turn_ : 0);
    } else if (go_to_.run(frame, team_, turn_done_)) {
      stop();
    } else {
      publish(go_to_.stage);
    }
  }

  void send(uint8_t code, int16_t value) {
    Command message;
    message.code = code;
    message.value = value;
    if (code == 5 || code == 6) turn_done_ = false;
    commands_->publish(message);
  }

  void stop() {
    send(6, 0);
    active_ = false;
    publish("stop");
  }

  void publish(const std::string &stage) {
    if (stage == stage_) return;
    stage_ = stage;
    std_msgs::msg::String message;
    message.data = "{\"stage\":\"" + stage + "\"}";
    status_->publish(message);
    RCLCPP_INFO(get_logger(), "[Task] %s", stage.c_str());
  }

  GoTo go_to_;
  std::string team_, stage_;
  bool active_{false}, connected_{false}, turn_done_{false};
  int move_ms_, scatter_ms_, move_, scatter_, turn_;
  Clock::time_point started_{}, last_frame_{};
  rclcpp::Time last_stamp_{0,0,RCL_ROS_TIME};
  rclcpp::Publisher<Command>::SharedPtr commands_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr status_;
  rclcpp::Subscription<communication_pkg::msg::State>::SharedPtr state_;
  rclcpp::Subscription<communication_pkg::msg::Feedback>::SharedPtr feedback_;
  rclcpp::Subscription<GoTo::Objects>::SharedPtr objects_;
  rclcpp::Service<Trigger>::SharedPtr start_, halt_;
  rclcpp::TimerBase::SharedPtr watchdog_;
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<Task>());
  rclcpp::shutdown();
}
