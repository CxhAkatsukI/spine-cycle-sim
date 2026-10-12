#include "state.hpp"

#include <algorithm>
#include <stdexcept>

#include "../detail/grasu_regraph_payload.hpp"

namespace spine::sim::detail {

bool CrossRowPmaAdapter::issue(Kind kind, Task task, std::uint64_t address,
                             std::size_t channel, const CycleContext &context, std::size_t bytes) {
  if (pending_.size() >= config_.pending_read_capacity) return false;
  if (!memory_.requests().try_push(AxiRequest{
          .transaction_id = next_id_, .operation = MemoryOperation::kRead,
          .address = address, .bytes = bytes, .stream_read_beats = false,
          .target_channel = channel, .write_data = {}})) return false;
  staged_issue_ = Pending{kind, task, context.domain_cycle + config_.read_pipeline_cycles};
  return true;
}

void CrossRowPmaAdapter::begin_row() {
  const auto row = tile_ ? tile_->row(source_ - block_) : rows_.at(source_ - block_);
  begin_ = row >> 32;
  end_ = std::min<std::size_t>(std::uint32_t(row), partition_.slots);
  if (begin_ != issued_slots_ || end_ < begin_ || end_ > total_slots_ || begin_ % 16 || end_ % 16)
    throw std::logic_error("cross-row model requires contiguous aligned PMA rows");
  segment_ = begin_ / 16;
  ++counters_.rows_visited;
  if (begin_ == end_) ++counters_.empty_rows;
}

void CrossRowPmaAdapter::receive(const AxiResponse &response) {
  const auto pending = pending_.at(response.transaction_id);
  const auto bytes = tile_ && pending.kind == Kind::kDirectory
      ? PmaDirectoryTile::bytes(block_, partition_.vertices, config_.cross_row.directory_cache_rows) : 64;
  if (!response.success || response.read_data.size() != bytes)
    throw std::runtime_error("cross-row adapter requires a successful full-line response");
  pending_.erase(response.transaction_id);
  ++counters_.responses;
  if (pending.kind == Kind::kSegment) {
    if (!returned_.emplace(response.transaction_id, response.read_data).second)
      throw std::logic_error("duplicate cross-row response");
    return;
  }
  if (pending.kind == Kind::kExtent) {
    const auto offset = ((partition_.row_base + pending.task.source * 8) & 63U);
    total_slots_ = std::min<std::size_t>(decode_u32(response.read_data, offset), partition_.slots);
    if (total_slots_ % 16) throw std::logic_error("cross-row final extent is not aligned");
    stream_complete_ = total_slots_ == 0;
    phase_ = total_slots_ ? Phase::kDirectory : Phase::kTerminal;
    return;
  }
  block_count_ = std::min<std::size_t>(config_.cross_row.directory_cache_rows, partition_.vertices - block_);
  bool occupied = false;
  if (tile_) occupied = tile_->load(response.read_data, block_count_, partition_.slots);
  else for (std::size_t lane = 0; lane < block_count_; ++lane) {
    rows_[lane] = decode_u32(response.read_data, lane * 8) |
        (std::uint64_t(decode_u32(response.read_data, lane * 8 + 4)) << 32);
    const auto begin = rows_[lane] >> 32;
    const auto end = std::min<std::size_t>(std::uint32_t(rows_[lane]), partition_.slots);
    occupied |= (begin >> 4) < ((end + 15) >> 4);
  }
  source_ = block_;
  if (occupied) {
    begin_row();
    phase_ = Phase::kScan;
  } else {
    // V3 bypasses the deep pipeline only for an entirely empty cached block.
    for (; source_ < block_ + block_count_; ++source_) begin_row();
    block_ += block_count_;
    phase_ = block_ < partition_.vertices ? Phase::kDirectory : Phase::kTerminal;
  }
}

void CrossRowPmaAdapter::finish_block(const CycleContext &context) {
  // The continuous reader crosses line boundaries with segment requests still
  // live; the same finite port/FIFO retain their traffic and backpressure.
  if (config_.cross_row.continuous_directory && issued_slots_ < total_slots_) {
    block_ += block_count_;
    phase_ = Phase::kDirectory;
    return;
  }
  phase_ = Phase::kDrain;
  drain_until_ = context.domain_cycle + config_.cross_row.block_drain_cycles;
}

} // namespace spine::sim::detail
