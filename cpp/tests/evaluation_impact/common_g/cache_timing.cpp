#include <algorithm>
#include <array>
#include <iostream>
#include <stdexcept>
#include <vector>

#include "spine_sim/grasu_update/cached_processor.hpp"
#include "spine_sim/grasu_update/pma_word.hpp"

using namespace spine::sim;
using namespace spine::sim::grasu_update_detail;

namespace {
struct Observation {
  std::uint64_t cycles{}, load_complete{}, store_issued{}, updates{}, read_bytes{},
      write_bytes{}, stalls{};
  bool operator==(const Observation&) const = default;
};

void require(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}

Observation run(unsigned count, bool conflict, bool reverse) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {1, 16, 1, 16, 64, true});
  FixedAxiPort port("hot", clock,
      {.memory_channels = 1, .channel = 0, .initiator_id = 1,
       .data_width_bytes = 64, .request_fifo_depth = 1,
       .response_fifo_depth = 1, .read_beat_fifo_depth = 1,
       .read_reorder_capacity = 16, .stream_read_beats = true,
       .max_pending_requests = 2, .max_outstanding_bursts = 2}, backend);
  Fifo<LocatedUpdate> input("input", clock, 2);
  constexpr std::uint64_t base = 4096;
  std::vector<std::array<std::uint32_t, kGraSuSegmentSlots>> oracle(kCachedHotSegments);
  std::vector<std::uint8_t> image;
  image.reserve(kCachedHotSegments * kGraSuSegmentBytes);
  for (auto& segment : oracle) {
    for (unsigned lane = 0; lane < segment.size(); ++lane)
      segment[lane] = lane < 15 ? 2 * lane + 2 : kGraSuPmaEmpty;
    const auto bytes = encode_segment(segment);
    image.insert(image.end(), bytes.begin(), bytes.end());
  }
  backend.initialize_payload(0, base, image);
  std::vector<LocatedUpdate> updates;
  for (unsigned index = 0; index < count; ++index) {
    const unsigned bank = conflict ? 0 : index % 16;
    const unsigned occurrence = conflict ? index : index / 16;
    const bool erase = occurrence & 1;
    auto& segment = oracle[bank];
    const auto position = std::lower_bound(segment.begin(), segment.end(), 17u);
    require(position != segment.end(), "invalid timing-control oracle position");
    if (erase) {
      require(*position == 17, "timing-control oracle delete is absent");
      std::move(position + 1, segment.end(), position);
      segment.back() = kGraSuPmaEmpty;
    } else {
      require(*position != 17 && segment.back() == kGraSuPmaEmpty,
              "timing-control oracle insert lacks reservation");
      std::move_backward(position, segment.end() - 1, segment.end());
      *position = 17;
    }
    // Weight zero preserves the RTL bench's literal full-word key 17.
    require(encode_grasu_pma_edge(17, 0) == 17, "timing-control key ABI changed");
    updates.push_back({index, 0, 0, bank << 5, 17, 0, erase, 0});
  }
  bool closed = count == 0;
  auto processor = make_cached_processor("processor", clock, base,
      {&input, {&port, nullptr}, {&port, nullptr}, nullptr},
      [&closed] { return closed; });
  if (reverse) {
    scheduler.add_component(*processor);
    scheduler.add_component(input);
    port.register_components(scheduler);
    scheduler.add_component(backend);
  } else {
    scheduler.add_component(backend);
    port.register_components(scheduler);
    scheduler.add_component(input);
    scheduler.add_component(*processor);
  }
  Observation result;
  unsigned sent = 0;
  for (; result.cycles < 2000000;) {
    if (sent < updates.size() && input.try_push(updates[sent])) ++sent;
    scheduler.step();
    ++result.cycles;
    if (sent == updates.size()) closed = true;
    if (processor->failed()) throw std::runtime_error(processor->failure());
    if (!result.load_complete && processor->pma_reads() == kCachedHotSegments)
      result.load_complete = result.cycles;
    if (!result.store_issued && processor->pma_writes() == kCachedHotSegments)
      result.store_issued = result.cycles;
    if (processor->idle() && port.idle() && backend.outstanding() == 0) break;
  }
  require(result.cycles < 2000000 && processor->idle() && port.idle() &&
              !backend.outstanding() && input.empty() && sent == count &&
              processor->completed() == count && result.load_complete &&
              result.store_issued > result.load_complete,
          "timing-control work or write acknowledgement did not drain");
  image.clear();
  for (const auto& segment : oracle) {
    const auto bytes = encode_segment(segment);
    image.insert(image.end(), bytes.begin(), bytes.end());
  }
  require(backend.inspect_payload(0, base, image.size()) == image,
          "timing-control full-cache state mismatch");
  const auto& stats = port.master().stats();
  const auto traffic = backend.traffic_stats();
  require(processor->pma_reads() == kCachedHotSegments &&
              processor->pma_writes() == kCachedHotSegments &&
              stats.requests_accepted == 2 && stats.requests_completed == 2 &&
              stats.beats_issued == 2 * kCachedHotSegments &&
              stats.beats_completed == stats.beats_issued &&
              !stats.zero_filled_write_bytes && traffic.reads.bytes == image.size() &&
              traffic.writes.bytes == image.size(),
          "timing-control full-cache traffic was omitted or repeated");
  result.updates = processor->completed();
  result.read_bytes = traffic.reads.bytes;
  result.write_bytes = traffic.writes.bytes;
  result.stalls = processor->lane_queue_stalls();
  return result;
}
}  // namespace

int main() {
  try {
    constexpr std::array<unsigned, 6> counts{0, 16, 64, 4096, 65536, 4096};
    std::array<Observation, counts.size()> rows;
    for (unsigned index = 0; index < counts.size(); ++index) {
      rows[index] = run(counts[index], index == 5, false);
      require(rows[index] == run(counts[index], index == 5, true),
              "timing-control registration order changed observations");
    }
    std::cout << "{\"schema\":1,\"complete_state_and_traffic_checked\":true,"
                 "\"reverse_registration_checked\":true,\"input_fifo_depth\":2,"
                 "\"memory_backend\":\"MockMemoryBackend\",\"rows\":[";
    for (unsigned index = 0; index < rows.size(); ++index) {
      const auto& row = rows[index];
      if (index) std::cout << ',';
      std::cout << "{\"index\":" << index << ",\"updates\":" << row.updates
                << ",\"conflict\":" << (index == 5 ? "true" : "false")
                << ",\"cycles\":" << row.cycles
                << ",\"load_complete\":" << row.load_complete
                << ",\"store_issued\":" << row.store_issued
                << ",\"read_bytes\":" << row.read_bytes
                << ",\"write_bytes\":" << row.write_bytes
                << ",\"lane_queue_stalls\":" << row.stalls << '}';
    }
    std::cout << "]}\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
