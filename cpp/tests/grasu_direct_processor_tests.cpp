#include <algorithm>
#include <iostream>
#include <map>
#include <set>

#include "spine_sim/grasu_update/processor.hpp"
#include "spine_sim/grasu_update/pma_word.hpp"

using namespace spine::sim;
using namespace spine::sim::grasu_update_detail;

namespace {
void require(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}

std::uint64_t run(DirectProcessorTopology topology, unsigned pattern,
                  bool reverse, bool degree, bool invalid = false) {
  Scheduler scheduler;
  const auto clock = scheduler.add_clock_mhz("G", 200);
  MockMemoryBackend backend("memory", clock, {1, 64, 1, 2, 64, true});
  FixedAxiPort port("PMA", clock,
      {.memory_channels = 1, .channel = 0, .initiator_id = 1,
       .data_width_bytes = 64, .request_fifo_depth = 1,
       .response_fifo_depth = 1, .max_pending_requests = 2,
       .max_outstanding_bursts = 2}, backend);
  Fifo<LocatedUpdate> input("input", clock, 1);
  Fifo<DegreeDelta> output("degree", clock, 1);
  const std::vector<std::uint64_t> bases;
  auto processor = make_direct_processor("processor", clock, topology, 1,
      0, 0, bases, false, GraSuPmaWordAbi::kWeightedFullWord,
      {&input, {&port, nullptr}, {&port, nullptr}, degree ? &output : nullptr});
  std::map<unsigned, std::set<std::uint32_t>> expected;
  std::vector<LocatedUpdate> updates;
  std::vector<std::int32_t> deltas;
  const unsigned count = pattern == 3 ? 0 : 257;
  for (unsigned index = 0; index < count; ++index) {
    const unsigned segment = pattern == 0 ? index % 32 :
                             pattern == 1 ? 0 : (index % 8) * 16;
    auto [it, inserted] = expected.try_emplace(segment,
        std::set<std::uint32_t>{encode_grasu_pma_edge(10, 7)});
    if (inserted) {
      std::array<std::uint32_t, kGraSuSegmentSlots> words;
      words.fill(kGraSuPmaEmpty); words[0] = *it->second.begin();
      backend.initialize_payload(0, segment * 64, encode_segment(words));
    }
    const auto word = encode_grasu_pma_edge(11, 7);
    const bool deletion = invalid || it->second.contains(word);
    if (deletion) it->second.erase(word);
    else it->second.insert(word);
    updates.push_back({index, 0, 0, segment * 32, 11, 7, deletion, 0});
    deltas.push_back(deletion ? -1 : 1);
  }
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
  std::uint64_t cycles = 0;
  for (; cycles < 200000 && !processor->failed(); ++cycles) {
    if (sent < updates.size() && input.try_push(updates[sent])) ++sent;
    DegreeDelta delta;
    // Hold publication long enough to force the bounded lane/input queues full.
    if (cycles > 3000 && cycles % 5 == 0 && output.try_pop(delta)) {
      require(delta.global_index < deltas.size() && delta.source == 0 &&
          delta.delta == deltas[delta.global_index] && seen.insert(delta.global_index).second,
          "degree sideband duplicated, lost, or changed");
      ++received;
    }
    scheduler.step();
    if (sent == updates.size() && processor->idle() && port.idle() &&
        output.empty()) break;
  }
  if (invalid) {
    require(processor->failed(), "invalid delete was accepted");
    return cycles;
  }
  require(processor->idle() && port.idle() && backend.outstanding() == 0 &&
      processor->completed() == updates.size() &&
      received == (degree ? updates.size() : 0), "processor did not drain");
  for (const auto& [segment, values] : expected) {
    std::array<std::uint32_t, kGraSuSegmentSlots> words;
    words.fill(kGraSuPmaEmpty);
    std::copy(values.begin(), values.end(), words.begin());
    require(decode_segment(backend.inspect_payload(0, segment * 64, 64)) == words,
            "segment lost a same-owner update");
  }
  const auto& stats = port.master().stats();
  const auto traffic = backend.traffic_stats();
  require(stats.requests_accepted == updates.size() * 2 &&
      stats.requests_accepted == stats.requests_completed &&
      stats.beats_issued == stats.beats_completed &&
      traffic.reads.bytes == updates.size() * 64 &&
      traffic.writes.bytes == updates.size() * 64,
      "physical RMW requests were lost or made free");
  return cycles;
}
}  // namespace

int main() {
  try {
    for (const auto topology : {DirectProcessorTopology::kSequentialHot,
                               DirectProcessorTopology::kParallelHot}) {
      for (unsigned pattern = 0; pattern < 4; ++pattern)
        for (const bool degree : {false, true})
          require(run(topology, pattern, false, degree) ==
                  run(topology, pattern, true, degree),
                  "registration order changed processor cycles");
      run(topology, 1, false, false, true);
    }
    require(run(DirectProcessorTopology::kParallelHot, 0, false, false) <
            run(DirectProcessorTopology::kSequentialHot, 0, false, false),
            "independent segments failed to overlap");
    require(run(DirectProcessorTopology::kParallelHot, 1, false, false) ==
            run(DirectProcessorTopology::kSequentialHot, 1, false, false),
            "same segment incorrectly gained parallel RMW");
    std::cout << "direct processor bounded/order/RAW/degree/traffic tests pass\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
