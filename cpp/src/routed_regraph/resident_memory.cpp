#include "../detail/routed_regraph_system.hpp"

#include <set>

namespace spine::sim {
namespace {
void append(std::vector<std::uint8_t> &data, std::uint64_t value, std::size_t bytes) {
  for (std::size_t byte = 0; byte < bytes; ++byte) data.push_back(value >> (byte * 8));
}
}

void RoutedReGraphSystem::Impl::initialize_memory() {
  for (std::size_t p = 0; p < layout.partitions.size(); ++p) {
    const auto &part = layout.partitions[p];
    const auto row = find_grasu_regraph_runtime_region(plan, p, "row");
    ReGraphPmaPartition partition{.vertices = layout.vertices, .slots = part.segments.size() * 16,
        .cache_segments_per_half = config.compute.cache_segments_per_half,
        .destination_base = part.destination_base, .destination_vertices = part.destination_vertices,
        .row_base = row.channel_offset_bytes, .row_channel = row.channel};
    for (std::size_t bank = 0; bank < 4; ++bank) {
      const auto region = find_grasu_regraph_runtime_region(plan, p, "pma" + std::to_string(bank));
      partition.pma_base[bank] = region.channel_offset_bytes;
      partition.pma_channel[bank] = region.channel;
      backend.fill_payload(region.channel, region.channel_offset_bytes, region.allocated_bytes, 0xff);
    }
    backend.fill_payload(row.channel, row.channel_offset_bytes, row.allocated_bytes, 0);
    std::vector<std::uint8_t> rows;
    rows.reserve((layout.vertices + 1) * 8);
    for (const auto &[begin, end] : part.row_slot_bounds)
      append(rows, (static_cast<std::uint64_t>(begin) << 32) | end, 8);
    append(rows, (static_cast<std::uint64_t>(partition.slots) << 32) | partition.slots, 8);
    backend.initialize_payload(row.channel, partition.row_base, rows);
    for (std::size_t segment = 0; segment < part.segments.size(); ++segment) {
      const auto local = segment >> 1;
      const auto bank = (segment & 1U) * 2 + (local < partition.cache_segments_per_half ? 0 : 1);
      std::vector<std::uint8_t> data;
      data.reserve(64);
      for (auto word : part.segments[segment]) append(data, word, 4);
      backend.initialize_payload(partition.pma_channel[bank], partition.pma_base[bank] + local * 64, data);
    }
    partitions.push_back(partition);
  }
  const auto &c = config.compute;
  const std::set<std::uint32_t> active(initial.active_vertices.begin(), initial.active_vertices.end());
  std::vector<std::uint8_t> state, source;
  state.reserve(padded_vertices * 4);
  source.reserve(padded_vertices * 4);
  for (std::size_t vertex = 0; vertex < padded_vertices; ++vertex) {
    const auto word = vertex < layout.vertices ? detail::encode_distance(initial.primary[vertex], false) : 0;
    append(state, word, 4);
    append(source, word | (active.contains(vertex) ? detail::kReGraphActive : 0U), 4);
  }
  backend.initialize_payload(30, c.vertex_state_base, state);
  for (auto channel : {23U, 24U}) {
    backend.initialize_payload(channel, c.source_state_base, source);
    backend.fill_payload(channel, c.source_state_base + c.source_state_buffer_stride, padded_vertices * 4, 0);
  }
  backend.fill_payload(30, config.status_address, 4, 0);
}

std::vector<std::uint32_t> RoutedReGraphSystem::Impl::read_words(std::size_t channel,
                                                              std::uint64_t address) const {
  const auto bytes = backend.inspect_payload(channel, address, padded_vertices * 4);
  std::vector<std::uint32_t> words;
  words.reserve(padded_vertices);
  for (std::size_t vertex = 0; vertex < padded_vertices; ++vertex)
    words.push_back(detail::decode_u32(bytes, vertex * 4));
  return words;
}

} // namespace spine::sim
