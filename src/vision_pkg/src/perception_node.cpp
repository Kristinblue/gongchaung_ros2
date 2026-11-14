#include <algorithm>
#include <chrono>
#include <cmath>
#include <map>
#include <tuple>
#include <utility>
#include <vector>
#include <opencv2/opencv.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <communication_pkg/msg/state.hpp>
#include <vision_pkg/msg/objects.hpp>
#include <vision_pkg/msg/safety_regions.hpp>

using Image = sensor_msgs::msg::Image;
using Objects = vision_pkg::msg::Objects;
using Object = vision_pkg::msg::Object;
using Regions = vision_pkg::msg::SafetyRegions;

class Perception : public rclcpp::Node {
public:
  Perception() : Node("perception_node") {
    const auto detect = declare_parameter("detect", false);
    background_ = declare_parameter("background_filter", true);
    supplies_on_left_ = declare_parameter("supplies_on_left", true);
    const auto qos = rclcpp::SensorDataQoS().keep_last(1);
    preview_ = create_publisher<Image>("vision/preview", qos);
    objects_ = create_publisher<Objects>("vision/objects", qos);
    regions_ = create_publisher<Regions>("vision/safety_regions", qos);
    state_ = create_subscription<communication_pkg::msg::State>("robot/state", rclcpp::QoS(1).transient_local(),
      [this](const communication_pkg::msg::State &state) {
        if (state.camera_changed != robot_.camera_changed) {
          memory_.clear();
          next_id_.clear();
        }
        robot_ = state;
      });
    images_ = create_subscription<Image>(detect ? "vision/inference_image" : "camera/image", qos,
      [this, detect](Image::ConstSharedPtr image) {
        if (!detect) preview_->publish(*image);
        else {
          frame_ = std::move(image);
          match();
        }
      });
    if (detect) {
      detections_ = create_subscription<Objects>("vision/detections", qos,
        [this](Objects::SharedPtr objects) {
          pending_ = std::move(objects);
          match();
        });
    }
  }

private:
  struct Memory { Object object; int missed; };

  static double center_x(const Object &object) { return (object.x1 + object.x2) / 2; }

  void associate(Objects &objects) {
    std::vector<Memory> current;
    std::vector<bool> used(memory_.size(), false);
    for (auto &item : objects.items) {
      int nearest = -1;
      double distance = 150;
      for (size_t index = 0; index < memory_.size(); ++index) {
        const auto &old = memory_[index].object;
        if (used[index] || old.name != item.name) continue;
        const auto delta = std::hypot(center_x(old) - center_x(item), old.y2 - item.y2);
        if (delta <= distance) {
          distance = delta;
          nearest = index;
        }
      }
      if (nearest >= 0) {
        used[nearest] = true;
        item.id = memory_[nearest].object.id;
      } else {
        item.id = ++next_id_[item.name];
      }
      current.push_back({item, 0});
    }
    for (size_t index = 0; index < memory_.size(); ++index) {
      auto old = memory_[index];
      auto &item = old.object;
      if (used[index] || ++old.missed > 6 || item.x1 <= 8 || item.y1 <= 8 ||
          item.x2 >= objects.width - 8.0 || item.y2 >= objects.height - 8.0) continue;
      item.observed = false;
      objects.items.push_back(item);
      current.push_back(old);
    }
    memory_ = std::move(current);
  }

  Regions split(const cv::Mat &frame, Objects &objects) {
    Regions regions;
    regions.header = objects.header;
    if (robot_.team.empty()) return regions;
    const auto safe = std::find_if(objects.items.begin(), objects.items.end(), [this](const Object &item) {
      return item.observed && item.name == (robot_.team == "red" ? "rsafe" : "bsafe");
    });
    if (safe == objects.items.end()) return regions;
    const auto clamp_x = [&](float x) { return static_cast<int>(std::clamp(x, 0.f, float(frame.cols))); };
    const auto clamp_y = [&](float y) { return static_cast<int>(std::clamp(y, 0.f, float(frame.rows))); };
    const cv::Rect roi(cv::Point(clamp_x(safe->x1), clamp_y(safe->y1)), cv::Point(clamp_x(safe->x2), clamp_y(safe->y2)));
    if (roi.empty()) return regions;
    cv::Mat hsv, mask, high;
    cv::cvtColor(frame(roi), hsv, cv::COLOR_BGR2HSV);
    if (robot_.team == "red") {
      cv::inRange(hsv, cv::Scalar(0,60,40), cv::Scalar(12,255,255), mask);
      cv::inRange(hsv, cv::Scalar(168,60,40), cv::Scalar(179,255,255), high);
      mask |= high;
    } else {
      cv::inRange(hsv, cv::Scalar(90,60,40), cv::Scalar(135,255,255), mask);
    }
    cv::morphologyEx(mask, mask, cv::MORPH_OPEN, cv::Mat::ones(9,9,CV_8U));
    std::vector<std::vector<cv::Point>> contours;
    cv::findContours(mask, contours, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_SIMPLE, roi.tl());
    contours.erase(std::remove_if(contours.begin(), contours.end(), [&](const auto &contour) {
      return cv::contourArea(contour) < roi.area() * .015;
    }), contours.end());
    std::sort(contours.begin(), contours.end(), [](const auto &a, const auto &b) {
      return cv::contourArea(a) > cv::contourArea(b);
    });
    if (contours.size() > 2) contours.resize(2);
    if (contours.size() == 2) {
      const auto center = [](const auto &contour) { const auto box = cv::boundingRect(contour); return box.x + box.width * .5; };
      if (center(contours[0]) > center(contours[1])) std::swap(contours[0], contours[1]);
    }
    for (size_t index = 0; index < contours.size(); ++index) {
      vision_pkg::msg::Region region;
      if (contours.size() == 2) region.name = (index == 0) == supplies_on_left_ ? "supplies" : "wounded";
      for (const auto &point : contours[index]) {
        geometry_msgs::msg::Point32 pixel;
        pixel.x = point.x;
        pixel.y = point.y;
        region.polygon.push_back(pixel);
      }
      for (auto &object : objects.items) {
        object.in_safe_zone |= cv::pointPolygonTest(contours[index], cv::Point2f(center_x(object), object.y2), false) >= 0;
      }
      regions.regions.push_back(std::move(region));
    }
    return regions;
  }

  void match() {
    if (!frame_ || !pending_ || frame_->header.stamp != pending_->header.stamp) return;
    auto image = *std::exchange(frame_, {});
    auto detected = std::exchange(pending_, {});
    if (image.encoding != "bgr8" || !image.width || !image.height || image.step < image.width * 3 ||
        image.data.size() < size_t(image.step) * image.height) return;
    cv::Mat frame(image.height, image.width, CV_8UC3, image.data.data(), image.step);
    const bool stable = robot_.camera_known &&
      (rclcpp::Time(image.header.stamp) - rclcpp::Time(robot_.camera_changed)).seconds() >= .4;
    if (robot_.camera_known && !stable) {
      memory_.clear();
      next_id_.clear();
    }
    double cutoff = 0;
    if (background_ && stable) {
      constexpr double rad = 3.141592653589793 / 180;
      cutoff = std::clamp(frame.rows * .5 - frame.cols / (2 * std::tan(35 * rad)) *
        std::tan(robot_.camera_deg * rad) - 16, 0., double(frame.rows));
    }
    auto &items = detected->items;
    items.erase(std::remove_if(items.begin(), items.end(), [&](const auto &item) {
      return !(std::isfinite(item.x1) && std::isfinite(item.y1) && std::isfinite(item.x2) &&
        std::isfinite(item.y2) && item.x2 > item.x1 && item.y2 > item.y1 && item.y2 >= cutoff);
    }), items.end());
    associate(*detected);
    const auto regions = split(frame, *detected);
    objects_->publish(*detected);
    regions_->publish(regions);
    if (cutoff > 0) cv::line(frame, {0,int(cutoff)}, {frame.cols-1,int(cutoff)}, {0,255,255}, 1);
    for (const auto &item : items) {
      if (!item.observed) continue;
      cv::rectangle(frame, cv::Point(item.x1,item.y1), cv::Point(item.x2,item.y2), {65,190,80}, 2);
      cv::putText(frame, item.name, {int(item.x1),std::max(15,int(item.y1)-4)}, cv::FONT_HERSHEY_SIMPLEX, .6, {65,190,80}, 1);
    }
    for (const auto &region : regions.regions) {
      std::vector<cv::Point> contour;
      for (const auto &point : region.polygon) contour.emplace_back(point.x, point.y);
      if (!contour.empty()) cv::polylines(frame, contour, true, {255,210,40}, 2);
    }
    preview_->publish(std::move(image));
  }

  bool background_{true}, supplies_on_left_{true};
  communication_pkg::msg::State robot_;
  Image::ConstSharedPtr frame_;
  Objects::SharedPtr pending_;
  std::map<std::string, int> next_id_;
  std::vector<Memory> memory_;
  rclcpp::Subscription<Image>::SharedPtr images_;
  rclcpp::Subscription<Objects>::SharedPtr detections_;
  rclcpp::Subscription<communication_pkg::msg::State>::SharedPtr state_;
  rclcpp::Publisher<Image>::SharedPtr preview_;
  rclcpp::Publisher<Objects>::SharedPtr objects_;
  rclcpp::Publisher<Regions>::SharedPtr regions_;
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<Perception>());
  rclcpp::shutdown();
}
