#include "spine_sim/grasu_update/search.hpp"

#include <array>
#include <optional>
#include <stdexcept>
#include <utility>

namespace spine::sim::grasu_update_detail {
namespace {

constexpr std::size_t kLanes = 16;
enum class Phase { kUpdate, kWaitUpdate, kRow, kWaitRow, kBinary,
                   kWaitBinary, kEmit, kDone };

struct Context {
  std::size_t index{};
  Phase phase{Phase::kDone};
  std::uint64_t edge{}, last_head{};
  std::uint32_t begin{}, end{}, mid{};
};

std::uint64_t word(const AxiResponse& response) {
  if (!response.success || response.operation != MemoryOperation::kRead ||
      response.read_data.size() != 8) {
    throw std::runtime_error("parallel GraSU search malformed response");
  }
  std::uint64_t value = 0;
  for (unsigned byte = 0; byte < 8; ++byte)
    value |= std::uint64_t(response.read_data[byte]) << (byte * 8);
  return value;
}

class ParallelSearch final : public Search {
public:
  ParallelSearch(std::string name, ClockId clock, std::size_t cu,
                 std::size_t count, std::uint64_t update_base,
                 std::uint64_t row_base, std::uint64_t binary_base,
                 FixedAxiPort& updates, FixedAxiPort& metadata,
                 Fifo<LocatedUpdate>& output)
      : Search(std::move(name), clock), cu_(cu), count_(count),
        update_base_(update_base), row_base_(row_base), binary_base_(binary_base),
        updates_(updates), metadata_(metadata), output_(output) {
    if (cu >= 4) throw std::invalid_argument("parallel search CU out of range");
    for (std::size_t lane = 0; lane < kLanes; ++lane)
      contexts_[lane] = {.index = lane,
                        .phase = lane < count ? Phase::kUpdate : Phase::kDone};
  }

  bool done() const noexcept override { return emitted_ == count_; }
  bool failed() const noexcept override { return !failure_.empty(); }
  const std::string& failure() const noexcept override { return failure_; }
  std::uint64_t row_reads() const noexcept override { return rows_; }
  std::uint64_t binary_probes() const noexcept override { return probes_; }

  void evaluate(const CycleContext&) override {
    update_response_.reset(); metadata_response_.reset();
    update_issue_.reset(); metadata_issue_.reset(); emitted_lane_.reset();
    if (failed() || done()) return;
    take_response(updates_, update_response_);
    take_response(metadata_, metadata_response_);
    for (std::size_t offset = 0; offset < kLanes; ++offset) {
      const auto lane = (update_rr_ + offset) % kLanes;
      const auto& context = contexts_[lane];
      if (context.phase != Phase::kUpdate) continue;
      if (issue(updates_, context, 0, update_base_ + context.index * 8))
        update_issue_ = lane;
      break;
    }
    for (std::size_t offset = 0; offset < kLanes; ++offset) {
      const auto lane = (metadata_rr_ + offset) % kLanes;
      const auto& context = contexts_[lane];
      if (context.phase != Phase::kRow && context.phase != Phase::kBinary) continue;
      const bool binary = context.phase == Phase::kBinary;
      const auto address = binary ? binary_base_ + std::uint64_t(context.mid) * 8
          : row_base_ + ((context.edge >> 32) & 0x7fffffffULL) * 8;
      if (issue(metadata_, context, binary ? 2 : 1, address)) metadata_issue_ = lane;
      break;
    }
    const auto lane = emitted_ % kLanes;
    const auto& context = contexts_[lane];
    if (context.phase == Phase::kEmit && context.index == emitted_) {
      const auto encoded = static_cast<std::uint32_t>(context.edge);
      if (output_.try_push(LocatedUpdate{
              .global_index = cu_ + context.index * 4,
              .source = static_cast<std::uint32_t>((context.edge >> 32) & 0x7fffffff),
              .partition = 0, .segment_head_slot = context.begin << 4,
              .destination = decode_grasu_pma_destination(encoded),
              .weight = decode_grasu_pma_weight(encoded),
              .delete_op = static_cast<bool>(context.edge >> 63),
              .last_binary_head = context.last_head})) emitted_lane_ = lane;
    }
  }

  void commit(const CycleContext&) override {
    if (failed()) return;
    try {
      if (update_response_) consume(*update_response_, true);
      if (metadata_response_) consume(*metadata_response_, false);
      if (update_issue_) {
        contexts_[*update_issue_].phase = Phase::kWaitUpdate;
        update_rr_ = (*update_issue_ + 1) % kLanes;
      }
      if (metadata_issue_) {
        auto& context = contexts_[*metadata_issue_];
        const bool binary = context.phase == Phase::kBinary;
        context.phase = binary ? Phase::kWaitBinary : Phase::kWaitRow;
        (binary ? probes_ : rows_)++;
        metadata_rr_ = (*metadata_issue_ + 1) % kLanes;
      }
      if (emitted_lane_) {
        auto& context = contexts_[*emitted_lane_];
        context.index += kLanes;
        context.phase = context.index < count_ ? Phase::kUpdate : Phase::kDone;
        ++emitted_;
      }
    } catch (const std::exception& error) { failure_ = error.what(); }
  }

private:
  static void take_response(FixedAxiPort& port, std::optional<AxiResponse>& staged) {
    AxiResponse response;
    if (port.responses().try_pop(response)) staged = std::move(response);
  }
  static bool issue(FixedAxiPort& port, const Context& context,
                    unsigned kind, std::uint64_t address) {
    return port.requests().try_push(AxiRequest{
        .transaction_id = (context.index << 2) | kind,
        .operation = MemoryOperation::kRead, .address = address, .bytes = 8,
        .stream_read_beats = false, .write_data = {}});
  }
  void consume(const AxiResponse& response, bool update_port) {
    const auto index = response.transaction_id >> 2;
    const auto kind = response.transaction_id & 3;
    auto& context = contexts_[index % kLanes];
    const auto expected = kind == 0 ? Phase::kWaitUpdate :
                          kind == 1 ? Phase::kWaitRow : Phase::kWaitBinary;
    if (kind > 2 || update_port != (kind == 0) ||
        context.index != index || context.phase != expected)
      throw std::runtime_error("parallel search response owner/phase mismatch");
    const auto value = word(response);
    if (kind == 0) {
      context.edge = value; context.last_head = 0; context.phase = Phase::kRow;
      return;
    }
    if (kind == 1) {
      context.begin = static_cast<std::uint32_t>(value >> 32) >> 4;
      context.end = static_cast<std::uint32_t>(value) >> 4;
      if (context.begin >= context.end)
        throw std::runtime_error("parallel search source has no reserved segment");
    } else {
      context.last_head = value;
      if (value <= (context.edge & ~(std::uint64_t{1} << 63))) context.begin = context.mid;
      else context.end = context.mid;
    }
    context.mid = (context.begin + context.end) >> 1;
    context.phase = context.begin == context.mid ? Phase::kEmit : Phase::kBinary;
  }

  std::size_t cu_{}, count_{}, emitted_{}, update_rr_{}, metadata_rr_{};
  std::uint64_t update_base_{}, row_base_{}, binary_base_{}, rows_{}, probes_{};
  FixedAxiPort& updates_;
  FixedAxiPort& metadata_;
  Fifo<LocatedUpdate>& output_;
  std::array<Context, kLanes> contexts_{};
  std::optional<AxiResponse> update_response_, metadata_response_;
  std::optional<std::size_t> update_issue_, metadata_issue_, emitted_lane_;
  std::string failure_;
};
}  // namespace

std::unique_ptr<Search> make_parallel_search(
    std::string name, ClockId clock, std::size_t cu, std::size_t count,
    std::uint64_t update_base, std::uint64_t row_base, std::uint64_t binary_base,
    FixedAxiPort& updates, FixedAxiPort& metadata, Fifo<LocatedUpdate>& output) {
  return std::make_unique<ParallelSearch>(std::move(name), clock, cu, count,
      update_base, row_base, binary_base, updates, metadata, output);
}
}  // namespace spine::sim::grasu_update_detail
