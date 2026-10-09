#pragma once

#include <array>
#include <iostream>

#include "spine_sim/original_regraph/pr_apply.hpp"
#include "spine_sim/original_regraph/property_writer.hpp"
#include "spine_sim/original_regraph/write_indexer.hpp"
#include "memory_fixture.hpp"

namespace original_regraph_state_test {
namespace rg = spine::sim::original_regraph;
using original_regraph_memory_test::MemoryFixture;
using original_regraph_memory_test::MemoryLink;

inline void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

inline constexpr std::array<std::uint32_t, 3> kArguments{0, 3, 17};
inline constexpr std::array<std::uint32_t, 8> kDegrees{0, 1, 2, 3, 7, 31, 65536, 65537};
inline constexpr std::uint64_t kNewPropertyAddress = 1u << 20;

inline void emit_configuration() {
  std::cout << "STATE_CONFIG {\"clock_mhz\":210,\"axi_data_bytes\":64,\"outstanding\":16,"
               "\"memory_latency\":64,\"write_index_latency\":2,\"apply_post_read_latency\":26,"
               "\"apply_line_credits\":100,\"writer_line_credits\":72,"
               "\"degree_channel\":30,\"source_writer_share_odd_channels\":true}\n";
}

inline void append_word(std::vector<std::uint8_t>& bytes, std::uint32_t value) {
  for (unsigned byte = 0; byte < 4; ++byte) bytes.push_back((value >> (byte * 8)) & 255u);
}

inline std::uint32_t fixture_sum(unsigned case_index, unsigned vertex) {
  return (vertex * 37 + case_index * 101) % 4096;
}

inline std::uint32_t oracle(std::uint32_t sum, std::uint32_t degree, std::uint32_t argument) {
  const std::uint64_t score = argument + (static_cast<std::uint64_t>(sum) * 108 / 128);
  const std::uint64_t inverse = degree == 0 ? 0 : 65536 / degree;
  return static_cast<std::uint32_t>((score * inverse) / 65536);
}

struct Options {
  unsigned replicas{4};
  std::size_t fifo_depth{8};
  std::uint64_t memory_latency{64};
  std::size_t outstanding{16};
  std::size_t apply_credits{rg::kApplyLineCredits};
  std::size_t writer_credits{rg::kWriterLineCredits};
  bool reverse_registration{};
};

class StatePath {
 public:
  StatePath(MemoryFixture& memory, spine::sim::Fifo<rg::PropertyLine>& input,
             std::uint32_t lines, Options options = {})
      : memory(memory), lines(lines), options(options) {
    indexed = memory.queue<rg::PropertyWrite>("state.indexed");
    applied = memory.queue<rg::PropertyWrite>("state.applied");
    degree = memory.port("degree_axi", 100, 30, options.outstanding);
    std::vector<rg::WriteTarget> targets;
    for (unsigned index = 0; index < options.replicas; ++index) {
      auto port = memory.port("writer_axi" + std::to_string(index), 200 + index,
                              index * 2 + 1, options.outstanding);
      targets.push_back({{*port.requests, *port.responses}, kNewPropertyAddress, lines * 64ull});
      writers.push_back(port);
    }
    indexer = memory.make<rg::LittleWriteIndexer>("write_index", memory.clock, input, *indexed);
    apply = memory.make<rg::PrApply>("apply", memory.clock,
        rg::TransactionPort{*degree.requests, *degree.responses}, *indexed, *applied,
        0, lines * 64ull, rg::kApplyPostReadTiming, options.apply_credits);
    writer = memory.make<rg::PropertyBroadcastWriter>("property_writer", memory.clock,
        *applied, targets, options.writer_credits);
  }

  void begin(std::uint32_t argument, std::uint64_t property_address = kNewPropertyAddress,
             const std::vector<std::uint32_t>& actual_degrees = {}) {
    require(actual_degrees.empty() || actual_degrees.size() == lines * 16, "degree oracle extent mismatch");
    new_property_address = property_address;
    std::vector<std::uint8_t> degrees;
    for (std::uint32_t vertex = 0; vertex < lines * 16; ++vertex) {
      append_word(degrees, actual_degrees.empty() ? kDegrees[vertex % kDegrees.size()] : actual_degrees[vertex]);
    }
    memory.backend->initialize_payload(30, 0, degrees);
    for (unsigned index = 0; index < options.replicas; ++index) {
      memory.backend->fill_payload(index * 2 + 1, property_address, lines * 64ull + 64, 0xa5);
    }
    indexer->begin(lines);
    apply->begin(lines, argument);
    writer->begin(lines, property_address);
  }

  bool finished() const { return indexer->finished() && apply->finished() && writer->finished(); }

  std::vector<std::uint32_t> inspect_and_check(const std::vector<std::uint32_t>& expected) const {
    require(expected.size() == lines * 16, "state oracle extent mismatch");
    std::vector<std::uint32_t> result;
    for (unsigned index = 0; index < options.replicas; ++index) {
      const auto payload = memory.backend->inspect_payload(index * 2 + 1, new_property_address,
                                                            lines * 64ull + 64);
      for (std::size_t vertex = 0; vertex < expected.size(); ++vertex) {
        std::uint32_t value = 0;
        for (unsigned byte = 0; byte < 4; ++byte) value |= std::uint32_t{payload[vertex * 4 + byte]} << (byte * 8);
        require(value == expected[vertex], "state replica differs from independent PR oracle");
        if (index == 0) result.push_back(value);
      }
      require(std::all_of(payload.end() - 64, payload.end(), [](auto byte) { return byte == 0xa5; }),
              "property writer changed allocation guard");
    }
    return result;
  }

  MemoryFixture& memory;
  std::uint32_t lines;
  Options options;
  std::uint64_t new_property_address{kNewPropertyAddress};
  spine::sim::Fifo<rg::PropertyWrite>* indexed{};
  spine::sim::Fifo<rg::PropertyWrite>* applied{};
  MemoryLink degree;
  std::vector<MemoryLink> writers;
  rg::LittleWriteIndexer* indexer{};
  rg::PrApply* apply{};
  rg::PropertyBroadcastWriter* writer{};
};

}  // namespace original_regraph_state_test
