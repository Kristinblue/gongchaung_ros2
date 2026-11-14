#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <fstream>
#include <memory>
#include <mutex>
#include <thread>
#include <ament_index_cpp/get_package_share_directory.hpp>
#include <opencv2/opencv.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <std_msgs/msg/string.hpp>
#include "httplib.h"

using namespace std::chrono_literals;
using Image = sensor_msgs::msg::Image;

class DesktopServer : public rclcpp::Node {
public:
  DesktopServer() : Node("desktop_server_node") {
    const auto host = declare_parameter("host", "127.0.0.1");
    const int port = declare_parameter("port", 8080);
    const auto source = declare_parameter("camera_source", "usb");
    browser_ = source == "browser";
    if (!browser_ && source != "usb" && source != "http") throw std::invalid_argument("camera_source");
    const auto width = declare_parameter("preview_width", 640);
    const auto height = declare_parameter("preview_height", 360);
    quality_ = declare_parameter("jpeg_quality", 65);
    if (port < 1 || port > 65535 || width < 1 || height < 1 || quality_ < 25 || quality_ > 90)
      throw std::invalid_argument("HTTP port, preview dimensions or JPEG quality");
    status_ = create_subscription<std_msgs::msg::String>("task/state", rclcpp::QoS(1).transient_local(),
      [this](const std_msgs::msg::String &message) {
        std::lock_guard lock(mutex_);
        status_text_ = message.data;
      });
    input_ = create_subscription<Image>("vision/preview", rclcpp::SensorDataQoS().keep_last(1),
      [this](Image::ConstSharedPtr image) {
        std::lock_guard lock(mutex_);
        newest_ = std::move(image);
      });

    if (browser_) {
      camera_ = create_publisher<Image>("camera/image", rclcpp::SensorDataQoS().keep_last(1));
      server_.Post("/camera", [this](const auto &request, auto &response) {
        if (!request.has_header("X-Gongchuang-Client") || request.get_header_value("Content-Type") != "image/jpeg") {
          response.status = 415;
          return;
        }
        std::unique_lock upload_lock(upload_mutex_, std::try_to_lock);
        if (!upload_lock || request.body.empty() || request.body.size() > 512 * 1024) {
          response.status = upload_lock ? 413 : 429;
          return;
        }
        if (std::chrono::steady_clock::now() - last_upload_ < 90ms) {
          response.status = 429;
          return;
        }
        try {
          auto image = decode(request.body);
          if (!image) {
            response.status = 400;
            return;
          }
          camera_->publish(*image);
          last_upload_ = std::chrono::steady_clock::now();
          response.status = 204;
        } catch (const cv::Exception &) {
          response.status = 400;
        }
      });
    }
    server_.new_task_queue = [] { return new httplib::ThreadPool(8, 8, 16); };
    server_.set_payload_max_length(512 * 1024);
    server_.set_read_timeout(3, 0);
    server_.set_write_timeout(2, 0);
    server_.Get("/", [](const auto &, auto &response) {
      std::ifstream file(ament_index_cpp::get_package_share_directory("desktop_server_pkg") + "/web/index.html");
      response.set_content(std::string(std::istreambuf_iterator<char>(file), {}), "text/html; charset=utf-8");
    });
    server_.Get("/status", [this, source](const auto &, auto &response) {
      std::lock_guard lock(mutex_);
      response.set_content("{\"camera_source\":\"" + source + "\",\"jpeg_quality\":" +
        std::to_string(quality_.load()) + ",\"task\":" + status_text_ + "}", "application/json");
    });
    server_.Post("/settings", [this](const auto &request, auto &response) {
      if (!request.has_header("X-Gongchuang-Client") || !request.has_param("jpeg_quality")) {
        response.status = 400;
        return;
      }
      try {
        const auto value = request.get_param_value("jpeg_quality");
        size_t end = 0;
        const int quality = std::stoi(value, &end);
        if (end != value.size() || quality < 25 || quality > 90) throw std::invalid_argument("quality");
        quality_ = quality;
        response.set_content("{\"jpeg_quality\":" + std::to_string(quality) + "}", "application/json");
      } catch (const std::exception &) {
        response.status = 400;
      }
    });
    server_.Get("/video", [this](const auto &, auto &response) {
      if (viewers_.fetch_add(1) >= 3) {
        --viewers_;
        response.status = 503;
        return;
      }
      response.set_header("Cache-Control", "no-store");
      response.set_chunked_content_provider("multipart/x-mixed-replace; boundary=frame",
        [this, seen = uint64_t{0}](size_t, httplib::DataSink &sink) mutable {
          std::shared_ptr<const std::vector<uchar>> jpeg;
          {
            std::unique_lock lock(mutex_);
            ready_.wait_for(lock, 1s, [&] { return stop_ || serial_ != seen; });
            if (stop_ || !sink.is_writable()) return false;
            if (serial_ == seen) return true;
            seen = serial_;
            jpeg = jpeg_;
          }
          const auto header = "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
            std::to_string(jpeg->size()) + "\r\n\r\n";
          return sink.write(header.data(), header.size()) &&
            sink.write(reinterpret_cast<const char *>(jpeg->data()), jpeg->size()) && sink.write("\r\n", 2);
        }, [this](bool) { --viewers_; });
    });
    if (!server_.bind_to_port(host, port)) throw std::runtime_error("无法监听 HTTP 端口");
    http_ = std::thread([this] { server_.listen_after_bind(); });
    encode_ = std::thread([=] { encode_loop(width, height); });
    RCLCPP_INFO(get_logger(), "[DesktopServer] http://%s:%d (%s)", host.c_str(), port, source.c_str());
  }

  ~DesktopServer() override {
    stop_ = true;
    ready_.notify_all();
    server_.stop();
    http_.join();
    encode_.join();
  }

private:
  Image::SharedPtr decode(const std::string &body) {
    const auto frame = cv::imdecode(std::vector<uchar>(body.begin(), body.end()), cv::IMREAD_COLOR);
    if (frame.empty() || frame.cols > 1920 || frame.rows > 1080) return {};
    auto image = std::make_shared<Image>();
    image->header.stamp = now();
    image->header.frame_id = "browser_camera";
    image->width = frame.cols;
    image->height = frame.rows;
    image->encoding = "bgr8";
    image->step = frame.cols * 3;
    image->data.assign(frame.data, frame.data + image->step * image->height);
    return image;
  }

  void encode_loop(int width, int height) {
    Image::ConstSharedPtr last;
    int last_quality = 0;
    while (!stop_) {
      const auto next = std::chrono::steady_clock::now() + 100ms;
      Image::ConstSharedPtr image;
      {
        std::lock_guard lock(mutex_);
        image = newest_;
      }
      const int quality = quality_;
      if (image && (image != last || quality != last_quality) && image->encoding == "bgr8" &&
          image->width && image->height && image->step >= image->width * 3 &&
          image->data.size() >= static_cast<size_t>(image->step) * image->height) {
        try {
          cv::Mat frame(image->height, image->width, CV_8UC3,
            const_cast<unsigned char *>(image->data.data()), image->step);
          cv::Mat small;
          const double scale = std::min({1.0, double(width) / frame.cols, double(height) / frame.rows});
          cv::resize(frame, small, {}, scale, scale, cv::INTER_AREA);
          auto jpeg = std::make_shared<std::vector<uchar>>();
          if (cv::imencode(".jpg", small, *jpeg, {cv::IMWRITE_JPEG_QUALITY, quality})) {
            {
              std::lock_guard lock(mutex_);
              jpeg_ = jpeg;
              ++serial_;
            }
            ready_.notify_all();
          }
        } catch (const cv::Exception &error) {
          RCLCPP_WARN(get_logger(), "[DesktopServer] %s", error.what());
        }
        last = image;
        last_quality = quality;
      }
      std::this_thread::sleep_until(next);
    }
  }

  httplib::Server server_;
  std::mutex mutex_, upload_mutex_;
  std::condition_variable ready_;
  std::atomic<bool> stop_{false};
  std::atomic<int> quality_{65}, viewers_{0};
  bool browser_{false};
  std::chrono::steady_clock::time_point last_upload_{};
  std::thread http_, encode_;
  Image::ConstSharedPtr newest_;
  std::shared_ptr<const std::vector<uchar>> jpeg_;
  uint64_t serial_{0};
  std::string status_text_{"{\"stage\":\"preview\"}"};
  rclcpp::Subscription<Image>::SharedPtr input_;
  rclcpp::Publisher<Image>::SharedPtr camera_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr status_;
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  try {
    rclcpp::spin(std::make_shared<DesktopServer>());
  } catch (const std::exception &error) {
    RCLCPP_ERROR(rclcpp::get_logger("DesktopServer"), "%s", error.what());
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
}
