#include <iostream>
#include <stdexcept>

#include "memory.hpp"
#include "spine_sim/original_grasu/routing.hpp"
#include "spine_sim/original_grasu/search.hpp"

namespace {
using namespace grasu_test;
void require(bool value) { if (!value) throw std::runtime_error("G component assertion"); }
template <typename F> void rejected(F&& function) {
  bool threw = false;
  try { function(); } catch (const std::logic_error&) { threw = true; }
  require(threw);
}
void updates() {
  g::Segment original; original.fill(g::kEmpty);
  original[0] = 10; original[1] = 40; original[2] = 70;
  auto inserted = g::apply_update(original, {.edge = 20});
  require(inserted[0] == 10 && inserted[1] == 20 && inserted[2] == 40 && inserted[3] == 70);
  require(g::apply_update(inserted, {.edge = (1ull << 63) | 20}) == original);
  rejected([&] { g::apply_update(original, {.edge = 40}); });
  rejected([&] { g::apply_update(original, {.edge = (1ull << 63) | 20}); });
  rejected([&] { g::apply_update(original, {.edge = g::kEmpty}); });
  require(g::decode_segment(g::encode_segments(std::span<const g::Segment>(&original, 1))) == original);
}
void dispatch(bool reverse) {
  Memory memory(2, 4, 4);
  std::array<Fifo<g::Update>*, 4> input{}, output{};
  for (unsigned index = 0; index < 4; ++index) {
    input[index] = memory.queue<g::Update>("in" + std::to_string(index));
    output[index] = memory.queue<g::Update>("out" + std::to_string(index));
  }
  auto* route = memory.make<g::Dispatch>("dispatch", memory.clock, input, output);
  memory.register_components(reverse); route->begin(4);
  for (unsigned index = 0; index < 4; ++index) {
    const auto global = (index & 1) * g::kHotSegments * 2 + index / 2;
    require(input[index]->try_push({.edge = index + 20, .slot = global * 16}));
  }
  memory.scheduler.step();
  for (unsigned cycle = 0; cycle < 32 && !route->finished(); ++cycle) memory.scheduler.step();
  require(route->finished() && route->counters().updates == 4 && route->counters().ends == 4);
  for (auto* queue : output) {
    require(queue->size() == 2);
    g::Update item; require(queue->try_pop(item) && !item.end);
    memory.scheduler.step(); require(queue->try_pop(item) && item.end); memory.scheduler.step();
  }
  require(memory.drained());
}
std::uint64_t search(bool reverse) {
  Memory memory(2, 4, 16);
  g::SearchQueues inputs{}, results{};
  for (unsigned lane = 0; lane < 64; ++lane) {
    inputs[lane] = memory.queue<g::Update>("input" + std::to_string(lane));
    results[lane] = memory.queue<g::Update>("result" + std::to_string(lane));
  }
  auto edges = memory.link("edges", 0, 8, true);
  std::vector<g::Port> ports;
  for (unsigned index = 0; index < 8; ++index)
    ports.push_back(memory.link("table" + std::to_string(index), 0, 8).port());
  auto* output = memory.queue<g::Update>("merged");
  auto* reader = memory.make<g::EdgeReader>("reader", memory.clock, edges.stream(), inputs);
  auto* compute = memory.make<g::Search>("search", memory.clock, inputs, results, *output,
      std::array<g::Port, 8>{ports[0], ports[1], ports[2], ports[3], ports[4], ports[5], ports[6], ports[7]});
  auto bytes = [](std::initializer_list<std::uint64_t> words) {
    std::vector<std::uint8_t> result;
    for (auto word : words) for (unsigned byte = 0; byte < 8; ++byte) result.push_back(word >> (byte * 8));
    return result;
  };
  memory.backend->initialize_payload(0, 0, bytes({20, 148}));
  memory.backend->initialize_payload(0, 64, bytes({10, 138}));
  memory.backend->initialize_payload(0, 128, bytes({32}));
  memory.register_components(reverse);
  reader->begin(0, 2); compute->begin(2, 64, 128, 2, 1);
  for (unsigned cycle = 0; cycle < 10000 && !compute->finished(); ++cycle) memory.scheduler.step();
  require(reader->finished() && compute->finished() && output->size() == 2);
  require(compute->counters().reads == 4 && compute->counters().acknowledgements == 4);
  for (unsigned index = 0; index < 2; ++index) {
    g::Update item; require(output->try_pop(item) && item.edge == 20 + index * 128 && item.slot == index * 16);
    memory.scheduler.step();
  }
  require(memory.drained());
  return memory.scheduler.event_count();
}
}
int main() {
  try { updates(); dispatch(false); dispatch(true); require(search(false) == search(true)); std::cout << "original G components pass\n"; }
  catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
