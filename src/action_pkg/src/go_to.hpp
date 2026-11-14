#pragma once

#include <algorithm>
#include <chrono>
#include <cmath>
#include <functional>
#include <optional>
#include <string>
#include <vector>
#include <vision_pkg/msg/objects.hpp>

class GoTo {
public:
  using Object = vision_pkg::msg::Object;
  using Objects = vision_pkg::msg::Objects;
  using Clock = std::chrono::steady_clock;
  using Send = std::function<void(uint8_t, int16_t)>;

  struct Config {
    double x{640}, y{550}, green{5}, black{5}, orange{2}, count{4}, safe{6}, distance{.002};
    int cam1{30}, cam2{20}, settle{400}, forward{200}, forward_ms{1000}, confirm{3};
    int threshold{10}, gate{150}, tolerance{20}, turn_only{80}, turn_limit{100}, forward_limit{180};
    bool first{true};
  };

  explicit GoTo(Send send) : send_(std::move(send)) {}
  Config config;
  std::string stage{"search"};

  void reset() {
    stage = "search";
    step_ = -1;
    target_.reset();
    hits_ = aligned_ = 0;
  }

  bool run(const Objects &objects, const std::string &team, bool turned) {
    const auto now = Clock::now();
    if (step_ < 0) { next(now); return false; }
    if (now - changed_ < std::chrono::milliseconds(config.settle)) return false;
    std::vector<Object> material;
    for (const auto &item : objects.items) {
      if (!item.observed || item.in_safe_zone || (item.name != "green" && item.name != "black" &&
          item.name != "orange" && item.name != "blue")) continue;
      if (std::any_of(objects.items.begin(), objects.items.end(), [&](const auto &safe) {
        return safe.observed && (safe.name == "rsafe" || safe.name == "bsafe") &&
          x(item) >= safe.x1 && x(item) <= safe.x2 && item.y2 >= safe.y1 && item.y2 <= safe.y2;
      })) continue;
      material.push_back(item);
    }
    std::vector<Object> candidates;
    for (const auto &item : material) if (eligible(item.name)) candidates.push_back(item);
    if (stage == "search") {
      double score = 0;
      if (!candidates.empty()) {
        score = config.count / material.size();
        for (const auto &name : {"green", "black", "orange"}) {
          if (std::any_of(candidates.begin(), candidates.end(), [name](const auto &item) { return item.name == name; }))
            score += weight(name);
        }
        const auto own = team == "red" ? "rsafe" : team == "blue" ? "bsafe" : "";
        if (std::any_of(objects.items.begin(), objects.items.end(), [&](const auto &item) {
          return item.observed && item.name == own;
        })) score += config.safe;
      }
      const bool half = step_ == 0 || step_ == 2;
      if (!candidates.empty() && (half ? score >= config.threshold : score > 0)) {
        send_(6, 0);
        stage = "track";
        target_.reset();
        hits_ = aligned_ = 0;
      } else if (step_ == 4) {
        send_(1, config.forward);
        send_(2, 0);
        if (now - step_at_ >= std::chrono::milliseconds(config.settle + config.forward_ms)) next(now);
      } else if (!turn_sent_) {
        send_(5, half ? 180 : 360);
        turn_sent_ = true;
      } else if (turned) {
        next(now);
      }
      return false;
    }
    std::optional<Object> selected;
    double best = -1e10;
    for (const auto &item : candidates) {
      const double delta = target_ ? std::hypot(x(item) - x(*target_), item.y2 - target_->y2) : 0;
      if (target_ && (item.name != target_->name || delta > config.gate)) continue;
      const double score = target_ ? -delta : weight(item.name) + config.distance /
        std::max(1., std::hypot(x(item)-config.x, item.y2-config.y));
      if (score > best) { selected = item; best = score; }
    }
    if (!selected) {
      reset();
      next(now);
      return false;
    }
    target_ = selected;
    if (++hits_ < config.confirm) {
      send_(6, 0);
      return false;
    }
    const double dx = x(*target_) - config.x, dy = target_->y2 - config.y;
    if (std::abs(dx) <= config.tolerance && std::abs(dy) <= config.tolerance) {
      send_(6, 0);
      return ++aligned_ >= config.confirm;
    }
    aligned_ = 0;
    send_(2, std::abs(dx) <= config.tolerance ? 0 : std::clamp(dx, -double(config.turn_limit), double(config.turn_limit)));
    send_(1, std::abs(dx) > config.turn_only || std::abs(dy) <= config.tolerance ?
      0 : std::clamp(dy, -double(config.forward_limit), double(config.forward_limit)));
    return false;
  }

private:
  static double x(const Object &object) { return (object.x1 + object.x2) * .5; }
  bool eligible(const std::string &name) const {
    return name == "green" || (!config.first && (name == "black" || name == "orange"));
  }
  double weight(const std::string &name) const {
    return name == "green" ? config.green : name == "black" ? config.black : config.orange;
  }
  void next(Clock::time_point now) {
    step_ = (step_ + 1) % 5;
    send_(6, 0);
    const int camera = step_ == 2 || step_ == 3 ? config.cam2 : config.cam1;
    if (camera != camera_) changed_ = now;
    camera_ = camera;
    send_(4, camera);
    turn_sent_ = false;
    step_at_ = now;
  }

  Send send_;
  int step_{-1}, camera_{-1}, hits_{0}, aligned_{0};
  bool turn_sent_{false};
  Clock::time_point step_at_{}, changed_{};
  std::optional<Object> target_;
};
