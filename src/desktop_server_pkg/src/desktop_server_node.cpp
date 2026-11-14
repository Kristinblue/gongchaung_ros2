#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <fstream>
#include <future>
#include <optional>
#include <cmath>
#include <memory>
#include <mutex>
#include <thread>
#include <ament_index_cpp/get_package_share_directory.hpp>
#include <opencv2/opencv.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <std_msgs/msg/string.hpp>
#include <communication_pkg/msg/state.hpp>
#include <vision_pkg/msg/objects.hpp>
#include <rcl_interfaces/srv/get_parameters.hpp>
#include <rcl_interfaces/srv/set_parameters_atomically.hpp>
#include "httplib.h"

using namespace std::chrono_literals;
using Image = sensor_msgs::msg::Image;
using Objects = vision_pkg::msg::Objects;
using RobotState = communication_pkg::msg::State;
using ReadSettings = rcl_interfaces::srv::GetParameters;
using WriteSettings = rcl_interfaces::srv::SetParametersAtomically;

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
    read_settings_ = create_client<ReadSettings>("yolo_node/get_parameters");
    write_settings_ = create_client<WriteSettings>("yolo_node/set_parameters_atomically");
    robot_ = create_subscription<RobotState>("robot/state", rclcpp::QoS(1).transient_local(),
      [this](const RobotState &state) {
        std::lock_guard lock(mutex_);
        camera_angle_ = state.camera_known ? std::optional<int>{state.camera_deg} : std::nullopt;
      });
    target_ = create_subscription<Objects>("task/target", rclcpp::SensorDataQoS().keep_last(1),
      [this](Objects::ConstSharedPtr message) {
        std::lock_guard lock(mutex_);
        selected_ = std::move(message);
      });
    status_ = create_subscription<std_msgs::msg::String>("task/state", rclcpp::QoS(1).transient_local(),
      [this](const std_msgs::msg::String &message) {
        std::lock_guard lock(mutex_);
        status_text_ = message.data;
        const auto start = message.data.find("\"stage\":\"");
        if (start != std::string::npos) {
          const auto end = message.data.find('"', start + 9);
          stage_ = message.data.substr(start + 9, end - (start + 9));
        }
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
    server_.set_socket_options([](socket_t socket) {
      int enabled = 1;
      setsockopt(socket, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char *>(&enabled), sizeof(enabled));
    });
    server_.new_task_queue = [] { return new httplib::ThreadPool(8, 8, 16); };
    server_.set_payload_max_length(512 * 1024);
    server_.set_read_timeout(3, 0);
    server_.set_write_timeout(2, 0);
    server_.Get("/", [](const auto &, auto &response) {
      std::ifstream file(ament_index_cpp::get_package_share_directory("desktop_server_pkg") + "/web/index.html");
      response.set_content(std::string(std::istreambuf_iterator<char>(file), {}), "text/html; charset=utf-8");
    });
    server_.Get("/status", [this, source](const auto &, auto &response) {
      const auto confidence = read_confidence();
      std::lock_guard lock(mutex_);
      auto json = "{\"camera_source\":\"" + source + "\",\"jpeg_quality\":" +
        std::to_string(quality_.load()) + ",\"task\":" + status_text_;
      if (confidence) json += ",\"confidence\":" + std::to_string(*confidence);
      response.set_content(json + "}", "application/json");
    });
    server_.Post("/settings", [this](const auto &request, auto &response) {
      if (!request.has_header("X-Gongchuang-Client") ||
          (!request.has_param("jpeg_quality") && !request.has_param("confidence"))) {
        response.status = 400;
        return;
      }
      try {
        int quality = quality_;
        if (request.has_param("jpeg_quality")) {
          const auto value = request.get_param_value("jpeg_quality");
          size_t end = 0;
          quality = std::stoi(value, &end);
          if (end != value.size() || quality < 25 || quality > 90) throw std::invalid_argument("quality");
        }
        std::optional<double> confidence;
        if (request.has_param("confidence")) {
          const auto value = request.get_param_value("confidence");
          size_t end = 0;
          confidence = std::stod(value, &end);
          if (end != value.size() || !std::isfinite(*confidence) || *confidence < 0 || *confidence > 1)
            throw std::invalid_argument("confidence");
          if (!write_confidence(*confidence)) {
            response.status = 503;
            response.set_content("{\"error\":\"YOLO 未确认设置，刷新状态后重试\"}", "application/json");
            return;
          }
        }
        if (request.has_param("jpeg_quality")) quality_ = quality;
        auto json = "{\"jpeg_quality\":" + std::to_string(quality_.load());
        if (confidence) json += ",\"confidence\":" + std::to_string(*confidence);
        response.set_content(json + "}", "application/json");
      } catch (const std::exception &) {
        response.status = 400;
        response.set_content("{\"error\":\"JPEG 质量须为 25～90，置信度须为 0～1\"}", "application/json");
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
  std::optional<double> read_confidence() {
    if (!read_settings_->service_is_ready()) return std::nullopt;
    auto request = std::make_shared<ReadSettings::Request>();
    request->names = {"confidence"};
    auto result = read_settings_->async_send_request(request);
    if (result.wait_for(400ms) != std::future_status::ready) {
      read_settings_->remove_pending_request(result);
      return std::nullopt;
    }
    const auto reply = result.get();
    if (reply->values.size() != 1 || reply->values[0].type != rcl_interfaces::msg::ParameterType::PARAMETER_DOUBLE)
      return std::nullopt;
    return reply->values[0].double_value;
  }

  bool write_confidence(double confidence) {
    if (!write_settings_->service_is_ready()) return false;
    auto request = std::make_shared<WriteSettings::Request>();
    request->parameters.push_back(rclcpp::Parameter("confidence", confidence).to_parameter_msg());
    auto result = write_settings_->async_send_request(request);
    if (result.wait_for(1500ms) != std::future_status::ready) {
      write_settings_->remove_pending_request(result);
      return false;
    }
    return result.get()->result.successful;
  }

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
    bool last_target = false;
    std::string last_stage;
    std::optional<int> last_angle;
    while (!stop_) {
      const auto next = std::chrono::steady_clock::now() + 100ms;
      Image::ConstSharedPtr image;
      Objects::ConstSharedPtr selected;
      std::string stage;
      std::optional<int> angle;
      {
        std::lock_guard lock(mutex_);
        image = newest_;
        selected = selected_;
        stage = stage_;
        angle = camera_angle_;
      }
      const int quality = quality_;
      const bool has_target = image && stage == "track" && selected &&
        selected->header.stamp == image->header.stamp && !selected->items.empty();
      if (image && (image != last || quality != last_quality || has_target != last_target ||
          stage != last_stage || angle != last_angle) && image->encoding == "bgr8" &&
          image->width && image->height && image->step >= image->width * 3 &&
          image->data.size() >= static_cast<size_t>(image->step) * image->height) {
        try {
          cv::Mat frame(image->height, image->width, CV_8UC3,
            const_cast<unsigned char *>(image->data.data()), image->step);
          cv::Mat small;
          const double scale = std::min({1.0, double(width) / frame.cols, double(height) / frame.rows});
          cv::resize(frame, small, {}, scale, scale, cv::INTER_AREA);
          std::string display_stage = stage == "search" ? "goto / S1 search" : stage;
          if (stage == "track") {
            display_stage = "goto / S2 track";
            if (has_target) {
              const auto &item = selected->items.front();
              const cv::Point upper(cvRound(item.x1*scale), cvRound(item.y1*scale));
              const cv::Point lower(cvRound(item.x2*scale), cvRound(item.y2*scale));
              cv::rectangle(small, upper, lower, {0,255,255}, 2);
              cv::putText(small, "target", {upper.x, std::max(15, upper.y-3)}, cv::FONT_HERSHEY_SIMPLEX, .48, {0,255,255}, 1);
            }
          }
          if (!display_stage.empty()) cv::putText(small, display_stage, {8,18}, cv::FONT_HERSHEY_SIMPLEX, .5, {30,210,250}, 1, cv::LINE_AA);
          if (angle) cv::putText(small, "cam_angle: " + std::to_string(*angle), {8,38},
            cv::FONT_HERSHEY_SIMPLEX, .5, {30,210,250}, 1, cv::LINE_AA);
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
        last_target = has_target;
        last_stage = stage;
        last_angle = angle;
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
  std::string stage_;
  std::optional<int> camera_angle_;
  Objects::ConstSharedPtr selected_;
  rclcpp::Client<ReadSettings>::SharedPtr read_settings_;
  rclcpp::Client<WriteSettings>::SharedPtr write_settings_;
  rclcpp::Subscription<RobotState>::SharedPtr robot_;
  rclcpp::Subscription<Objects>::SharedPtr target_;
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
