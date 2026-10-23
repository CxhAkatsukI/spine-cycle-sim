#pragma once

#include "../../../sst/sst_memory_backend.hpp"

namespace figure_refresh {
class DramClock final : public spine::sim::Component {
 public:
  DramClock(spine::sim::ClockId clock, spine::sim::sst_adapter::SstMemoryBackend& backend)
      : Component("dram-clock", clock), backend_(backend) {}
  bool has_prepare_phase() const noexcept override { return true; }
  bool has_evaluate_phase() const noexcept override { return false; }
  void prepare(const spine::sim::CycleContext& context) override {
    backend_.advance_direct_to(context.now_fs / 1000);
  }
  void evaluate(const spine::sim::CycleContext&) override {}
  void commit(const spine::sim::CycleContext&) override {}
 private:
  spine::sim::sst_adapter::SstMemoryBackend& backend_;
};
} // namespace figure_refresh
