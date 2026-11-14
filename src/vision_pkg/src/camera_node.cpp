#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <string>
#include <thread>
#include <opencv2/opencv.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>

class CameraNode : public rclcpp::Node {
public:
  CameraNode() : Node("camera_node") {
    const auto device = declare_parameter("device", "/dev/video0");
    const auto width = declare_parameter("width", 1280);
    const auto height = declare_parameter("height", 720);
    const auto fps = declare_parameter("fps", 60);
    const auto url = declare_parameter("url", "");
    publisher_ = create_publisher<sensor_msgs::msg::Image>("camera/image", rclcpp::SensorDataQoS().keep_last(1));
    worker_ = std::thread([=] {
      while (!stop_ && rclcpp::ok()) {
        try {
          cv::VideoCapture capture;
          if (url.empty()) {
            capture.open(device, cv::CAP_V4L2);
            capture.set(cv::CAP_PROP_FOURCC, cv::VideoWriter::fourcc('M','J','P','G'));
            capture.set(cv::CAP_PROP_FRAME_WIDTH, width);
            capture.set(cv::CAP_PROP_FRAME_HEIGHT, height);
            capture.set(cv::CAP_PROP_FPS, fps);
          } else {
            capture.open(url, cv::CAP_FFMPEG,
              {cv::CAP_PROP_OPEN_TIMEOUT_MSEC, 3000, cv::CAP_PROP_READ_TIMEOUT_MSEC, 3000});
          }
          cv::Mat frame;
          while (!stop_ && rclcpp::ok() && capture.read(frame)) {
            if (frame.type() != CV_8UC3) continue;
            if (!frame.isContinuous()) frame = frame.clone();
            sensor_msgs::msg::Image message;
            message.header.stamp = now();
            message.header.frame_id = "camera";
            message.width = frame.cols;
            message.height = frame.rows;
            message.encoding = "bgr8";
            message.step = frame.cols * 3;
            message.data.assign(frame.data, frame.data + message.step * message.height);
            publisher_->publish(std::move(message));
          }
        } catch (const std::exception &error) {
          if (!stop_ && rclcpp::ok()) RCLCPP_WARN(get_logger(), "[Camera] %s", error.what());
        }
        if (!stop_ && rclcpp::ok()) {
          RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, "[Camera] 等待图像：%s", url.empty() ? device.c_str() : "HTTP");
          std::this_thread::sleep_for(std::chrono::seconds(1));
        }
      }
    });
  }
  ~CameraNode() override {
    stop_ = true;
    worker_.join();
  }

private:
  std::atomic<bool> stop_{false};
  std::thread worker_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr publisher_;
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<CameraNode>());
  rclcpp::shutdown();
}
