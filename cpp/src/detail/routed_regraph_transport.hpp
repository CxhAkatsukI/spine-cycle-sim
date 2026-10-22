#pragma once

#include <deque>

#include "grasu_regraph_compute.hpp"
#include "spine_sim/regraph_pma_adapter.hpp"

namespace spine::sim::detail {

// A registered one-token/cycle stream bridge. Optional invocation counts stop
// ingress before it consumes the following independently queued adapter task.
template <class T> class RoutedStreamBridge final : public Component {
public:
  RoutedStreamBridge(std::string name, ClockId clock, Fifo<T> &input, Fifo<T> &output,
                     bool counted = false)
      : Component(std::move(name), clock), input_(input), output_(output), counted_(counted) {}
  void start(std::size_t count) {
    if (!counted_ || !done() || !count) throw std::logic_error("invalid counted ingress restart");
    terminal_framed_ = false;
    remaining_ = count;
  }
  void start_until_last(std::size_t maximum) {
    if constexpr (requires(T value) { value.last; }) {
      start(maximum);
      terminal_framed_ = true;
    } else throw std::logic_error("terminal ingress requires a packet marker");
  }
  [[nodiscard]] bool done() const noexcept { return remaining_ == 0 && !held_; }
  void evaluate(const CycleContext &) override {
    accepted_.reset();
    retired_ = held_ && output_.try_push(*held_);
    if ((!held_ || retired_) && (!counted_ || remaining_)) {
      T value;
      if (input_.try_pop(value)) accepted_ = std::move(value);
    }
  }
  void commit(const CycleContext &) override {
    if (retired_) held_.reset();
    if (accepted_) {
      held_ = std::move(accepted_);
      if (counted_) {
        --remaining_;
        if constexpr (requires(T value) { value.last; }) {
          if (terminal_framed_) {
            if (held_->last) remaining_ = 0;
            else if (!remaining_) throw std::logic_error("terminal ingress exceeded physical packet bound");
          }
        }
      }
    }
  }
private:
  Fifo<T> &input_, &output_;
  bool counted_{}, retired_{}, terminal_framed_{};
  std::size_t remaining_{};
  std::optional<T> held_, accepted_;
};

class RoutedGatherMux final : public Component {
public:
  RoutedGatherMux(std::string name, ClockId clock,
                  std::array<Fifo<ReGraphGatherRow> *, 4> inputs,
                  Fifo<ReGraphGatherRow> &output, std::size_t partitions);
  void start_round();
  [[nodiscard]] bool done() const noexcept { return partition_ == partitions_; }
  [[nodiscard]] std::uint64_t rows() const noexcept { return rows_; }
  void evaluate(const CycleContext &) override;
  void commit(const CycleContext &) override;
private:
  std::array<Fifo<ReGraphGatherRow> *, 4> inputs_;
  Fifo<ReGraphGatherRow> &output_;
  std::size_t partitions_{}, partition_{}, local_row_{};
  std::uint64_t rows_{};
  bool staged_{}, started_{};
};

class RoutedStatusWriter final : public Component {
public:
  RoutedStatusWriter(std::string name, ClockId clock, AxiEndpoint memory,
                     std::size_t channel, std::uint64_t address);
  void start(std::uint32_t active);
  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] std::uint64_t writes() const noexcept { return writes_; }
  void evaluate(const CycleContext &) override;
  void commit(const CycleContext &) override;
private:
  enum class Phase { kIdle, kIssue, kWait, kDone };
  AxiEndpoint memory_;
  std::size_t channel_{};
  std::uint64_t address_{}, id_{1}, writes_{};
  std::uint32_t active_{};
  Phase phase_{Phase::kIdle};
  bool staged_{};
};

} // namespace spine::sim::detail
