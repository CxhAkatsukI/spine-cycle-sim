#include <algorithm>
#include <iostream>
#include <map>
#include <set>
#include <string_view>

#include "spine_sim/grasu_update/cached_processor.hpp"
#include "spine_sim/grasu_update/pma_word.hpp"

using namespace spine::sim;
using namespace spine::sim::grasu_update_detail;

namespace {
void require(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}

std::uint64_t run(unsigned pattern, bool reverse, bool degree,
                  bool invalid = false, std::size_t valid = kCachedHotSegments,
                  bool prompt_close = false) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {1, 16, 1, 16, 64, true});
  FixedAxiPort port("hot", clock,
      {.memory_channels = 1, .channel = 0, .initiator_id = 1,
       .data_width_bytes = 64, .request_fifo_depth = 1,
       .response_fifo_depth = 1, .read_beat_fifo_depth = 1,
       .read_reorder_capacity = 16, .stream_read_beats = true,
       .max_pending_requests = 2, .max_outstanding_bursts = 2}, backend);
  Fifo<LocatedUpdate> input("input", clock, 1);
  Fifo<DegreeDelta> output("degree", clock, 1);
  constexpr std::uint64_t base = 4096;
  std::vector<std::uint8_t> image(kCachedHotSegments * kGraSuSegmentBytes);
  for (std::size_t byte = 3; byte < image.size(); byte += 4) image[byte] = 0x80;
  std::map<unsigned, std::set<std::uint32_t>> expected;
  std::vector<LocatedUpdate> updates;
  const unsigned count = pattern == 3 ? 0 : 257;
  const auto transferred = (valid + 15) / 16 * 16;
  for (unsigned index = 0; index < count; ++index) {
    const unsigned segment = pattern == 4 ? valid - 1 : pattern == 5 ? valid :
                             pattern == 0 ? index % std::min<std::size_t>(32, valid) :
                             pattern == 1 ? 0 : (index % 8) * 16;
    auto [it, inserted] = expected.try_emplace(segment,
        std::set<std::uint32_t>{encode_grasu_pma_edge(10, 7)});
    if (inserted) {
      const auto word = *it->second.begin();
      for (unsigned byte = 0; byte < 4; ++byte)
        image[segment * 64 + byte] = static_cast<std::uint8_t>(word >> (byte * 8));
    }
    const auto word = encode_grasu_pma_edge(11, 7);
    const bool deletion = invalid || it->second.contains(word);
    if (deletion) it->second.erase(word);
    else it->second.insert(word);
    updates.push_back({index, 0, 0, segment * 32, 11, 7, deletion, 0});
  }
  backend.initialize_payload(0, base, image);
  bool closed = false;
  auto processor = make_cached_processor("processor", clock, base,
      {&input, {&port, nullptr}, {&port, nullptr}, degree ? &output : nullptr},
      [&closed] { return closed; }, valid);
  if (reverse) {
    scheduler.add_component(*processor); scheduler.add_component(output);
    scheduler.add_component(input); port.register_components(scheduler);
    scheduler.add_component(backend);
  } else {
    scheduler.add_component(backend); port.register_components(scheduler);
    scheduler.add_component(input); scheduler.add_component(output);
    scheduler.add_component(*processor);
  }
  unsigned sent = 0, received = 0;
  std::set<std::uint64_t> seen;
  bool checked_private_cache = false, held_close = false;
  std::uint64_t cycles = 0;
  for (; cycles < 1500000 && !processor->failed(); ++cycles) {
    if (sent < updates.size() && input.try_push(updates[sent])) ++sent;
    // The producer deliberately delays its end notification, including N=0.
    if (sent == updates.size() && (prompt_close || cycles > 350000)) closed = true;
    DegreeDelta delta;
    if ((prompt_close || cycles > 300000) && cycles % 5 == 0 && output.try_pop(delta)) {
      require(delta.global_index < updates.size() && delta.source == 0 &&
          delta.delta == (updates[delta.global_index].delete_op ? -1 : 1) &&
          seen.insert(delta.global_index).second, "cached degree lost or duplicated");
      ++received;
    }
    scheduler.step();
    if (!closed && processor->pma_reads() == transferred) {
      require(!processor->idle() && processor->pma_writes() == 0,
              "cache wrote back before the input-close barrier");
      held_close = true;
    }
    if (!checked_private_cache && processor->completed() && !processor->pma_writes()) {
      require(backend.inspect_payload(0, base, 64) ==
              std::vector<std::uint8_t>(image.begin(), image.begin() + 64),
              "cache update silently changed external PMA before writeback");
      checked_private_cache = true;
    }
    if (closed && processor->idle() && port.idle() && output.empty()) break;
  }
  if (invalid || pattern == 5) {
    require(processor->failed(), "cached invalid packet was accepted");
    return cycles;
  }
  if (processor->failed()) throw std::runtime_error(processor->failure());
  if (!(cycles < 1500000 && (held_close || prompt_close) && (count == 0 || checked_private_cache) &&
        processor->idle() && port.idle() && backend.outstanding() == 0 &&
        processor->completed() == count && received == (degree ? count : 0))) {
    std::cerr << "pattern=" << pattern << " reverse=" << reverse << " degree=" << degree
              << " cycles=" << cycles << " reads=" << processor->pma_reads()
              << " writes=" << processor->pma_writes() << " completed=" << processor->completed()
              << " received=" << received << " held_close=" << held_close
              << " private=" << checked_private_cache << '\n';
  }
  require(cycles < 1500000 && (held_close || prompt_close) && (count == 0 || checked_private_cache) &&
      processor->idle() && port.idle() && backend.outstanding() == 0 &&
      processor->completed() == count && received == (degree ? count : 0),
      "cached processor did not close all work");
  for (const auto& [segment, words] : expected) {
    std::array<std::uint32_t, kGraSuSegmentSlots> value;
    value.fill(kGraSuPmaEmpty);
    std::copy(words.begin(), words.end(), value.begin());
    const auto bytes = encode_segment(value);
    std::copy(bytes.begin(), bytes.end(), image.begin() + segment * 64);
  }
  require(backend.inspect_payload(0, base, image.size()) == image,
          "cached processor changed complete PMA state");
  const auto& stats = port.master().stats();
  const auto traffic = backend.traffic_stats();
  require(processor->pma_reads() == transferred &&
      processor->pma_writes() == transferred &&
      stats.requests_accepted == (valid ? 2U : 0U) &&
      stats.requests_completed == stats.requests_accepted &&
      stats.beats_issued == 2 * transferred &&
      stats.beats_completed == stats.beats_issued && !stats.zero_filled_write_bytes &&
      traffic.reads.bytes == transferred * 64 && traffic.writes.bytes == transferred * 64,
      "cache preload/writeback was free, repeated, or unacknowledged");
  if (count && degree && !prompt_close) require(processor->lane_queue_stalls() > 0,
                              "blocked publication did not backpressure finite queues");
  return cycles;
}
}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc == 2 && std::string_view(argv[1]) == "--extent-benchmark") {
      std::cout << "degree,valid_segments,transferred_segments,updates,cycles\n";
      for (const bool degree : {false, true})
        for (const auto valid : {1U, 16U, 17U, 1024U, 131072U}) {
          const auto cycles = run(1, false, degree, false, valid, true);
          require(cycles == run(1, true, degree, false, valid, true),
                  "prompt-close cache registration order changed cycles");
          std::cout << degree << ',' << valid << ',' << (valid + 15) / 16 * 16
                    << ",257," << cycles << '\n';
        }
      return 0;
    }
    require(argc == 1, "unknown cached processor test arguments");
    for (unsigned pattern = 0; pattern < 4; ++pattern)
      for (const bool degree : {false, true})
        require(run(pattern, false, degree) == run(pattern, true, degree),
                "cached registration order changed cycles");
    run(1, false, false, true);
    for (const auto valid : {1U, 15U, 16U, 17U, 131071U}) {
      for (const bool degree : {false, true})
        require(run(4, false, degree, false, valid) ==
                run(4, true, degree, false, valid),
                "bounded cache registration order changed cycles");
      run(5, false, false, false, valid);
    }
    require(run(3, false, false, false, 0) == run(3, true, false, false, 0),
            "zero-length cache registration order changed cycles");
    run(5, false, false, false, 0);
    std::cout << "cached processor complete-state/RAW/finite/degree/drain tests pass\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
