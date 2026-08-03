#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "spine_sim/component.hpp"
#include "spine_sim/fixed_axi_port.hpp"

namespace spine::sim {

struct SpineVertexLifecycleConfig {
  std::size_t max_vertices{16'777'216};
  std::size_t initial_valid_vertices{};
  std::uint64_t bitmap_base{};
};

struct SpineVertexLifecycleCounters {
  std::uint64_t activation_attempts{};
  std::uint64_t deactivation_attempts{};
  std::uint64_t accepted_operations{};
  std::uint64_t busy_stalls{};
  std::uint64_t unsafe_deactivation_rejections{};
  std::uint64_t no_op_operations{};
  std::uint64_t changed_operations{};
  std::uint64_t bitmap_reads{};
  std::uint64_t bitmap_writes{};
  std::uint64_t read_bytes{};
  std::uint64_t write_bytes{};
  std::uint64_t memory_request_fifo_stall_cycles{};
  std::uint64_t memory_requests_issued{};
  std::uint64_t memory_requests_completed{};
  std::uint64_t last_start_cycle{};
  std::uint64_t last_end_cycle{};
};

struct SpineVertexLifecycleResult {
  std::uint32_t vertex{};
  bool requested_valid{};
  bool changed{};
  bool final_valid{};
  std::uint64_t start_cycle{};
  std::uint64_t end_cycle{};
};

class SpineVertexLifecycle final : public Component {
 public:
  SpineVertexLifecycle(std::string name, ClockId clock_id,
                       SpineVertexLifecycleConfig config,
                       FixedAxiPort &bitmap_port);

  bool try_activate(std::uint32_t vertex);
  bool try_deactivate(std::uint32_t vertex,
                      bool incident_edges_retired_or_masked);

  [[nodiscard]] bool valid(std::uint32_t vertex) const;
  [[nodiscard]] bool busy() const noexcept;
  [[nodiscard]] bool failed() const noexcept { return failed_; }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] const SpineVertexLifecycleCounters &counters() const noexcept {
    return counters_;
  }
  [[nodiscard]] const std::optional<SpineVertexLifecycleResult> &last_result()
      const noexcept {
    return last_result_;
  }
  [[nodiscard]] bool request_ledger_closed() const noexcept {
    return counters_.memory_requests_issued ==
           counters_.memory_requests_completed;
  }

  void evaluate(const CycleContext &) override;
  void commit(const CycleContext &) override;

 private:
  enum class Phase { kIdle, kIssueRead, kWaitRead, kIssueWrite, kWaitWrite };

  struct Operation {
    std::uint32_t vertex{};
    bool requested_valid{};
    std::uint64_t start_cycle{};
    std::uint64_t bitmap_word{};
    std::uint64_t updated_word{};
  };

  [[nodiscard]] std::uint64_t word_index(std::uint32_t vertex) const noexcept;
  [[nodiscard]] std::uint64_t word_address(std::uint32_t vertex) const noexcept;
  [[nodiscard]] std::vector<std::uint8_t> encode_word(
      std::uint64_t word) const;
  [[nodiscard]] std::uint64_t decode_word(
      const std::vector<std::uint8_t> &payload) const;
  bool begin_operation(std::uint32_t vertex, bool requested_valid);
  void complete_operation(bool changed, std::uint64_t end_cycle);
  void fail(std::string message);

  SpineVertexLifecycleConfig config_;
  FixedAxiPort &bitmap_port_;
  SpineVertexLifecycleCounters counters_;
  std::vector<std::uint64_t> validity_words_;
  std::optional<Operation> operation_;
  std::optional<SpineVertexLifecycleResult> last_result_;
  std::optional<AxiResponse> staged_response_;
  Phase phase_{Phase::kIdle};
  std::uint64_t next_transaction_{};
  std::uint64_t inflight_transaction_{};
  bool staged_issue_{};
  bool failed_{};
  std::string failure_;
};

}  // namespace spine::sim
