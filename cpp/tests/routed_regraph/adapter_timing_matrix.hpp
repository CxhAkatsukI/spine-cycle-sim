#pragma once

#include "adapter_fixture.hpp"

#include <iostream>

namespace routed_adapter_test {

struct TimingCase {
  unsigned vertices, placement, segments, latency, stall;
};

inline constexpr std::array<TimingCase, 12> timing_cases{{
    {0, 0, 1, 1, 0}, {1, 0, 1, 1, 0}, {8, 0, 1, 1, 0}, {9, 0, 1, 1, 0},
    {17, 0, 1, 1, 0}, {17, 0, 1, 64, 0}, {17, 0, 1, 128, 0}, {17, 0, 3, 64, 0},
    {17, 1, 1, 64, 0}, {17, 2, 1, 64, 0}, {17, 3, 1, 64, 0}, {17, 0, 1, 64, 1000}}};

// Exact logical input of adapter_axi_tb.sv; the C++ and RTL memory engines differ.
inline Data timing_data(const TimingCase &trial) {
  Data data(trial.vertices, false, true, ReGraphPmaFormat::kWeighted, 2);
  data.partition.destination_vertices = 32;
  data.partition.row_base = 0x80000;
  data.partition.row_channel = 0;
  data.partition.pma_base = {0x10000, 0x20000, 0x30000, 0x40000};
  data.partition.pma_channel = {0, 0, 0, 0};
  for (auto &bank : data.pma) bank.assign(128 * 16, 0);
  std::size_t cursor = 0;
  for (unsigned source = 0; source < trial.vertices; ++source) {
    const auto begin = cursor;
    const bool occupied = trial.placement == 0 || (trial.placement == 1 && source + 1 == trial.vertices) ||
        (trial.placement == 2 && source == 0) || (trial.placement == 3 && source % 7 == 0);
    if (occupied) {
      data.last_source = source;
      for (unsigned segment = 0; segment < trial.segments; ++segment) {
        const auto bank = (cursor / 16 < 4 ? 0 : 1) + (cursor / 16 % 2 ? 2 : 0);
        std::array<ReGraphPmaPacket, 2> packets;
        for (unsigned lane = 0; lane < 16; ++lane) {
          const auto dummy = lane % 3 == 0 ? 0x80000000U : 0U;
          const auto raw = static_cast<std::uint32_t>(((cursor / 16 + 1) << 19) | lane | dummy);
          data.pma[bank][cursor / 32 * 16 + lane] = raw;
          packets[lane / 8].sources[lane % 8] = source | dummy;
          packets[lane / 8].destinations[lane % 8] = raw;
        }
        data.expected.insert(data.expected.end(), packets.begin(), packets.end());
        cursor += 16;
      }
    }
    data.rows[source * 2] = static_cast<std::uint32_t>(cursor);
    data.rows[source * 2 + 1] = static_cast<std::uint32_t>(begin);
  }
  data.partition.slots = cursor;
  if (!data.expected.empty()) data.expected.back().last = true;
  return data;
}

template<class Run>
void timing_matrix(Run &&run) {
  for (std::size_t index = 0; index < timing_cases.size(); ++index) {
    const auto trial = timing_cases[index];
    const auto data = timing_data(trial);
    for (bool candidate : {false, true}) {
      const auto result = run(data, candidate, trial.latency, trial.stall);
      const auto &c = result.counters;
      std::cout << "{\"trial\":" << index << ",\"candidate\":" << (candidate ? "true" : "false")
                << ",\"cycles_to_sink_empty\":" << result.cycles
                << ",\"adapter_done\":" << result.adapter_done
                << ",\"stream_done\":" << result.stream_done
                << ",\"row_reads\":" << c.row_reads << ",\"extent_reads\":" << c.extent_reads
                << ",\"segment_reads\":" << c.segment_reads << ",\"packets\":" << c.packets
                << ",\"live_edges\":" << c.live_edges << ",\"dummy_edges\":" << c.dummy_edges
                << ",\"max_pending_reads\":" << c.max_pending_reads
                << ",\"exact_packets_and_traffic\":true}\n";
    }
  }
}

} // namespace routed_adapter_test
