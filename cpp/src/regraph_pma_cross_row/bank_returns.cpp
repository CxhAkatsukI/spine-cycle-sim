#include "bank_stream.hpp"

#include <algorithm>
#include <stdexcept>
#include "../detail/grasu_regraph_payload.hpp"

namespace spine::sim::detail {

bool BankStreamReader::beat_space() const {
  if (pending_->received == pending_->count) return false;
  if (pending_->phase == Phase::kBanks)
    return banks_.at(pending_->parity).size() < config_.cross_row.bank_fifo_lines;
  return pending_->phase != Phase::kDirectory || directory_.size() + 8 <= 1024;
}

void BankStreamReader::receive_beat(const AxiReadBeatResponse &beat) {
  auto &request = *pending_;
  if (!beat.success || beat.transaction_id != request.id || beat.read_data.size() != 64 ||
      request.received >= request.count || beat.address != request.address + request.received * 64 ||
      beat.parent_offset != request.received * 64 || beat.last != (request.received + 1 == request.count))
    throw std::logic_error("bank read beat address/order/extent mismatch");
  if (request.phase == Phase::kExtent) {
    const auto offset = ((partition_.vertices - 1) * 8) & 63U;
    total_ = std::min<std::size_t>(decode_u32(beat.read_data, offset), partition_.slots);
    if (total_ % 16) throw std::logic_error("unaligned bank-stream extent");
    extent_ready_ = true;
  } else if (request.phase == Phase::kDirectory) {
    for (unsigned lane = 0; lane < 8 && request.received * 8 + lane < loader_count_; ++lane) {
      last_directory_row_ = decode_u32(beat.read_data, lane * 8) |
          (std::uint64_t(decode_u32(beat.read_data, lane * 8 + 4)) << 32);
      directory_.push_back(last_directory_row_);
    }
    if (directory_.size() > 1024) throw std::logic_error("directory FIFO overflow");
  } else {
    auto &bank = banks_.at(request.parity);
    bank.push_back(beat.read_data);
    if (bank.size() > config_.cross_row.bank_fifo_lines) throw std::logic_error("bank FIFO overflow");
  }
  ++request.received;
}

void BankStreamReader::finish_stream_read() {
  const auto request = *pending_;
  pending_.reset();
  if (request.phase == Phase::kExtent) phase_ = total_ ? Phase::kDirectory : Phase::kFinished;
  else if (request.phase == Phase::kDirectory) {
    const auto end = std::min<std::size_t>(std::uint32_t(last_directory_row_), partition_.slots);
    if (end % 16 || end < loader_segment_ * 16 || end > total_)
      throw std::logic_error("invalid bank tile extent");
    loader_last_ = end / 16;
    phase_ = Phase::kBanks;
    parity_ = 0;
    chunk_end_ = std::min(loader_last_, loader_segment_ + 2 * config_.cross_row.bank_fifo_lines);
    interval_first_ = (loader_segment_ + 1) / 2;
    interval_end_ = (chunk_end_ + 1) / 2;
  } else {
    interval_first_ += request.count;
    next_interval();
  }
}

} // namespace spine::sim::detail
