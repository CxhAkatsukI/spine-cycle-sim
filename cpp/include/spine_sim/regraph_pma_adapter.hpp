#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <vector>

#include "spine_sim/fixed_axi_port.hpp"

namespace spine::sim {

namespace detail { class CrossRowPmaAdapter; }

enum class ReGraphPmaFormat { kWeighted, kDestination, kUnitWeight };

struct ReGraphPmaPacket {
  std::array<std::uint32_t, 8> sources{};
  std::array<std::uint32_t, 8> destinations{};
  bool last{};
  bool operator==(const ReGraphPmaPacket &) const = default;
};

struct ReGraphPmaPartition {
  std::size_t vertices{};
  std::size_t slots{};
  std::size_t cache_segments_per_half{};
  std::uint32_t destination_base{};
  std::size_t destination_vertices{};
  std::uint64_t row_base{};
  std::size_t row_channel{};
  std::array<std::uint64_t, 4> pma_base{};
  std::array<std::size_t, 4> pma_channel{};
};

// Nominal structural schedule, not a fitted or FPGA-calibrated timing model.
struct ReGraphPmaCrossRowSchedule {
  std::size_t loaded_fifo_capacity{16};
  std::size_t reader_pipeline_capacity{74};
  std::uint64_t block_drain_cycles{74};
  std::uint64_t publisher_pipeline_cycles{2};
  // Counterfactual candidate: current single-loop HLS fails II=1. Default off.
  bool continuous_directory{false};
  // Explicit production-HLS candidate; 8 is the unchanged legacy line cache.
  std::size_t directory_cache_rows{8};
  bool packet_pipeline{false};
  bool bank_stream{false};
  bool bank_read_beats{false};
  std::size_t bank_fifo_lines{128};
};

struct ReGraphPmaAdapterConfig {
  ReGraphPmaFormat format{ReGraphPmaFormat::kWeighted};
  bool prefetch_rows{true};
  bool stop_after_last{true};
  std::size_t pending_read_capacity{16};
  std::size_t segment_buffer_capacity{16};
  std::uint64_t read_pipeline_cycles{71};
  std::uint64_t row_control_cycles{6};
  std::uint64_t segment_issue_interval{2};
  std::uint64_t empty_segment_exit_cycles{0};
  bool row_line_reads{false};
  bool cross_row_pipeline{false};
  ReGraphPmaCrossRowSchedule cross_row{};
};

struct ReGraphPmaAdapterCounters {
  std::uint64_t extent_reads{};
  std::uint64_t row_reads{};
  std::uint64_t directory_requests{};
  std::uint64_t pma_requests{};
  std::uint64_t rows_visited{};
  std::uint64_t empty_rows{};
  std::uint64_t empty_exit_cycles{};
  std::uint64_t segment_reads{};
  std::uint64_t responses{};
  std::uint64_t packets{};
  std::uint64_t live_edges{};
  std::uint64_t dummy_edges{};
  std::uint64_t output_stalls{};
  std::size_t max_pending_reads{};
  std::size_t max_buffered_segments{};
};

// The routed adapter has one 512-bit AXI master for rows and all PMA banks.
// Legacy prefetch repeats a line load per row; the explicit whole-line
// candidate decodes up to eight rows from one response. Extent stays separate.
class ReGraphPmaAdapter final : public Component {
public:
  using Notifier = void (*)(void *) noexcept;
  ReGraphPmaAdapter(std::string name, ClockId clock_id,
                    ReGraphPmaAdapterConfig config, FixedAxiPort &memory,
                    Fifo<ReGraphPmaPacket> &output);
  ~ReGraphPmaAdapter() override;
  void start_partition(ReGraphPmaPartition partition);
  void bind_completion_notifier(void *owner, Notifier notifier);
  void unbind_completion_notifier(void *owner) noexcept;
  [[nodiscard]] bool done() const noexcept;
  [[nodiscard]] bool stream_complete() const noexcept { return stream_complete_; }
  [[nodiscard]] const ReGraphPmaAdapterCounters &counters() const noexcept { return counters_; }
  void evaluate(const CycleContext &context) override;
  void commit(const CycleContext &context) override;

private:
  enum class Phase { kIdle, kEmptyPartition, kExtent, kWaitExtent, kRows, kRowControl, kEmptyExit, kSegments, kDone };
  enum class Kind { kExtent, kRow, kSegment };
  struct Pending {
    Kind kind{};
    std::size_t index{};
    std::uint64_t ready_cycle{};
  };
  bool issue(Kind kind, std::size_t index, std::uint64_t address,
             std::size_t channel, const CycleContext &context);
  void consume(const AxiResponse &response);
  void select_source();
  void start_row();
  void notify() const noexcept;
  ReGraphPmaPacket packet() const;
  ReGraphPmaAdapterConfig config_;
  FixedAxiPort &memory_;
  Fifo<ReGraphPmaPacket> &output_;
  ReGraphPmaPartition partition_;
  Phase phase_{Phase::kIdle};
  std::map<std::uint64_t, Pending> pending_;
  std::map<std::size_t, std::vector<std::uint8_t>> segments_;
  std::array<std::uint64_t, 8> rows_{};
  std::size_t row_begin_{};
  std::size_t row_count_{};
  std::size_t rows_issued_{};
  std::size_t rows_received_{};
  std::size_t source_{};
  std::size_t total_slots_{};
  std::size_t emitted_slots_{};
  std::size_t next_segment_{};
  std::size_t next_emit_segment_{};
  std::size_t end_segment_{};
  unsigned half_{};
  std::uint64_t remaining_control_{};
  std::uint64_t remaining_empty_exit_{};
  std::uint64_t next_segment_issue_cycle_{};
  std::uint64_t next_id_{0x7a00'0000'0000'0000ULL};
  bool stream_complete_{};
  std::optional<Pending> staged_issue_;
  std::optional<AxiResponse> staged_response_;
  std::optional<ReGraphPmaPacket> staged_packet_;
  bool staged_control_{};
  bool staged_empty_exit_{};
  bool staged_output_stall_{};
  void *notifier_owner_{};
  Notifier notifier_{};
  ReGraphPmaAdapterCounters counters_;
  std::unique_ptr<detail::CrossRowPmaAdapter> cross_row_;
};

} // namespace spine::sim
