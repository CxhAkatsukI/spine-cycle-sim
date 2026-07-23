#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>

namespace spine::sim {

using ClockId = std::size_t;
using TimestampFs = std::uint64_t;

struct CycleContext {
  TimestampFs now_fs{};
  std::uint64_t domain_cycle{};
  ClockId clock_id{};
};

class Component {
 public:
  Component(std::string name, ClockId clock_id)
      : name_(std::move(name)), clock_id_(clock_id) {}
  virtual ~Component() = default;

  Component(const Component&) = delete;
  Component& operator=(const Component&) = delete;
  Component(Component&&) = delete;
  Component& operator=(Component&&) = delete;

  [[nodiscard]] const std::string& name() const noexcept { return name_; }
  [[nodiscard]] ClockId clock_id() const noexcept { return clock_id_; }

  virtual void evaluate(const CycleContext& context) = 0;
  virtual void commit(const CycleContext& context) = 0;

 private:
  std::string name_;
  ClockId clock_id_;
};

}  // namespace spine::sim
