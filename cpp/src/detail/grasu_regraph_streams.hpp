#pragma once

#include <algorithm>
#include <array>
#include <memory>
#include <optional>
#include <stdexcept>
#include <vector>

#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"
#include "spine_sim/grasu_regraph.hpp"
#include "grasu_regraph_payload.hpp"

namespace spine::sim::detail {

struct PmaEdgeBatch {
  std::uint32_t source{};
  std::uint32_t source_payload{};
  bool source_active{};
  bool per_lane_source{};
  std::size_t lanes{};
  std::array<std::uint32_t, 8> source_payloads{};
  std::array<bool, 8> source_actives{};
  std::array<std::uint32_t, 8> destinations{};
  std::array<std::uint16_t, 8> weights{};
  std::array<bool, 8> valid{};
};

class ReGraphDoneSignal {
public:
  using Notifier = void (*)(void *) noexcept;

  void bind(void *owner, Notifier notifier) {
    if (notifier == nullptr) {
      throw std::invalid_argument("ReGraph done notifier is null");
    }
    if (notifier_ != nullptr && (owner_ != owner || notifier_ != notifier)) {
      throw std::logic_error("ReGraph done notifier is already bound");
    }
    owner_ = owner;
    notifier_ = notifier;
  }

  void unbind(void *owner) noexcept {
    if (owner_ == owner) {
      owner_ = nullptr;
      notifier_ = nullptr;
    }
  }

  void notify() const noexcept {
    if (notifier_ != nullptr) {
      notifier_(owner_);
    }
  }

private:
  void *owner_{};
  Notifier notifier_{};
};

class ReGraphReaderContext {
public:
  using DoneNotifier = void (*)(void *) noexcept;

  virtual ~ReGraphReaderContext() = default;
  [[nodiscard]] virtual bool done() const noexcept = 0;
  [[nodiscard]] virtual AlgorithmIterationContext
  iteration_context() const noexcept = 0;

  void bind_done_notifier(void *owner, DoneNotifier notifier) {
    if (notifier == nullptr) {
      throw std::invalid_argument("ReGraph reader done notifier is null");
    }
    const auto duplicate =
        std::find_if(done_notifiers_.begin(), done_notifiers_.end(),
                     [owner](const DoneNotifierBinding &binding) {
                       return binding.owner == owner;
                     });
    if (duplicate != done_notifiers_.end()) {
      if (duplicate->notifier != notifier) {
        throw std::logic_error(
            "ReGraph reader done notifier owner is already bound");
      }
      return;
    }
    done_notifiers_.push_back({.owner = owner, .notifier = notifier});
    if (done()) {
      notifier(owner);
    }
  }

  void unbind_done_notifier(void *owner) noexcept {
    std::erase_if(done_notifiers_, [owner](const DoneNotifierBinding &binding) {
      return binding.owner == owner;
    });
  }

protected:
  void notify_done() noexcept {
    for (const DoneNotifierBinding &binding : done_notifiers_) {
      binding.notifier(binding.owner);
    }
  }

private:
  struct DoneNotifierBinding {
    void *owner{};
    DoneNotifier notifier{};
  };

  std::vector<DoneNotifierBinding> done_notifiers_;
};

struct ReGraphSourceCacheRequest {
  std::size_t source_round{};
  bool end{};
};

struct ReGraphSourceCacheResponse {
  std::size_t source_round{};
  std::size_t line{};
  std::array<std::uint32_t, kStateWordsPerBurst> words{};
  std::array<std::uint32_t, kStateWordsPerBurst> auxiliary_words{};
  std::size_t vertices{};
  bool end{};
};

struct ReGraphGatherRow {
  std::size_t row{};
  std::array<std::optional<std::uint32_t>, 2> candidates{};
};

struct ReGraphMergedBurst {
  std::size_t offset{};
  std::array<std::optional<std::uint32_t>, kStateWordsPerBurst> candidates{};
};

struct ReGraphAppliedBurst {
  std::size_t offset{};
  std::vector<std::uint8_t> data;
  std::vector<std::uint8_t> source_data;
};

struct ReGraphPartitionPlan {
  std::size_t destination_base{};
  std::size_t destination_vertices{};
  std::uint64_t row_base{};
  std::size_t row_channel{};
  std::array<std::uint64_t, 4> pma_base{};
  std::array<std::size_t, 4> pma_channel{};
};

class ReGraphPartitionReader : public Component, public ReGraphReaderContext {
public:
  using Component::Component;
  struct Ports {
    FixedAxiPort *rows{};
    FixedAxiPort *degree{};
    std::array<FixedAxiPort *, 4> pma{};
    Fifo<PmaEdgeBatch> *output{};
    Fifo<ReGraphSourceCacheRequest> *source_requests{};
    Fifo<ReGraphSourceCacheResponse> *source_responses{};
  };


  virtual void start_partition(std::uint64_t round, const ReGraphPartitionPlan &plan,
                               bool accumulate_dangling) = 0;
  [[nodiscard]] virtual std::uint64_t row_reads() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t source_requests() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t source_request_markers() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t source_lines() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t source_lane_writes() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t source_response_markers() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t source_wait_cycles() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t segment_reads() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t degree_reads() const noexcept = 0;
  [[nodiscard]] virtual std::uint64_t source_map_cycles() const noexcept = 0;
};

std::unique_ptr<ReGraphPartitionReader> make_legacy_pma_reader(
    std::string name, ClockId clock_id, std::size_t vertices,
    GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
    ReGraphPartitionReader::Ports ports);

} // namespace spine::sim::detail
