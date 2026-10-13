#include <iostream>

#include "memory.hpp"
#include "spine_sim/original_grasu/hot_store.hpp"

namespace {
using namespace grasu_test;
void require(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}

std::uint64_t run(bool forward, bool reverse, bool alias) {
  Memory memory(1, 4, 16);
  const auto port = memory.link("hot", 0, 64, true);
  auto* store = memory.make<g::HotStore>("store", memory.clock, port.stream());
  std::array<g::CachePe*, 16> lanes{};
  std::array<Fifo<g::Update>*, 16> inputs{};
  g::Timing timing;
  timing.cache_forward_pending = forward;
  for (unsigned bank = 0; bank < 16; ++bank) {
    inputs[bank] = memory.queue<g::Update>("input" + std::to_string(bank));
    lanes[bank] = memory.make<g::CachePe>("pe" + std::to_string(bank), memory.clock,
                                        bank, *store, *inputs[bank], timing);
  }
  store->connect(lanes);
  std::vector<g::Segment> expected(g::kHotSegments);
  for (auto& segment : expected) { segment.fill(g::kEmpty); segment[0] = 10; }
  const auto initial = g::encode_segments(expected);
  memory.backend->initialize_payload(0, 0, initial);
  memory.register_components(reverse);
  store->begin();
  for (auto* lane : lanes) lane->begin();
  std::array<bool, 16> ended{};
  std::vector<std::uint64_t> accepted;
  unsigned sent = 0;
  std::uint64_t cycles = 0;
  for (; cycles < 1000000 && !store->finished(); ++cycles) {
    if (sent < 33) {
      const auto index = alias ? (sent % 4 / 2) * 16 : 0;
      const g::Update update{.edge = ((sent & 1) ? 1ull << 63 : 0) | 20,
                             .slot = index * 32};
      if (inputs[0]->try_push(update)) {
        expected[index] = g::apply_update(expected[index], update);
        ++sent;
      }
    }
    for (unsigned bank = 0; bank < 16; ++bank)
      if (!ended[bank] && (bank != 0 || sent == 33) && inputs[bank]->try_push({.end = true}))
        ended[bank] = true;
    const auto before = lanes[0]->counters().updates;
    memory.scheduler.step();
    if (lanes[0]->counters().updates != before) {
      accepted.push_back(cycles);
      if (accepted.size() == 1)
        require(store->segment(0)[1] == g::kEmpty, "cache edit retired before declared latency");
    }
  }
  require(store->finished() && memory.drained(), "cache did not drain preload/writeback/ends");
  require(accepted.size() == 33, "cache update loss");
  for (std::size_t index = 1; index < accepted.size(); ++index)
    require(accepted[index] - accepted[index - 1] ==
                (forward || (alias && index % 2 == 0) ? 3U : 8U),
            "same-bank cache interval differs from declared control");
  require(lanes[0]->counters().reads == 33 && lanes[0]->counters().writes == 33 &&
          lanes[0]->counters().ends == 1, "cache work not conserved");
  require(forward ? lanes[0]->counters().dependency_stalls == 0 :
                   lanes[0]->counters().dependency_stalls > 0, "RAW control not exercised");
  require(memory.backend->inspect_payload(0, 0, initial.size()) == g::encode_segments(expected),
          "forwarded cache full-state mismatch");
  const auto& stats = port.master->stats();
  require(stats.requests_accepted == 2 && stats.requests_completed == 2 &&
          stats.beats_issued == g::kHotSegments * 2 && stats.beats_completed == stats.beats_issued &&
          stats.zero_filled_write_bytes == 0, "cache transfers not conserved");
  return cycles;
}
}  // namespace

int main() {
  try {
    for (const auto alias : {false, true})
      for (const auto forward : {false, true})
        require(run(forward, false, alias) == run(forward, true, alias),
                "cache registration order changed cycles");
    std::cout << "original G legacy/forwarded cache finite timing and state pass\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
