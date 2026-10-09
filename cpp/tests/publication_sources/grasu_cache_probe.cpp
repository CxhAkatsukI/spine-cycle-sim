#include "kernel_process_cache.cpp"
#include "probe_support.hpp"

#include <algorithm>
#include <array>
#include <map>

namespace {
constexpr std::uint32_t empty_slot = 0x80000000u;
using Segment = std::array<std::uint32_t, 16>;

pipe_type_96 update(unsigned segment, unsigned edge, bool deletion) {
  pipe_type_96 packet{};
  packet.data.range(31, 0) = segment << 5;
  packet.data.range(63, 32) = edge;
  packet.data[95] = deletion;
  return packet;
}

void oracle_update(Segment &segment, unsigned edge, bool deletion) {
  std::vector<std::uint32_t> edges;
  for (auto value : segment) {
    if (value != empty_slot) {
      edges.push_back(value);
    }
  }
  auto position = std::lower_bound(edges.begin(), edges.end(), edge);
  if (deletion) {
    require(position != edges.end() && *position == edge,
            "invalid oracle delete");
    edges.erase(position);
  } else {
    require(position == edges.end() || *position != edge,
            "duplicate oracle insert");
    require(edges.size() < 16, "oracle segment full");
    edges.insert(position, edge);
  }
  segment.fill(empty_slot);
  std::copy(edges.begin(), edges.end(), segment.begin());
}
} // namespace

int main() {
  try {
    std::vector<ap_uint<512>> pma(MAX_CACHE_SEGMENT);
    ap_uint<512> empty = 0;
    for (unsigned slot = 0; slot < 16; ++slot) {
      empty.range(32 * slot + 31, 32 * slot) = empty_slot;
    }
    std::fill(pma.begin(), pma.end(), empty);
    std::map<unsigned, Segment> expected;
    for (unsigned bank = 0; bank < UPDATE_STREAM_CACHE_COUNT; ++bank) {
      for (unsigned row : {0u, (MAX_CACHE_SEGMENT >> 4) - 1u}) {
        const unsigned segment = row * 16 + bank;
        auto &values = expected[segment];
        values.fill(empty_slot);
        values[0] = 10;
        values[1] = 40;
        values[2] = 70;
        for (unsigned slot = 0; slot < 16; ++slot) {
          pma[segment].range(32 * slot + 31, 32 * slot) = values[slot];
        }
      }
    }

    unsigned updates = 0;
    for (unsigned batch = 0; batch < 3; ++batch) {
      hls::stream<pipe_type_96> stream;
      for (auto &[segment, values] : expected) {
        auto submit = [&](unsigned edge, bool deletion) {
          stream.write(update(segment, edge, deletion));
          oracle_update(values, edge, deletion);
          ++updates;
        };
        if (batch == 0) {
          submit(20, false);
          submit(60, false);
          submit(40, true);
        } else if (batch == 1) {
          submit(20, true);
          submit(50, false);
        } else {
          submit(60, true);
          submit(60, false);
        }
      }
      pipe_type_96 end{};
      end.data = END_EDGE;
      stream.write(end);
      process_cache(pma.data(), stream);
      require(stream.empty(), "GraSU input not fully consumed");
      for (unsigned segment = 0; segment < pma.size(); ++segment) {
        const auto found = expected.find(segment);
        for (unsigned slot = 0; slot < 16; ++slot) {
          const auto value =
              found == expected.end() ? empty_slot : found->second[slot];
          require(
              pma[segment].range(32 * slot + 31, 32 * slot).to_uint() == value,
              "GraSU preload/update/writeback differs from sorted-set oracle");
        }
      }
    }
    std::cout << "PUBLICATION_PROBE {\"kind\":\"grasu_cache\",\"passed\":true,"
                 "\"batches\":3,\"banks\":16,\"segments_per_batch\":131072,"
                 "\"checked_words\":6291456,\"successful_updates\":"
              << updates << "}\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
