#include <algorithm>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <vector>
#include <opencv2/core/utils/logger.hpp>
#include <stdexcept>
#include <string>
#include <thread>
#include <opencv2/opencv.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>

// 参数是 auto 时优先找 USB 摄像头的主视频接口（index0），找不到再试 /dev/video0。
static std::string camera_device(const std::string &configured) {
  if (configured != "auto") return configured;
  std::vector<std::string> devices;
  std::error_code error;
  for (auto it = std::filesystem::directory_iterator("/dev/v4l/by-id", error);
       !error && it != std::filesystem::directory_iterator(); it.increment(error)) {
    const auto name = it->path().filename().string();
    if (name.rfind("usb-", 0) == 0 && name.find("-video-index0") != std::string::npos)
      devices.push_back(it->path().string());
  }
  std::sort(devices.begin(), devices.end());
  return devices.empty() ? "/dev/video0" : devices.front();
}

// 从 USB 相机或 HTTP 视频源取图，把原始画面发到 camera/image。
class CameraNode : public rclcpp::Node {
public:
  CameraNode() : Node("camera_node") {
    cv::utils::logging::setLogLevel(cv::utils::logging::LOG_LEVEL_SILENT);
    const auto device = declare_parameter("device", "auto");
    const auto width = declare_parameter("width", 1280);
    const auto height = declare_parameter("height", 720);
    const auto fps = declare_parameter("FPS", 60);
    const auto FOURCC = declare_parameter<std::string>("FOURCC", "MJPG");
    if (FOURCC.size() != 4) throw std::invalid_argument("[Camera] FOURCC 需要四个字符");
    const auto url = declare_parameter("url", "");
    // 图像队列只留 1 帧。下游忙时丢掉旧帧，预览和追踪都能尽快拿到新画面。
    publisher_ = create_publisher<sensor_msgs::msg::Image>("camera/image", rclcpp::SensorDataQoS().keep_last(1));
    // 读摄像头可能阻塞，所以单独开线程。相机没接上或读不到帧时，每隔一秒重试。
    worker_ = std::thread([=] {
      while (!stop_ && rclcpp::ok()) {
        try {
          cv::VideoCapture capture;
          const auto path = url.empty() ? camera_device(device) : std::string{};
          if (url.empty() && capture.open(path, cv::CAP_V4L2)) {
            capture.set(cv::CAP_PROP_FOURCC, cv::VideoWriter::fourcc(FOURCC[0], FOURCC[1], FOURCC[2], FOURCC[3]));
            capture.set(cv::CAP_PROP_FRAME_WIDTH, width);
            capture.set(cv::CAP_PROP_FRAME_HEIGHT, height);
            capture.set(cv::CAP_PROP_FPS, fps);
          } else if (!url.empty()) {
            capture.open(url, cv::CAP_FFMPEG,
              {cv::CAP_PROP_OPEN_TIMEOUT_MSEC, 3000, cv::CAP_PROP_READ_TIMEOUT_MSEC, 3000});
          }
          cv::Mat frame;
          while (!stop_ && rclcpp::ok() && capture.read(frame)) {
            if (frame.type() != CV_8UC3) continue;
            // 下面要一次复制整张图。若 OpenCV 的每行之间有空隙，先复制成连续内存。
            if (!frame.isContinuous()) frame = frame.clone();
            // 这里生成的时间戳会跟着原图和 YOLO 结果走，感知节点靠它配对。
            // bgr8 每像素 3 字节，step 是 ROS 消息里一行占用的字节数。
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
          if (!stop_ && rclcpp::ok()) RCLCPP_DEBUG(get_logger(), "[Camera] %s", error.what());
        }
        if (!stop_ && rclcpp::ok()) {
          std::this_thread::sleep_for(std::chrono::seconds(1));
        }
      }
    });
  }
  // 先通知采图线程退出，再等它结束，避免线程继续使用已经销毁的节点。
  ~CameraNode() override {
    stop_ = true;
    worker_.join();
  }

private:
  // 主线程写、采图线程读，用 atomic 让两边可以安全访问这个开关。
  std::atomic<bool> stop_{false};
  std::thread worker_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr publisher_;
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<CameraNode>());
  rclcpp::shutdown();
}
