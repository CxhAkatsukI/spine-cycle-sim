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

  // Phase participation is fixed for a component's lifetime. The scheduler
  // uses these declarations only to omit virtual calls to known no-op phases;
  // every simulated clock edge and the prepare/evaluate/commit ordering remain
  // unchanged.
  [[nodiscard]] virtual bool has_prepare_phase() const noexcept {
    return false;
  }
  [[nodiscard]] virtual bool has_evaluate_phase() const noexcept {
    return true;
  }
  [[nodiscard]] virtual bool has_commit_phase() const noexcept { return true; }
  [[nodiscard]] virtual bool has_dynamic_evaluate_guard() const noexcept {
    return false;
  }
  [[nodiscard]] virtual bool has_dynamic_commit_guard() const noexcept {
    return false;
  }
  [[nodiscard]] virtual bool evaluate_ready() const noexcept { return true; }
  [[nodiscard]] virtual bool commit_ready() const noexcept { return true; }

  virtual void prepare(const CycleContext&) {}
  virtual void evaluate(const CycleContext& context) = 0;
  virtual void commit(const CycleContext& context) = 0;

 private:
  std::string name_;
  ClockId clock_id_;
};

}  // namespace spine::sim
