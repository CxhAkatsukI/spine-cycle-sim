#include "bank_stream.hpp"

#include <algorithm>
#include <stdexcept>
#include "../detail/grasu_regraph_payload.hpp"

namespace spine::sim::detail {

BankStreamReader::BankStreamReader(const ReGraphPmaAdapterConfig &config, FixedAxiPort &memory,
    Fifo<PmaLoadedSegment> &loaded, ReGraphPmaAdapterCounters &counters)
    : config_(config), memory_(memory), loaded_(loaded), counters_(counters) {}

void BankStreamReader::start(ReGraphPmaPartition partition) {
  if (pending_ || !directory_.empty() || !banks_[0].empty() || !banks_[1].empty() || !pipeline_.empty())
    throw std::logic_error("bank reader restarted with live work");
  partition_ = partition;
  total_ = loader_base_ = loader_count_ = loader_segment_ = loader_last_ = 0;
  chunk_end_ = parity_ = interval_first_ = interval_end_ = 0;
  join_base_ = join_loaded_ = source_ = begin_ = end_ = segment_ = consumed_slots_ = 0;
  loader_ready_ = join_ready_ = 0;
  join_count_ = std::min<std::size_t>(1024, partition.vertices);
  extent_ready_ = !partition.vertices;
  row_selected_ = closed_ = false;
  phase_ = partition.vertices ? Phase::kExtent : Phase::kFinished;
}

void BankStreamReader::issue(Phase phase, std::uint64_t address, std::size_t channel,
                           std::size_t bytes, const CycleContext &context, std::size_t parity) {
  if (pending_ || !bytes) return;
  if (memory_.requests().try_push(AxiRequest{.transaction_id = next_id_,
      .operation = MemoryOperation::kRead, .address = address, .bytes = bytes,
      .stream_read_beats = config_.cross_row.bank_read_beats, .target_channel = channel, .write_data = {}}))
    staged_issue_ = Request{phase, next_id_, context.domain_cycle + config_.read_pipeline_cycles,
                            bytes, parity, bytes / 64, address};
}

void BankStreamReader::next_interval() {
  if (interval_first_ < interval_end_) return;
  if (parity_ == 0) parity_ = 1;
  else {
    loader_segment_ = chunk_end_;
    if (loader_segment_ == loader_last_) {
      loader_base_ += loader_count_;
      phase_ = loader_segment_ * 16 == total_ ? Phase::kFinished : Phase::kDirectory;
      return;
    }
    parity_ = 0;
    chunk_end_ = std::min(loader_last_, loader_segment_ + 2 * config_.cross_row.bank_fifo_lines);
  }
  interval_first_ = (loader_segment_ + 1 - parity_) / 2;
  interval_end_ = (chunk_end_ + 1 - parity_) / 2;
}

void BankStreamReader::receive(const AxiResponse &response) {
  const auto request = *pending_;
  if (response.transaction_id != request.id || !response.success || response.read_data.size() != request.bytes)
    throw std::runtime_error("bank stream requires complete acknowledged read data");
  ++counters_.responses;
  pending_.reset();
  if (request.phase == Phase::kExtent) {
    const auto offset = ((partition_.vertices - 1) * 8) & 63U;
    total_ = std::min<std::size_t>(decode_u32(response.read_data, offset), partition_.slots);
    if (total_ % 16) throw std::logic_error("unaligned bank-stream extent");
    extent_ready_ = true;
    phase_ = total_ ? Phase::kDirectory : Phase::kFinished;
  } else if (request.phase == Phase::kDirectory) {
    if (!directory_.empty()) throw std::logic_error("directory FIFO overwrite");
    for (std::size_t lane = 0; lane < loader_count_; ++lane)
      directory_.push_back(decode_u32(response.read_data, lane * 8) |
                          (std::uint64_t(decode_u32(response.read_data, lane * 8 + 4)) << 32));
    const auto end = std::min<std::size_t>(std::uint32_t(directory_.back()), partition_.slots);
    if (end % 16 || end < loader_segment_ * 16 || end > total_)
      throw std::logic_error("invalid bank tile extent");
    loader_last_ = end / 16;
    phase_ = Phase::kBanks;
    parity_ = 0;
    chunk_end_ = std::min(loader_last_, loader_segment_ + 2 * config_.cross_row.bank_fifo_lines);
    interval_first_ = (loader_segment_ + 1) / 2;
    interval_end_ = (chunk_end_ + 1) / 2;
  } else {
    auto &bank = banks_.at(request.parity);
    if (bank.size() + request.count > config_.cross_row.bank_fifo_lines)
      throw std::logic_error("bank FIFO reservation exceeded");
    for (std::size_t line = 0; line < request.count; ++line)
      bank.emplace_back(response.read_data.begin() + line * 64, response.read_data.begin() + (line + 1) * 64);
    interval_first_ += request.count;
    next_interval();
  }
}

} // namespace spine::sim::detail
