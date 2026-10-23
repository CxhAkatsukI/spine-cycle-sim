#pragma once

#include "bootstrap.hpp"
#include "../warm_comparison/host_preparation.hpp"
#include <chrono>
#include <iostream>

namespace figure_refresh {
inline void host(const wc::Input& input, const std::string& arm) {
  for (unsigned repeat = 0; repeat < 5; ++repeat) {
    std::uint64_t bytes = 0;
    std::uint64_t graph_bytes = 0, directory_bytes = 0, metadata_bytes = 0, calls = 0;
    const auto begin = std::chrono::steady_clock::now();
    if (arm == "spine") {
      auto config = spine_config();
      auto state = preload_spine_resident_snapshot(slice(input, false), config);
      auto batch = slice(input, true);
      std::stable_sort(batch.edges.begin(), batch.edges.end(), [](const auto& a, const auto& b) {
        return std::tie(a.src, a.dst, a.weight, a.diff) < std::tie(b.src, b.dst, b.weight, b.diff);
      });
      BootstrapCapture capture(config);
      constructor_image(state, batch, config);
      require(capture.batch_bytes == input.updates.size() * 16 && capture.calls > 0,
              "constructor image capture missing or batch size changed");
      bytes = capture.initial_bytes();
      graph_bytes = capture.graph_bytes; directory_bytes = capture.directory_bytes;
      metadata_bytes = capture.metadata_bytes; calls = capture.calls;
    } else {
      auto reservations = input.updates;
      for (std::size_t p = 0; p * 65536 < input.after.compact.vertices; ++p) {
        const auto owns_zero = [p](const auto& e) { return e.source == 0 && e.destination / 65536 == p; };
        if (std::none_of(input.before.begin(), input.before.end(), owns_zero) &&
            std::none_of(input.updates.begin(), input.updates.end(), owns_zero))
          reservations.push_back({0, static_cast<std::uint32_t>(p * 65536), 1, false});
      }
      const auto layout = GraSuPartitionedPmaLayout::build(input.after.compact.vertices, 65536,
          input.before, reservations, GraSuPmaWordAbi::kWeightedFullWord);
      for (const auto& part : layout.partitions)
        bytes += part.row_slot_bounds.size() * 8 + part.binary_heads.size() * 8 + part.segments.size() * 64;
      const auto prepared = warm_host::prepare_grasu(input.after.compact.vertices, input.updates);
      require(!prepared.shards.empty() && !prepared.source_seeds.empty(),
              "GraSU batch packing produced no shards or source seeds");
    }
    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now() - begin).count();
    std::cout << "HOST_RESULT {\"arm\":\"" << arm << "\",\"repeat\":" << repeat
        << ",\"nanoseconds\":" << ns << ",\"initial_h2d_bytes\":" << bytes
        << ",\"bootstrap_complete\":true,\"batch_preparation_complete\":true,\"graph_bytes\":" << graph_bytes
        << ",\"directory_bytes\":" << directory_bytes << ",\"metadata_bytes\":" << metadata_bytes
        << ",\"constructor_payload_calls\":" << calls
        << ",\"update_h2d_bytes\":" << input.updates.size() * 16 << "}" << std::endl;
  }
}
} // namespace figure_refresh
