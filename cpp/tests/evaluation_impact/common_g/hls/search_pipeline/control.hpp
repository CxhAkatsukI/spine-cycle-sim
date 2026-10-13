#pragma once

#include "finite_host.hpp"
#include <chrono>
#include <iostream>

extern "C" void bin_search_pipeline(
    const unsigned long*, const search_pipeline::Raw*, const search_pipeline::Raw*,
    unsigned, hls::stream<search_pipeline::Packet>&);

namespace search_pipeline {
inline unsigned long check(const std::vector<unsigned long>& edges,
                           const std::vector<Raw>& binary,
                           const std::vector<Raw>& rows, bool stalled,
                           bool finite_control = true) {
  std::vector<Result> expected;
  unsigned long probes = 0;
  for (const auto raw : edges) {
    const auto key = raw & ~(1ul << 63);
    const unsigned source = key >> 32;
    if (source >= rows.size()) throw std::runtime_error("source outside test rows");
    const auto row = rows[source].to_uint64();
    unsigned begin = static_cast<unsigned>(row >> 32) >> 4;
    unsigned end = static_cast<unsigned>(row) >> 4;
    if (begin >= end || end > binary.size()) throw std::runtime_error("invalid test row extent");
    for (unsigned mid = (begin + end) / 2; begin != mid; mid = (begin + end) / 2) {
      ++probes;
      if (binary[mid].to_uint64() <= key) begin = mid;
      else end = mid;
    }
    Result result = raw;
    result <<= 32;
    expected.push_back(result | Result(begin * 16));
  }
  FiniteQueue<Packet> output_queue(2);
  hls::stream<Packet> output;
  if (finite_control) output.set_delegate(&output_queue);
  std::vector<Packet> actual;
  auto consume = [&] {
    if (stalled) std::this_thread::sleep_for(std::chrono::milliseconds(25));
    for (unsigned i = 0; i < edges.size(); ++i) {
      if (stalled && i % 17 == 0)
        std::this_thread::sleep_for(std::chrono::microseconds(50));
      actual.push_back(output.read());
    }
  };
  std::thread consumer;
  if (finite_control) consumer = std::thread(consume);
  bin_search_pipeline(edges.data(), binary.data(), rows.data(), edges.size(), output);
  if (finite_control) consumer.join();
  else consume();
  if (actual.size() != expected.size()) throw std::runtime_error("ordered result count");
  for (unsigned i = 0; i < actual.size(); ++i) {
    const auto& packet = actual[i];
    if (packet.data != expected[i] || packet.keep != decltype(packet.keep)(-1) ||
        packet.strb != decltype(packet.strb)(-1) || packet.last)
      throw std::runtime_error("ordered search packet mismatch");
  }
  const auto stats = output_queue.stats();
  if (finite_control) {
    const auto& report = last_host_report();
    if (report.channels.size() != 339) throw std::runtime_error("unexpected FIFO topology");
    const auto& requests = report.channels[337];
    const auto& responses = report.channels[338];
    if (requests.capacity != 32 || responses.capacity != 32 ||
        requests.writes != edges.size() + probes + 1 || responses.writes != requests.writes)
      throw std::runtime_error("metadata request/response ledger mismatch");
    if (stats.writes != edges.size() || stats.reads != edges.size() || output_queue.size())
      throw std::runtime_error("output FIFO did not drain");
  }
  std::cout << "SEARCH_PIPELINE_PASS updates=" << edges.size() << " probes=" << probes
            << " stalled=" << stalled << " channels=" << (finite_control ? 339 : 0)
            << " output_blocked=" << stats.blocked_writes
            << " host_vendor_keep_bits=" << Packet::width_keep << '\n';
  return probes;
}

inline void check_selector() {
  for (unsigned mask = 1; mask < 256; ++mask)
    for (unsigned cursor = 0; cursor < 8; ++cursor) {
      unsigned expected = cursor;
      while (!(mask & (1u << expected))) expected = (expected + 1) % 8;
      if (select_ready(mask, cursor).to_uint() != expected)
        throw std::runtime_error("eight-way round-robin mismatch");
    }
}
}  // namespace search_pipeline
