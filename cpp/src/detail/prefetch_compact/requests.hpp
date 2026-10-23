#pragma once

namespace spine::sim::detail::prefetch_compact {
inline std::size_t Reader::outstanding_directory() const {
  return std::count_if(pending_.begin(), pending_.end(), [this](const auto& item) {
    return item.second.kind == Kind::kDirectory && item.second.directory_base == directory_.base();
  });
}

inline std::size_t Reader::outstanding(std::size_t port) const {
  return std::count_if(pending_.begin(), pending_.end(), [port](const auto& item) {
    return item.second.port == port;
  });
}

inline void Reader::prepare_request(const CycleContext& context, std::size_t port) {
  if (outstanding(port) >= 16) return;
  Request request;
  std::size_t channel = partition_.row_channel;
  bool selected = false;
  if (!extent_) {
    if (port != (directory_memory_ ? 2U : 0U) || !pending_.empty()) return;
    request = {Kind::kExtent, next_id_, (partition_.row_base + (partition_.vertices - 1) * 8) &
        ~std::uint64_t{63}, context.domain_cycle + delay_, 0, 1};
    selected = true;
  } else {
    for (unsigned attempt = 0; attempt < 3 && !selected; ++attempt) {
      const auto which = (preference_ + attempt) % 3;
      if (directory_memory_) {
        if ((which == 0 ? 2U : which - 1) != port) continue;
      } else if (odd_memory_ && ((which == 2) != (port == 1))) continue;
      if (which == 0) {
        const auto read = directory_.next();
        if (consumed_ == total_ || !read) continue;
        request = {Kind::kDirectory, next_id_, partition_.row_base + read->base * 8 + read->first * 64,
            context.domain_cycle + delay_, read->first, read->count};
        request.directory_base = read->base;
      } else {
        const auto parity = which - 1;
        const auto end = (total_ / 16 + 1 - parity) / 2;
        const auto first = issued_[parity], occupied = first - released_[parity];
        if (first == end || occupied == 256) continue;
        const auto half = partition_.cache_segments_per_half;
        const auto stop = first < half ? std::min(end, half) : end;
        // Reserve a whole parent before issuing; only physical bank tails may be short.
        if (refill_ == RefillPolicy::kFullBurst &&
            256 - occupied < std::min(std::size_t{16}, stop - first)) continue;
        const auto count = std::min({std::size_t{16}, stop - first, 256 - occupied});
        const auto bank = parity * 2 + (first < half ? 0 : 1);
        channel = partition_.pma_channel[bank];
        request = {Kind::kPma, next_id_, partition_.pma_base[bank] + first * 64,
            context.domain_cycle + delay_, first, count, parity};
      }
      selected = true;
    }
  }
  request.id = next_id_ + port;
  request.port = port;
  if (selected && memory(port).requests().try_push(AxiRequest{.transaction_id = request.id,
      .operation = MemoryOperation::kRead, .address = request.address, .bytes = request.count * 64,
      .stream_read_beats = true, .target_channel = channel, .write_data = {}})) issues_[port] = request;
}

inline void Reader::accept_beat(const AxiReadBeatResponse& beat, std::uint64_t cycle) {
  auto& request = pending_.at(beat.transaction_id);
  check(beat.success && beat.read_data.size() == 64 && request.received < request.count &&
      beat.parent_offset == request.received * 64 && beat.address == request.address + beat.parent_offset &&
      beat.last == (request.received + 1 == request.count), "candidate beat/order mismatch");
  const auto index = request.first + request.received;
  if (request.kind == Kind::kExtent) {
    ++stats_.extent_beats;
    total_ = word(beat.read_data, ((partition_.vertices - 1) * 8) & 63U);
    check(total_ == partition_.slots && total_ % 16 == 0, "candidate normalized extent mismatch");
    extent_ = true;
  } else if (request.kind == Kind::kDirectory) {
    ++stats_.directory_beats;
    directory_.accept(request.directory_base, index, beat.read_data, cycle);
  } else {
    ++stats_.pma_beats;
    auto& line = banks_[request.parity][index % 256];
    check(line.reserved && !line.ready, "candidate bank ring overwrite");
    for (unsigned lane = 0; lane < 16; ++lane) line.words[lane] = word(beat.read_data, lane * 4);
    line.ready = true;
  }
  ++request.received;
  ++stats_.beats;
}
}  // namespace spine::sim::detail::prefetch_compact
