#pragma once

#include "memory.hpp"
#include "spine_sim/original_grasu/ddr.hpp"
#include "spine_sim/original_grasu/hot_store.hpp"
#include "spine_sim/original_grasu/routing.hpp"
#include "spine_sim/original_grasu/search.hpp"

namespace grasu_test {
inline constexpr std::uint32_t kHalf = g::kHotSegments + 32, kSegments = kHalf * 2;
inline constexpr std::uint64_t kBinary = 32ull << 20, kRows = 48ull << 20, kEdges = 64ull << 20;

struct System {
  System(unsigned depth, unsigned latency, unsigned credits, bool reverse)
      : memory(depth, latency, credits) {
    std::array<Fifo<g::Update>*, 4> search_outputs{}, routes{};
    for (unsigned kernel = 0; kernel < 4; ++kernel) {
      const auto prefix = "search" + std::to_string(kernel);
      g::SearchQueues input{}, results{};
      for (unsigned lane = 0; lane < 64; ++lane) {
        input[lane] = memory.queue<g::Update>(prefix + ".input" + std::to_string(lane));
        results[lane] = memory.queue<g::Update>(prefix + ".result" + std::to_string(lane));
      }
      search_outputs[kernel] = memory.queue<g::Update>(prefix + ".output");
      auto edges = memory.link(prefix + ".edges", kernel, 8, true);
      readers[kernel] = memory.make<g::EdgeReader>(prefix + ".reader", memory.clock, edges.stream(), input);
      std::vector<g::Port> ports;
      for (unsigned port = 0; port < 8; ++port)
        ports.push_back(memory.link(prefix + ".table" + std::to_string(port), kernel, 8).port());
      searches[kernel] = memory.make<g::Search>(prefix, memory.clock, input, results, *search_outputs[kernel],
          std::array<g::Port, 8>{ports[0], ports[1], ports[2], ports[3], ports[4], ports[5], ports[6], ports[7]});
      routes[kernel] = memory.queue<g::Update>("route" + std::to_string(kernel));
    }
    dispatch = memory.make<g::Dispatch>("dispatch", memory.clock, search_outputs, routes);
    for (unsigned half = 0; half < 2; ++half) {
      const auto prefix = "half" + std::to_string(half);
      const auto hot = memory.link(prefix + ".hot", half * 2, 64, true);
      stores[half] = memory.make<g::HotStore>(prefix + ".store", memory.clock, hot.stream());
      std::vector<Fifo<g::Update>*> cache_inputs, ddr_inputs;
      for (unsigned lane = 0; lane < 16; ++lane) {
        cache_inputs.push_back(memory.queue<g::Update>(prefix + ".cache" + std::to_string(lane)));
        cache[half][lane] = memory.make<g::CachePe>(prefix + ".pe" + std::to_string(lane), memory.clock,
            lane, *stores[half], *cache_inputs.back());
      }
      stores[half]->connect(cache[half]);
      for (unsigned lane = 0; lane < 32; ++lane)
        ddr_inputs.push_back(memory.queue<g::Update>(prefix + ".ddr" + std::to_string(lane)));
      cache_dispatch[half] = memory.make<g::PeDispatch>(prefix + ".cache_dispatch", memory.clock,
          *routes[half * 2], cache_inputs);
      ddr_dispatch[half] = memory.make<g::PeDispatch>(prefix + ".ddr_dispatch", memory.clock,
          *routes[half * 2 + 1], ddr_inputs);
      for (unsigned subpath = 0; subpath < 2; ++subpath) {
        std::array<Fifo<g::Update>*, 16> inputs{};
        for (unsigned lane = 0; lane < 16; ++lane) inputs[lane] = ddr_inputs[lane * 2 + subpath];
        auto read = memory.link(prefix + ".read" + std::to_string(subpath), half * 2 + 1, 64);
        auto write = memory.link(prefix + ".write" + std::to_string(subpath), half * 2 + 1, 64);
        ddr[half][subpath] = memory.make<g::DdrCore>(prefix + ".ddr" + std::to_string(subpath), memory.clock,
            subpath, inputs, read.port(), write.port());
      }
    }
    memory.register_components(reverse);
  }
  void begin(std::span<const std::uint64_t> updates) {
    if (started && !finished()) throw std::logic_error("G system restart before complete drain");
    for (unsigned kernel = 0; kernel < 4; ++kernel) {
      std::vector<std::uint8_t> edges;
      for (std::size_t index = kernel; index < updates.size(); index += 4)
        for (unsigned byte = 0; byte < 8; ++byte) edges.push_back(updates[index] >> (byte * 8));
      if (!edges.empty()) memory.backend->initialize_payload(kernel, kEdges, edges);
      readers[kernel]->begin(kEdges, edges.size() / 8);
      searches[kernel]->begin(edges.size() / 8, kBinary, kRows, kSegments, 2);
    }
    dispatch->begin(updates.size());
    for (unsigned half = 0; half < 2; ++half) {
      stores[half]->begin(); cache_dispatch[half]->begin(); ddr_dispatch[half]->begin();
      for (auto* pe : cache[half]) pe->begin();
      for (auto* core : ddr[half]) core->begin(0, kHalf);
    }
    started = true;
  }
  bool finished() const {
    if (!started || !dispatch->finished() || !memory.drained()) return false;
    for (unsigned kernel = 0; kernel < 4; ++kernel)
      if (!readers[kernel]->finished() || !searches[kernel]->finished()) return false;
    for (unsigned half = 0; half < 2; ++half) {
      if (!stores[half]->finished() || !cache_dispatch[half]->finished() || !ddr_dispatch[half]->finished()) return false;
      for (auto* pe : cache[half]) if (!pe->finished()) return false;
      for (auto* core : ddr[half]) if (!core->finished()) return false;
    }
    return true;
  }
  Memory memory;
  std::array<g::EdgeReader*, 4> readers{};
  std::array<g::Search*, 4> searches{};
  g::Dispatch* dispatch{};
  std::array<g::HotStore*, 2> stores{};
  std::array<g::PeDispatch*, 2> cache_dispatch{}, ddr_dispatch{};
  std::array<std::array<g::CachePe*, 16>, 2> cache{};
  std::array<std::array<g::DdrCore*, 2>, 2> ddr{};
  bool started{};
};
}  // namespace grasu_test
