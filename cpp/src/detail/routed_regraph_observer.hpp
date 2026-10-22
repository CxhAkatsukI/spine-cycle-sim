#pragma once

#include "grasu_regraph_compute.hpp"

namespace spine::sim::detail {

// Sample committed pre-edge state even when Apply's execution guard sleeps.
// No FIFO operation or timing state is changed by this observer.
class RoutedApplyObserver final : public Component {
public:
  RoutedApplyObserver(ClockId clock, const ReGraphApplyEngine& apply)
      : Component("apply-read-window-observer", clock), apply_(apply) {}

  void evaluate(const CycleContext&) override { blocked_ = apply_.read_window_blocked(); }
  void commit(const CycleContext&) override { cycles_ += blocked_; }
  [[nodiscard]] std::uint64_t blocked_cycles() const noexcept { return cycles_; }

private:
  const ReGraphApplyEngine& apply_;
  bool blocked_{};
  std::uint64_t cycles_{};
};

}  // namespace spine::sim::detail
