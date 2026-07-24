#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <string>
#include <vector>

#include "spine_sim/component.hpp"
#include "spine_sim/fixed_axi_port.hpp"
#include "spine_sim/spine_l0.hpp"
#include "spine_sim/spine_split.hpp"

namespace spine::sim {

struct SpineDirtyAckPorts {
  FixedAxiPort *task_scratch{};
  FixedAxiPort *metadata{};
  FixedAxiPort *result{};
};

struct SpineDirtyAckCounters {
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
  std::uint32_t status{};
  std::uint32_t expected_generation{};
  SpineDirtyIdentity captured;
  SpineDirtyIdentity candidate;
  SpineDirtyIdentity result;
  std::uint64_t candidate_write_bytes{};
  std::uint64_t metadata_read_bytes{};
  std::uint64_t metadata_write_bytes{};
  std::uint64_t list_read_bytes{};
  std::uint64_t bitmap_read_bytes{};
  std::uint64_t bitmap_write_bytes{};
  std::uint64_t result_write_bytes{};
  std::uint64_t validated_sources{};
  std::uint64_t cleared_sources{};
  std::uint64_t generation_advances{};
};

class SpineDirtyAck final : public Component {
public:
  SpineDirtyAck(std::string name, ClockId clock_id, SpineL0Config config,
                SpineDirtyAckPorts ports);

  void start(std::uint32_t expected_generation, SpineDirtyIdentity candidate);
  void reset();

  [[nodiscard]] bool started() const noexcept { return started_; }
  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] bool failed() const noexcept { return failed_; }
  [[nodiscard]] const SpineDirtyAckCounters &counters() const noexcept {
    return counters_;
  }

  void evaluate(const CycleContext &context) override;
  void commit(const CycleContext &context) override;

private:
  enum class PayloadKind {
    kNone,
    kCount,
    kGeneration,
    kHashSum,
    kHashXor,
    kCandidateGeneration,
    kCandidateCount,
    kCandidateHashSum,
    kCandidateHashXor,
    kCandidateValid,
    kList,
    kBitmapValidate,
    kBitmapClear,
  };

  struct MemoryTask {
    FixedAxiPort *port{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint64_t address{};
    std::uint64_t bytes{};
    std::vector<std::uint8_t> write_data;
    PayloadKind payload_kind{PayloadKind::kNone};
  };

  enum class Phase {
    kDormant,
    kHeaderResolve,
    kValidateList,
    kValidateBitmap,
    kClearList,
    kClearBitmapRead,
    kClearBitmapWrite,
    kDrain,
  };

  enum class Action { kNone, kIssue, kComplete, kAdvance };

  void enqueue(FixedAxiPort &port, MemoryOperation operation,
               std::uint64_t address, std::uint64_t bytes,
               PayloadKind payload_kind = PayloadKind::kNone,
               std::vector<std::uint8_t> write_data = {});
  void enqueue_metadata_write(std::uint64_t word, std::uint64_t value);
  void consume_response(const MemoryTask &task, const AxiResponse &response);
  void advance(const CycleContext &context);
  void begin_finalize(std::uint32_t status);
  void enqueue_final_writes();

  SpineL0Config config_;
  SpineDirtyAckPorts ports_;
  SpineDirtyAckCounters counters_;
  std::deque<MemoryTask> memory_tasks_;
  Phase phase_{Phase::kDormant};
  Action staged_action_{Action::kNone};
  AxiResponse staged_response_;
  std::vector<std::uint8_t> bitmap_payload_;
  std::uint32_t current_source_{};
  std::uint64_t checked_hash_sum_{};
  std::uint64_t checked_hash_xor_{};
  std::size_t source_index_{};
  std::uint64_t next_transaction_id_{};
  std::uint64_t expected_transaction_id_{};
  bool waiting_memory_{};
  bool start_cycle_recorded_{};
  bool candidate_valid_{};
  bool started_{};
  bool done_{};
  bool failed_{};
};

} // namespace spine::sim
