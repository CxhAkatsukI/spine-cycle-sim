#include "spine_sim/spine_l0.hpp"

#include <algorithm>
#include <array>
#include <fstream>
#include <limits>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <utility>

namespace spine::sim {

namespace {

constexpr std::uint64_t kMetadataWordBytes = 8;
constexpr std::uint64_t kPersistentRecordBytes = 16;
constexpr std::uint64_t kResultWords = 96;
constexpr std::uint64_t kMetadataMagic = 0x53504352ULL;
constexpr std::uint64_t kMetadataVersion = 2;
constexpr std::uint64_t kMetadataRequiredFeatures = 3;

struct GraphPayloadWrite {
  std::uint64_t address{};
  std::vector<std::uint8_t> data;
};

std::string trim(std::string text) {
  const auto first = text.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) {
    return {};
  }
  const auto last = text.find_last_not_of(" \t\r\n");
  return text.substr(first, last - first + 1);
}

std::uint64_t parse_unsigned(const std::string &text, const char *field) {
  std::size_t consumed = 0;
  const std::uint64_t value = std::stoull(text, &consumed, 0);
  if (consumed != text.size()) {
    throw std::invalid_argument(std::string("invalid ") + field + ": " + text);
  }
  return value;
}

std::vector<SpineEdgeRecord> coalesce_records(
    std::vector<SpineEdgeRecord> records) {
  std::stable_sort(
      records.begin(), records.end(),
      [](const SpineEdgeRecord &left, const SpineEdgeRecord &right) {
        return std::pair(left.src, left.dst) < std::pair(right.src, right.dst);
      });
  std::vector<SpineEdgeRecord> output;
  std::size_t index = 0;
  while (index < records.size()) {
    const std::uint32_t src = records[index].src;
    const std::uint32_t dst = records[index].dst;
    std::uint16_t weight = records[index].weight;
    std::int64_t diff = 0;
    while (index < records.size() && records[index].src == src &&
           records[index].dst == dst) {
      weight = std::min(weight, records[index].weight);
      diff += records[index].diff;
      ++index;
    }
    if (diff == 0) {
      continue;
    }
    if (diff < std::numeric_limits<std::int16_t>::min() ||
        diff > std::numeric_limits<std::int16_t>::max()) {
      throw std::overflow_error("coalesced Spine differential exceeds int16");
    }
    output.push_back(SpineEdgeRecord{
        .src = src,
        .dst = dst,
        .weight = weight,
        .diff = static_cast<std::int16_t>(diff),
    });
  }
  return output;
}

void append_u64_le(std::vector<std::uint8_t> &data, std::uint64_t value) {
  for (std::size_t byte = 0; byte < sizeof(std::uint64_t); ++byte) {
    data.push_back(static_cast<std::uint8_t>((value >> (byte * 8)) & 0xffU));
  }
}

std::vector<std::uint8_t> encode_u64_words(
    std::initializer_list<std::uint64_t> values) {
  std::vector<std::uint8_t> data;
  data.reserve(values.size() * sizeof(std::uint64_t));
  for (const std::uint64_t value : values) {
    append_u64_le(data, value);
  }
  return data;
}

std::uint64_t row_count_for_edges(const std::vector<SpineEdgeRecord> &edges) {
  std::uint64_t rows = 0;
  std::uint32_t previous = 0;
  bool have_previous = false;
  for (const SpineEdgeRecord &edge : edges) {
    if (!have_previous || edge.src != previous) {
      ++rows;
      previous = edge.src;
      have_previous = true;
    }
  }
  return rows;
}

std::uint64_t pack_u32_lane(std::uint32_t value, bool high_lane) {
  return high_lane ? (static_cast<std::uint64_t>(value) << 32) : value;
}

std::vector<std::uint8_t> encode_u32_lanes(
    const std::vector<std::uint32_t> &values, std::uint64_t word_count) {
  std::vector<std::uint8_t> data;
  data.reserve(word_count * kSpineGraphWordBytes);
  for (std::uint64_t word = 0; word < word_count; ++word) {
    std::uint64_t packed = 0;
    const std::size_t low = static_cast<std::size_t>(word * 2);
    if (low < values.size()) {
      packed |= values[low];
    }
    if (low + 1 < values.size()) {
      packed |= static_cast<std::uint64_t>(values[low + 1]) << 32;
    }
    append_u64_le(data, packed);
  }
  return data;
}

std::vector<GraphPayloadWrite> build_level_index_payloads(
    const SpineL0Config &config, const SpineLevelLayout &layout,
    const std::vector<SpineEdgeRecord> &edges, std::uint64_t rows) {
  const std::uint64_t page_count =
      (config.max_vertices + config.page_vertices - 1) / config.page_vertices;
  std::vector<std::uint32_t> row_sources;
  std::vector<std::uint32_t> row_offsets;
  std::vector<std::uint16_t> row_partition_masks;
  row_offsets.push_back(0);
  for (std::size_t index = 0; index < edges.size(); ++index) {
    const SpineEdgeRecord &edge = edges[index];
    if (row_sources.empty() || row_sources.back() != edge.src) {
      if (!row_sources.empty()) {
        row_offsets.push_back(static_cast<std::uint32_t>(index));
      }
      row_sources.push_back(edge.src);
      row_partition_masks.push_back(0);
    }
    const std::size_t partition = std::min<std::size_t>(
        edge.dst / config.vertex_partition_size, config.partitions - 1);
    row_partition_masks.back() |= static_cast<std::uint16_t>(1U << partition);
  }
  row_offsets.push_back(static_cast<std::uint32_t>(edges.size()));
  if (row_sources.size() != rows) {
    throw std::logic_error("Spine level row payload shape mismatch");
  }

  std::map<std::uint32_t, std::array<std::uint64_t, 4>> page_bitmaps;
  std::map<std::uint32_t, std::uint32_t> page_first_row;
  for (std::size_t row = 0; row < row_sources.size(); ++row) {
    const std::uint32_t source = row_sources[row];
    const std::uint32_t page = source / config.page_vertices;
    const std::uint32_t in_page = source % config.page_vertices;
    const std::uint32_t lane_word = in_page / 64;
    const std::uint32_t lane_bit = in_page % 64;
    page_bitmaps[page][lane_word] |= std::uint64_t{1} << lane_bit;
    page_first_row.emplace(page, static_cast<std::uint32_t>(row));
  }

  std::vector<GraphPayloadWrite> writes;
  for (const auto &[page, bitmap] : page_bitmaps) {
    std::vector<std::uint8_t> data;
    data.reserve(4 * kSpineGraphWordBytes);
    for (std::uint64_t word : bitmap) {
      append_u64_le(data, word);
    }
    writes.push_back(GraphPayloadWrite{
        .address =
            (layout.bitmap_offset_words + page * 4) * kSpineGraphWordBytes,
        .data = std::move(data),
    });
  }

  std::map<std::uint64_t, std::uint64_t> page_base_words;
  for (const auto &[page, row] : page_first_row) {
    page_base_words[page >> 1] |= pack_u32_lane(row, (page & 1U) != 0);
  }
  page_base_words[page_count >> 1] |=
      pack_u32_lane(static_cast<std::uint32_t>(rows), (page_count & 1U) != 0);
  for (const auto &[word, value] : page_base_words) {
    std::vector<std::uint8_t> data;
    data.reserve(kSpineGraphWordBytes);
    append_u64_le(data, value);
    writes.push_back(GraphPayloadWrite{
        .address =
            (layout.page_base_offset_words + word) * kSpineGraphWordBytes,
        .data = std::move(data),
    });
  }

  const std::uint64_t row_words = (rows + 2) >> 1;
  writes.push_back(GraphPayloadWrite{
      .address = layout.row_offset_offset_words * kSpineGraphWordBytes,
      .data = encode_u32_lanes(row_offsets, row_words),
  });

  const std::uint64_t mask_words = (rows + 3) >> 2;
  if (mask_words != 0) {
    std::vector<std::uint8_t> data(mask_words * kSpineGraphWordBytes, 0);
    for (std::size_t row = 0; row < row_partition_masks.size(); ++row) {
      const std::uint16_t partition_mask = row_partition_masks[row];
      const std::size_t word = row >> 2;
      const std::size_t lane = row & 3U;
      data[word * kSpineGraphWordBytes + lane * 2] =
          static_cast<std::uint8_t>(partition_mask & 0xffU);
      data[word * kSpineGraphWordBytes + lane * 2 + 1] =
          static_cast<std::uint8_t>((partition_mask >> 8) & 0xffU);
    }
    writes.push_back(GraphPayloadWrite{
        .address = layout.mask_offset_words * kSpineGraphWordBytes,
        .data = std::move(data),
    });
  }
  return writes;
}

}  // namespace

SpineMetadataLayout spine_metadata_layout(const SpineL0Config &config) {
  if (config.partitions != 16 || config.levels != kSpineLevelCount ||
      config.page_vertices != 256 || config.max_vertices == 0) {
    throw std::invalid_argument("unsupported Spine metadata architecture");
  }
  SpineMetadataLayout layout;
  layout.page_count = (static_cast<std::uint64_t>(config.max_vertices) +
                       config.page_vertices - 1) /
                      config.page_vertices;
  layout.slice_count = kSpineFamilyCount * kSpineLevelCount;
  layout.slice_words = layout.slice_count * 8;
  layout.active_bin_offset_base = layout.slice_words;
  layout.active_bin_count_base =
      layout.active_bin_offset_base + config.partitions;
  const std::uint64_t metadata_base_words =
      layout.active_bin_count_base + config.partitions;
  const std::uint64_t touched_slot_words = 5 + layout.page_count;
  const std::uint64_t touched_slot_base =
      metadata_base_words + 2 * config.partitions;
  const std::uint64_t touched_words =
      touched_slot_base +
      2 * static_cast<std::uint64_t>(config.partitions) * touched_slot_words;
  layout.slice_epoch_base = touched_words;
  const std::uint64_t slice_epoch_words = (layout.slice_count + 1) / 2;
  layout.page_epoch_base = layout.slice_epoch_base + slice_epoch_words;
  const std::uint64_t page_epoch_u32 = layout.slice_count * layout.page_count;
  const std::uint64_t page_epoch_words = (page_epoch_u32 + 1) / 2;
  const std::uint64_t hot_bitmap_base =
      layout.page_epoch_base + page_epoch_words;
  const std::uint64_t hot_bitmap_words =
      (static_cast<std::uint64_t>(config.max_vertices) + 63) / 64;
  const std::uint64_t hot_shard_edge_count_base =
      hot_bitmap_base + hot_bitmap_words;
  const std::uint64_t cold_partition_edge_count_base =
      hot_shard_edge_count_base + config.partitions;
  layout.hot_enabled_word = cold_partition_edge_count_base + config.partitions;
  layout.page_list_count_base = layout.hot_enabled_word + 1;
  const std::uint64_t page_list_count_words = (layout.slice_count + 1) / 2;
  layout.page_list_base = layout.page_list_count_base + page_list_count_words;
  layout.page_list_words_per_slice = (layout.page_count + 3) / 4;
  layout.dirty_base = layout.page_list_base +
                      layout.slice_count * layout.page_list_words_per_slice;
  layout.dirty_count_word = layout.dirty_base;
  layout.dirty_generation_word = layout.dirty_base + 1;
  layout.dirty_hash_sum_word = layout.dirty_base + 2;
  layout.dirty_hash_xor_word = layout.dirty_base + 3;
  layout.dirty_candidate_generation_word = layout.dirty_base + 4;
  layout.dirty_candidate_count_word = layout.dirty_base + 5;
  layout.dirty_candidate_hash_sum_word = layout.dirty_base + 6;
  layout.dirty_candidate_hash_xor_word = layout.dirty_base + 7;
  layout.dirty_candidate_valid_word = layout.dirty_base + 8;
  layout.dirty_host_generation_word = layout.dirty_base + 9;
  layout.dirty_host_count_word = layout.dirty_base + 10;
  layout.dirty_host_hash_sum_word = layout.dirty_base + 11;
  layout.dirty_host_hash_xor_word = layout.dirty_base + 12;
  layout.dirty_host_valid_word = layout.dirty_base + 13;
  layout.dirty_last_mode_word = layout.dirty_base + 14;
  layout.dirty_last_status_word = layout.dirty_base + 15;
  layout.total_words = layout.dirty_base + 16;
  return layout;
}

std::uint64_t spine_metadata_control_word(bool hot_enabled) {
  return (kMetadataMagic << 32) | (kMetadataVersion << 16) |
         (kMetadataRequiredFeatures << 1) | (hot_enabled ? 1ULL : 0ULL);
}

bool spine_metadata_control_valid(std::uint64_t control) noexcept {
  const std::uint64_t magic = control >> 32;
  const std::uint64_t version = (control >> 16) & 0xffffULL;
  const std::uint64_t features = (control >> 1) & 0x7fffULL;
  return magic == kMetadataMagic && version == kMetadataVersion &&
         features == kMetadataRequiredFeatures;
}

std::uint64_t spine_dirty_hash_sum_term(std::uint32_t source) noexcept {
  std::uint64_t value =
      static_cast<std::uint64_t>(source) + 0x9e3779b97f4a7c15ULL;
  value ^= value << 13;
  value ^= value >> 7;
  value ^= value << 17;
  return value;
}

std::uint64_t spine_dirty_hash_xor_term(std::uint32_t source) noexcept {
  std::uint64_t value =
      static_cast<std::uint64_t>(source) + 0xd1b54a32d192ed03ULL;
  value ^= value >> 11;
  value ^= value << 29;
  value ^= value >> 19;
  return (value << 23) | (value >> 41);
}

SpineDirtyIdentity spine_dirty_identity(
    std::uint32_t generation, std::span<const std::uint32_t> sources) {
  std::vector<std::uint32_t> unique(sources.begin(), sources.end());
  std::sort(unique.begin(), unique.end());
  unique.erase(std::unique(unique.begin(), unique.end()), unique.end());
  SpineDirtyIdentity identity{
      .generation = generation,
      .count = unique.size(),
  };
  for (const std::uint32_t source : unique) {
    identity.hash_sum += spine_dirty_hash_sum_term(source);
    identity.hash_xor ^= spine_dirty_hash_xor_term(source);
  }
  return identity;
}

std::vector<std::uint8_t> encode_spine_active_record(
    const SpineActiveRecord &record) {
  std::vector<std::uint8_t> data(kSpineActiveRecordBytes, 0);
  const auto put_u32 = [&data](std::size_t offset, std::uint32_t value) {
    for (std::size_t byte = 0; byte < sizeof(value); ++byte) {
      data[offset + byte] =
          static_cast<std::uint8_t>((value >> (byte * 8)) & 0xffU);
    }
  };
  const auto put_u16 = [&data](std::size_t offset, std::uint16_t value) {
    data[offset] = static_cast<std::uint8_t>(value & 0xffU);
    data[offset + 1] = static_cast<std::uint8_t>(value >> 8);
  };
  put_u32(0, record.source);
  put_u32(4, record.source_value);
  for (std::size_t level = 0; level < record.level_masks.size(); ++level) {
    put_u16(8 + 2 * level, record.level_masks[level]);
  }
  put_u16(30, record.hot_shard_mask);
  return data;
}

SpineActiveRecord decode_spine_active_record(
    std::span<const std::uint8_t> data) {
  if (data.size() != kSpineActiveRecordBytes) {
    throw std::invalid_argument("Spine active record must be 256 bits");
  }
  const auto get_u32 = [data](std::size_t offset) {
    std::uint32_t value = 0;
    for (std::size_t byte = 0; byte < sizeof(value); ++byte) {
      value |= static_cast<std::uint32_t>(data[offset + byte]) << (byte * 8);
    }
    return value;
  };
  const auto get_u16 = [data](std::size_t offset) {
    return static_cast<std::uint16_t>(data[offset]) |
           static_cast<std::uint16_t>(data[offset + 1] << 8);
  };
  SpineActiveRecord record;
  record.source = get_u32(0);
  record.source_value = get_u32(4);
  for (std::size_t level = 0; level < record.level_masks.size(); ++level) {
    record.level_masks[level] = get_u16(8 + 2 * level);
  }
  record.hot_shard_mask = get_u16(30);
  return record;
}

std::vector<std::uint8_t> encode_spine_sort_edge(const SpineEdgeRecord &edge) {
  std::vector<std::uint8_t> data(kSpineSortWordBytes, 0);
  const std::uint16_t diff = static_cast<std::uint16_t>(edge.diff);
  data[0] = static_cast<std::uint8_t>(diff & 0xffU);
  data[1] = static_cast<std::uint8_t>((diff >> 8) & 0xffU);
  data[4] = static_cast<std::uint8_t>(edge.weight & 0xffU);
  data[5] = static_cast<std::uint8_t>((edge.weight >> 8) & 0xffU);
  for (std::size_t byte = 0; byte < sizeof(std::uint32_t); ++byte) {
    data[8 + byte] =
        static_cast<std::uint8_t>((edge.dst >> (byte * 8)) & 0xffU);
    data[12 + byte] =
        static_cast<std::uint8_t>((edge.src >> (byte * 8)) & 0xffU);
  }
  return data;
}

SpineEdgeRecord decode_spine_sort_edge(const std::vector<std::uint8_t> &data) {
  if (data.size() != kSpineSortWordBytes) {
    throw std::invalid_argument("Spine sorted edge payload must be 128 bits");
  }
  std::uint32_t dst = 0;
  std::uint32_t src = 0;
  for (std::size_t byte = 0; byte < sizeof(std::uint32_t); ++byte) {
    dst |= static_cast<std::uint32_t>(data[8 + byte]) << (byte * 8);
    src |= static_cast<std::uint32_t>(data[12 + byte]) << (byte * 8);
  }
  const std::uint16_t weight = static_cast<std::uint16_t>(data[4]) |
                               (static_cast<std::uint16_t>(data[5]) << 8);
  const std::uint16_t diff = static_cast<std::uint16_t>(data[0]) |
                             (static_cast<std::uint16_t>(data[1]) << 8);
  return SpineEdgeRecord{
      .src = src,
      .dst = dst,
      .weight = weight,
      .diff = static_cast<std::int16_t>(diff),
  };
}

std::vector<std::uint8_t> encode_spine_sort_edges(
    const std::vector<SpineEdgeRecord> &edges) {
  std::vector<std::uint8_t> data(edges.size() * kSpineSortWordBytes);
  for (std::size_t index = 0; index < edges.size(); ++index) {
    const std::vector<std::uint8_t> edge = encode_spine_sort_edge(edges[index]);
    std::copy(edge.begin(), edge.end(),
              data.begin() +
                  static_cast<std::ptrdiff_t>(index * kSpineSortWordBytes));
  }
  return data;
}

std::vector<SpineEdgeRecord> decode_spine_sort_edges(
    const std::vector<std::uint8_t> &data) {
  if (data.size() % kSpineSortWordBytes != 0) {
    throw std::invalid_argument("Spine sorted edge payload is misaligned");
  }
  std::vector<SpineEdgeRecord> edges;
  edges.reserve(data.size() / kSpineSortWordBytes);
  for (std::size_t offset = 0; offset < data.size();
       offset += kSpineSortWordBytes) {
    edges.push_back(decode_spine_sort_edge(std::vector<std::uint8_t>(
        data.begin() + static_cast<std::ptrdiff_t>(offset),
        data.begin() +
            static_cast<std::ptrdiff_t>(offset + kSpineSortWordBytes))));
  }
  return edges;
}

std::vector<std::uint8_t> encode_spine_level_edge(const SpineEdgeRecord &edge) {
  const std::uint64_t packed = (static_cast<std::uint64_t>(edge.dst) << 32) |
                               (static_cast<std::uint64_t>(edge.weight) << 16) |
                               static_cast<std::uint16_t>(edge.diff);
  std::vector<std::uint8_t> data(kSpineGraphWordBytes);
  for (std::size_t byte = 0; byte < data.size(); ++byte) {
    data[byte] = static_cast<std::uint8_t>((packed >> (byte * 8)) & 0xffU);
  }
  return data;
}

SpineEdgeRecord decode_spine_level_edge(const std::vector<std::uint8_t> &data,
                                        std::uint32_t source) {
  if (data.size() != kSpineGraphWordBytes) {
    throw std::invalid_argument("Spine level edge payload must be 64 bits");
  }
  std::uint64_t packed = 0;
  for (std::size_t byte = 0; byte < data.size(); ++byte) {
    packed |= static_cast<std::uint64_t>(data[byte]) << (byte * 8);
  }
  return SpineEdgeRecord{
      .src = source,
      .dst = static_cast<std::uint32_t>(packed >> 32),
      .weight = static_cast<std::uint16_t>((packed >> 16) & 0xffffU),
      .diff = static_cast<std::int16_t>(packed & 0xffffU),
  };
}

std::uint32_t spine_hot_dst_hash(std::uint32_t dst) noexcept {
  std::uint32_t value = dst;
  value ^= value >> 16;
  value *= 0x7feb352dU;
  value ^= value >> 15;
  value *= 0x846ca68bU;
  value ^= value >> 16;
  return value;
}

std::size_t spine_hot_shard(std::uint32_t dst) noexcept {
  return spine_hot_dst_hash(dst) & 15U;
}

SpineLevelLayout spine_level_layout(const SpineL0Config &config, bool hot,
                                    std::size_t level) {
  if (config.partitions != 16 || config.levels != 11 ||
      config.page_vertices != 256 || config.max_vertices == 0 ||
      config.max_sort_edges == 0 || level >= config.levels) {
    throw std::invalid_argument("invalid Spine fixed-level layout request");
  }
  const std::uint64_t page_count =
      (config.max_vertices + config.page_vertices - 1) / config.page_vertices;
  const std::uint64_t bitmap_words = page_count * 4;
  const std::uint64_t page_base_words = (page_count + 2) >> 1;
  const auto capacity = [&](std::size_t index) {
    if (index == 0) {
      return static_cast<std::uint64_t>(config.max_sort_edges);
    }
    const std::uint64_t total =
        static_cast<std::uint64_t>(config.max_sort_edges) << index;
    return (total + config.partitions - 1) / config.partitions;
  };
  const auto level_words = [&](std::size_t index) {
    const std::uint64_t cap = capacity(index);
    return bitmap_words + page_base_words + ((cap + 2) >> 1) +
           ((cap + 3) >> 2) + cap;
  };

  std::uint64_t base = 0;
  if (hot) {
    for (std::size_t index = 0; index < config.levels; ++index) {
      base += level_words(index);
    }
  }
  for (std::size_t index = 0; index < level; ++index) {
    base += level_words(index);
  }

  SpineLevelLayout layout;
  layout.edge_capacity = capacity(level);
  layout.row_capacity_words = (layout.edge_capacity + 2) >> 1;
  layout.mask_capacity_words = (layout.edge_capacity + 3) >> 2;
  layout.bitmap_offset_words = base;
  layout.page_base_offset_words = base + bitmap_words;
  layout.row_offset_offset_words =
      layout.page_base_offset_words + page_base_words;
  layout.mask_offset_words =
      layout.row_offset_offset_words + layout.row_capacity_words;
  layout.edge_offset_words =
      layout.mask_offset_words + layout.mask_capacity_words;
  return layout;
}

SpineEdgeSlice load_spine_edge_slice(const std::filesystem::path &path) {
  std::ifstream input(path);
  if (!input) {
    throw std::runtime_error("cannot open Spine edge slice: " + path.string());
  }
  SpineEdgeSlice slice;
  std::uint32_t max_vertex = 0;
  std::string line;
  std::size_t line_number = 0;
  while (std::getline(input, line)) {
    ++line_number;
    line = trim(std::move(line));
    if (line.empty()) {
      continue;
    }
    if (line.front() == '#') {
      const std::string item = trim(line.substr(1));
      const auto separator = item.find('=');
      if (separator == std::string::npos) {
        continue;
      }
      const std::string key = trim(item.substr(0, separator));
      const std::string value = trim(item.substr(separator + 1));
      if (key == "vertices") {
        slice.vertices = static_cast<std::size_t>(
            parse_unsigned(value, "vertices metadata"));
      } else if (key == "case") {
        slice.case_name = value;
      }
      continue;
    }

    std::istringstream record(line);
    std::uint64_t src = 0;
    std::uint64_t dst = 0;
    std::uint64_t weight = 1;
    std::int64_t diff = 1;
    if (!(record >> src >> dst)) {
      throw std::runtime_error(path.string() + ":" +
                               std::to_string(line_number) +
                               ": expected src dst [weight [diff]]");
    }
    if (record >> weight) {
      static_cast<void>(record >> diff);
    }
    std::string extra;
    if (record >> extra || src > std::numeric_limits<std::uint32_t>::max() ||
        dst > std::numeric_limits<std::uint32_t>::max() ||
        weight > std::numeric_limits<std::uint16_t>::max() ||
        diff < std::numeric_limits<std::int16_t>::min() ||
        diff > std::numeric_limits<std::int16_t>::max() || diff == 0) {
      throw std::runtime_error(path.string() + ":" +
                               std::to_string(line_number) +
                               ": edge record is outside the HLS format");
    }
    slice.edges.push_back(SpineEdgeRecord{
        .src = static_cast<std::uint32_t>(src),
        .dst = static_cast<std::uint32_t>(dst),
        .weight = static_cast<std::uint16_t>(weight),
        .diff = static_cast<std::int16_t>(diff),
    });
    max_vertex =
        std::max(max_vertex, static_cast<std::uint32_t>(std::max(src, dst)));
  }
  if (slice.edges.empty()) {
    throw std::runtime_error("Spine edge slice has no edge records: " +
                             path.string());
  }
  if (slice.vertices == 0) {
    slice.vertices = static_cast<std::size_t>(max_vertex) + 1;
  }
  if (slice.vertices <= max_vertex) {
    throw std::runtime_error(
        "Spine edge slice vertex count does not cover IDs");
  }
  if (!std::is_sorted(
          slice.edges.begin(), slice.edges.end(),
          [](const SpineEdgeRecord &left, const SpineEdgeRecord &right) {
            return std::pair(left.src, left.dst) <
                   std::pair(right.src, right.dst);
          })) {
    throw std::runtime_error(
        "Spine maintenance input must be sorted by src,dst");
  }
  return slice;
}

SpineL0Maintenance::SpineL0Maintenance(std::string name, ClockId clock_id,
                                       SpineL0Config config,
                                       SpineEdgeSlice workload,
                                       SpineL0Ports ports, SpineL0State &state)
    : Component(std::move(name), clock_id),
      config_(config),
      workload_(std::move(workload)),
      ports_(ports),
      state_(state) {
  if (config_.partitions != ports_.graph.size() || config_.partitions != 16 ||
      config_.levels != 11 || config_.vertex_partition_size == 0 ||
      config_.page_vertices != 256 || config_.max_vertices == 0 ||
      config_.max_sort_edges == 0 || config_.device_dirty_source_limit == 0 ||
      config_.range_task_active_gate == 0 ||
      config_.range_task_capacity == 0 ||
      config_.range_task_capacity > 65'536 ||
      config_.range_task_payload_budget == 0 ||
      config_.fallback_replay_threshold == 0 ||
      config_.memory_request_window == 0 || workload_.vertices == 0 ||
      workload_.vertices > config_.max_vertices || workload_.edges.empty() ||
      workload_.edges.size() > config_.max_sort_edges ||
      ports_.sorted_edges == nullptr || ports_.metadata == nullptr ||
      ports_.result == nullptr) {
    throw std::invalid_argument("invalid Spine L0 maintenance configuration");
  }
  for (FixedAxiPort *port : ports_.graph) {
    if (port == nullptr) {
      throw std::invalid_argument("Spine graph AXI port is null");
    }
  }
  std::unordered_set<std::uint32_t> configured_hot;
  for (const std::uint32_t vertex : config_.hot_vertices) {
    if (vertex >= config_.max_vertices) {
      throw std::invalid_argument("Spine hot vertex exceeds MAX_N");
    }
    configured_hot.insert(vertex);
  }
  bool state_occupied = false;
  for (std::size_t family = 0; family < config_.partitions; ++family) {
    for (std::size_t level = 0; level < config_.levels; ++level) {
      state_occupied = state_occupied ||
                       !state_.cold_levels[family][level].empty() ||
                       !state_.hot_levels[family][level].empty();
    }
  }
  if (state_occupied && state_.hot_vertices != configured_hot) {
    throw std::invalid_argument(
        "Spine hot bitmap cannot change while levels are occupied");
  }
  state_.hot_vertices = std::move(configured_hot);
  state_.hot_enabled = !state_.hot_vertices.empty();
  sorted_scan_edges_ = workload_.edges;
  ports_.sorted_edges->initialize_payload(
      config_.sorted_edges_base, encode_spine_sort_edges(workload_.edges));
  const auto initialize_levels = [&](const auto &families, bool hot) {
    for (std::size_t family = 0; family < families.size(); ++family) {
      for (std::size_t level = 0; level < families[family].size(); ++level) {
        const auto &edges = families[family][level];
        if (edges.empty()) {
          continue;
        }
        const SpineLevelLayout layout = spine_level_layout(config_, hot, level);
        std::uint64_t rows = 0;
        std::uint32_t last_src = 0;
        bool have_src = false;
        for (const SpineEdgeRecord &edge : edges) {
          if (!have_src || edge.src != last_src) {
            ++rows;
            last_src = edge.src;
            have_src = true;
          }
        }
        for (const GraphPayloadWrite &write :
             build_level_index_payloads(config_, layout, edges, rows)) {
          ports_.graph[family]->initialize_payload(write.address, write.data);
        }
        ports_.graph[family]->initialize_payload(
            layout.edge_offset_words * kSpineGraphWordBytes, [&edges] {
              std::vector<std::uint8_t> payload;
              payload.reserve(edges.size() * kSpineGraphWordBytes);
              for (const SpineEdgeRecord &edge : edges) {
                const std::vector<std::uint8_t> packed =
                    encode_spine_level_edge(edge);
                payload.insert(payload.end(), packed.begin(), packed.end());
              }
              return payload;
            }());
      }
    }
  };
  initialize_levels(state_.cold_levels, false);
  if (state_.hot_enabled) {
    initialize_levels(state_.hot_levels, true);
  }
  initialize_metadata_payload();
}

void SpineL0Maintenance::initialize_metadata_payload() {
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  ports_.metadata->initialize_payload(
      config_.metadata_base + metadata.hot_enabled_word * kMetadataWordBytes,
      encode_u64_words({spine_metadata_control_word(state_.hot_enabled)}));

  const auto initialize_families = [&](const auto &families, bool hot) {
    for (std::size_t family = 0; family < families.size(); ++family) {
      const std::size_t logical_family =
          hot ? config_.partitions + family : family;
      for (std::size_t level = 0; level < families[family].size(); ++level) {
        const auto &edges = families[family][level];
        if (edges.empty()) {
          continue;
        }
        const std::uint64_t rows = row_count_for_edges(edges);
        const SpineLevelLayout layout = spine_level_layout(config_, hot, level);
        const std::uint64_t slice = logical_family * config_.levels + level;
        ports_.metadata->initialize_payload(
            config_.metadata_base + slice * 8 * kMetadataWordBytes,
            encode_u64_words(
                {edges.size(), rows, layout.bitmap_offset_words,
                 layout.page_base_offset_words, layout.row_offset_offset_words,
                 layout.mask_offset_words, layout.edge_offset_words, 1}));
        slice_epochs_[logical_family][level] = 1;
        std::set<std::uint32_t> pages;
        for (const SpineEdgeRecord &edge : edges) {
          pages.insert(edge.src / config_.page_vertices);
        }
        for (const std::uint32_t page : pages) {
          page_epochs_[slice * metadata.page_count + page] = 1;
        }
      }
    }
  };
  initialize_families(state_.cold_levels, false);
  initialize_families(state_.hot_levels, true);

  for (std::size_t word = 0; word < (metadata.slice_count + 1) / 2; ++word) {
    const std::uint64_t low_index = word * 2;
    const std::size_t low_family = low_index / config_.levels;
    const std::size_t low_level = low_index % config_.levels;
    std::uint64_t packed = slice_epochs_[low_family][low_level];
    if (low_index + 1 < metadata.slice_count) {
      const std::uint64_t high_index = low_index + 1;
      packed |=
          static_cast<std::uint64_t>(slice_epochs_[high_index / config_.levels]
                                                  [high_index % config_.levels])
          << 32;
    }
    if (packed != 0) {
      ports_.metadata->initialize_payload(
          config_.metadata_base +
              (metadata.slice_epoch_base + word) * kMetadataWordBytes,
          encode_u64_words({packed}));
    }
  }

  std::map<std::uint64_t, std::uint64_t> page_words;
  for (const auto &[index, epoch] : page_epochs_) {
    const std::uint64_t word = index >> 1;
    if ((index & 1U) == 0) {
      page_words[word] |= epoch;
    } else {
      page_words[word] |= static_cast<std::uint64_t>(epoch) << 32;
    }
  }
  for (const auto &[word, packed] : page_words) {
    ports_.metadata->initialize_payload(
        config_.metadata_base +
            (metadata.page_epoch_base + word) * kMetadataWordBytes,
        encode_u64_words({packed}));
  }
}

void SpineL0Maintenance::evaluate(const CycleContext &) {
  staged_action_ = StagedAction::kNone;
  staged_memory_issue_ = false;
  staged_memory_completion_ = false;
  if (done_ || failed_) {
    return;
  }
  staged_memory_completion_ = stage_memory_completion();
  if (!tasks_.empty()) {
    const MemoryTask &task = tasks_.front();
    if (inflight_tasks_.size() >= config_.memory_request_window) {
      ++counters_.memory_window_stall_cycles;
    } else if (memory_task_conflicts(task)) {
      ++counters_.memory_dependency_stall_cycles;
    } else if (task.port->requests().try_push(AxiRequest{
                   .transaction_id = next_transaction_id_,
                   .operation = task.operation,
                   .address = task.address,
                   .bytes = task.bytes,
                   .write_data = task.write_data,
               })) {
      staged_memory_issue_ = true;
    } else {
      ++counters_.memory_request_fifo_stall_cycles;
    }
  }
  if (!tasks_.empty() || !inflight_tasks_.empty() ||
      staged_memory_completion_) {
    return;
  }
  staged_action_ = StagedAction::kAdvance;
}

void SpineL0Maintenance::commit(const CycleContext &context) {
  if (staged_memory_completion_) {
    const auto found = inflight_tasks_.find(staged_response_.transaction_id);
    if (found == inflight_tasks_.end() || !staged_response_.success) {
      failed_ = true;
      done_ = true;
      failure_ = "Spine AXI response failed or used an unknown transaction ID";
      return;
    }
    consume_memory_response(found->second, staged_response_);
    inflight_tasks_.erase(found);
    ++counters_.memory_requests_completed;
  }
  if (staged_memory_issue_) {
    const std::uint64_t transaction_id = next_transaction_id_++;
    inflight_tasks_.emplace(transaction_id, std::move(tasks_.front()));
    tasks_.pop_front();
    ++counters_.memory_requests_issued;
    counters_.max_memory_requests_inflight =
        std::max(counters_.max_memory_requests_inflight,
                 inflight_tasks_.size());
  }
  switch (staged_action_) {
    case StagedAction::kNone:
      return;
    case StagedAction::kAdvance:
      advance(context);
      return;
  }
}

bool SpineL0Maintenance::memory_task_conflicts(
    const MemoryTask &task) const {
  const std::uint64_t task_end = task.address + task.bytes;
  for (const auto &[transaction_id, inflight] : inflight_tasks_) {
    (void)transaction_id;
    if (task.port != inflight.port ||
        (task.operation == MemoryOperation::kRead &&
         inflight.operation == MemoryOperation::kRead)) {
      continue;
    }
    const std::uint64_t inflight_end = inflight.address + inflight.bytes;
    if (task.address < inflight_end && inflight.address < task_end) {
      return true;
    }
  }
  return false;
}

bool SpineL0Maintenance::stage_memory_completion() {
  std::uint64_t selected = std::numeric_limits<std::uint64_t>::max();
  FixedAxiPort *selected_port = nullptr;
  for (const auto &[transaction_id, task] : inflight_tasks_) {
    const AxiResponse *response = task.port->responses().front();
    if (response != nullptr && response->transaction_id == transaction_id &&
        transaction_id < selected) {
      selected = transaction_id;
      selected_port = task.port;
    }
  }
  return selected_port != nullptr &&
         selected_port->responses().try_pop(staged_response_);
}

void SpineL0Maintenance::enqueue_task(
    FixedAxiPort &port, MemoryOperation operation, std::uint64_t address,
    std::uint64_t bytes, TaskClass task_class,
    std::vector<std::uint8_t> write_data,
    std::vector<std::uint32_t> carry_edge_sources) {
  if (bytes == 0) {
    return;
  }
  if ((operation == MemoryOperation::kRead && !write_data.empty()) ||
      (operation == MemoryOperation::kWrite && !write_data.empty() &&
       write_data.size() != bytes)) {
    throw std::invalid_argument("invalid Spine maintenance memory payload");
  }
  if ((!carry_edge_sources.empty() &&
       (operation != MemoryOperation::kRead ||
        task_class != TaskClass::kGraph ||
        carry_edge_sources.size() * kSpineGraphWordBytes != bytes)) ||
      (operation == MemoryOperation::kWrite && !carry_edge_sources.empty())) {
    throw std::invalid_argument("invalid Spine carry payload read task");
  }
  tasks_.push_back(MemoryTask{
      .port = &port,
      .operation = operation,
      .address = address,
      .bytes = bytes,
      .task_class = task_class,
      .write_data = std::move(write_data),
      .carry_edge_sources = std::move(carry_edge_sources),
  });
  ++counters_.memory_tasks;
  switch (task_class) {
    case TaskClass::kSorted:
      counters_.sorted_read_bytes += bytes;
      break;
    case TaskClass::kPersistent:
      if (operation == MemoryOperation::kRead) {
        counters_.persistent_read_bytes += bytes;
      } else {
        counters_.persistent_write_bytes += bytes;
      }
      break;
    case TaskClass::kMetadata:
      if (operation == MemoryOperation::kRead) {
        counters_.metadata_read_bytes += bytes;
      } else {
        counters_.metadata_write_bytes += bytes;
      }
      break;
    case TaskClass::kGraph:
      if (operation == MemoryOperation::kRead) {
        counters_.graph_read_bytes += bytes;
      } else {
        counters_.graph_write_bytes += bytes;
      }
      break;
    case TaskClass::kResult:
      counters_.result_write_bytes += bytes;
      break;
  }
}

void SpineL0Maintenance::begin_sorted_scan(Phase process_phase) {
  enqueue_task(
      *ports_.sorted_edges, MemoryOperation::kRead, config_.sorted_edges_base,
      workload_.edges.size() * kSpineSortWordBytes, TaskClass::kSorted);
  ++counters_.sorted_scan_passes;
  scan_index_ = 0;
  phase_ = process_phase;
}

void SpineL0Maintenance::process_scan_edge(Phase next_phase) {
  if (scan_index_ >= sorted_scan_edges_.size()) {
    phase_ = next_phase;
    return;
  }
  ++counters_.sorted_edge_visits;
  ++scan_index_;
  if (scan_index_ == sorted_scan_edges_.size()) {
    phase_ = next_phase;
  }
}

void SpineL0Maintenance::consume_memory_response(const MemoryTask &task,
                                                 const AxiResponse &response) {
  if (task.operation == MemoryOperation::kWrite) {
    if (!response.read_data.empty()) {
      throw std::logic_error(
          "Spine maintenance write response carried payload");
    }
    return;
  }
  if (response.read_data.size() != task.bytes) {
    throw std::logic_error("Spine maintenance read response payload mismatch");
  }
  if (task.task_class == TaskClass::kSorted) {
    sorted_scan_edges_ = decode_spine_sort_edges(response.read_data);
    counters_.sorted_payload_read_bytes += response.read_data.size();
  } else if (!task.carry_edge_sources.empty()) {
    for (std::size_t index = 0; index < task.carry_edge_sources.size();
         ++index) {
      const auto begin =
          response.read_data.begin() +
          static_cast<std::ptrdiff_t>(index * kSpineGraphWordBytes);
      const auto end = begin + kSpineGraphWordBytes;
      carry_payload_edges_.push_back(
          decode_spine_level_edge(std::vector<std::uint8_t>(begin, end),
                                  task.carry_edge_sources[index]));
    }
    counters_.carry_level_payload_read_bytes += response.read_data.size();
  }
}

std::size_t SpineL0Maintenance::family_for(std::uint32_t dst) const {
  return std::min<std::size_t>(dst / config_.vertex_partition_size,
                               config_.partitions - 1);
}

bool SpineL0Maintenance::edge_is_hot(std::uint32_t dst) const {
  return state_.hot_enabled && state_.hot_vertices.contains(dst);
}

std::vector<SpineEdgeRecord> SpineL0Maintenance::coalesce_family(
    bool hot, std::size_t family) const {
  std::vector<SpineEdgeRecord> selected;
  for (const SpineEdgeRecord &edge : sorted_scan_edges_) {
    const bool is_hot = edge_is_hot(edge.dst);
    const std::size_t owner =
        is_hot ? spine_hot_shard(edge.dst) : family_for(edge.dst);
    if (is_hot == hot && owner == family) {
      selected.push_back(edge);
    }
  }
  return coalesce_records(std::move(selected));
}

std::size_t SpineL0Maintenance::target_for(bool hot) const {
  const auto &levels = hot ? state_.hot_levels : state_.cold_levels;
  for (std::size_t level = 0; level < config_.levels; ++level) {
    bool occupied = false;
    for (std::size_t family = 0; family < config_.partitions; ++family) {
      occupied = occupied || !levels[family][level].empty();
    }
    if (!occupied) {
      return level;
    }
  }
  return config_.levels;
}

std::vector<SpineEdgeRecord> SpineL0Maintenance::merge_family(
    bool hot, std::size_t family, std::size_t target) const {
  std::vector<SpineEdgeRecord> inputs = coalesce_family(hot, family);
  const auto &levels = hot ? state_.hot_levels : state_.cold_levels;
  for (std::size_t level = 0; level < target; ++level) {
    inputs.insert(inputs.end(), levels[family][level].begin(),
                  levels[family][level].end());
  }
  return coalesce_records(std::move(inputs));
}

std::vector<SpineEdgeRecord>
SpineL0Maintenance::merge_family_with_carry_payload(bool hot,
                                                    std::size_t family) const {
  std::vector<SpineEdgeRecord> inputs = coalesce_family(hot, family);
  for (const SpineEdgeRecord &edge : carry_payload_edges_) {
    const bool is_hot = edge_is_hot(edge.dst);
    const std::size_t owner =
        is_hot ? spine_hot_shard(edge.dst) : family_for(edge.dst);
    if (is_hot == hot && owner == family) {
      inputs.push_back(edge);
    }
  }
  return coalesce_records(std::move(inputs));
}

void SpineL0Maintenance::build_family_outputs() {
  family_write_tasks_.clear();
  counters_.active_families = 0;
  const std::size_t cold_target =
      static_cast<std::size_t>(counters_.target_level);
  const std::size_t hot_target =
      counters_.hot_enabled
          ? static_cast<std::size_t>(counters_.hot_target_level)
          : 0;
  for (std::size_t family = 0; family < config_.partitions; ++family) {
    family_outputs_[family] = merge_family(false, family, cold_target);
    counters_.family_edges[family] = family_outputs_[family].size();
    std::uint64_t rows = 0;
    std::uint32_t last_src = 0;
    bool have_src = false;
    for (const SpineEdgeRecord &edge : family_outputs_[family]) {
      if (!have_src || edge.src != last_src) {
        ++rows;
        last_src = edge.src;
        have_src = true;
      }
    }
    counters_.family_rows[family] = rows;
    const auto &cold_levels = state_.cold_levels[family];
    std::size_t cold_inputs = coalesce_family(false, family).size();
    for (std::size_t level = 0; level < cold_target; ++level) {
      cold_inputs += cold_levels[level].size();
    }
    if (cold_inputs != 0 || !family_outputs_[family].empty()) {
      family_write_tasks_.push_back(FamilyWriteTask{
          .hot = false, .family = family, .target = cold_target});
    }
    if (!family_outputs_[family].empty()) {
      ++counters_.active_families;
    }

    hot_family_outputs_[family].clear();
    if (!counters_.hot_enabled) {
      continue;
    }
    hot_family_outputs_[family] = merge_family(true, family, hot_target);
    counters_.hot_family_edges[family] = hot_family_outputs_[family].size();
    rows = 0;
    last_src = 0;
    have_src = false;
    for (const SpineEdgeRecord &edge : hot_family_outputs_[family]) {
      if (!have_src || edge.src != last_src) {
        ++rows;
        last_src = edge.src;
        have_src = true;
      }
    }
    counters_.hot_family_rows[family] = rows;
    const auto &hot_levels = state_.hot_levels[family];
    std::size_t hot_inputs = coalesce_family(true, family).size();
    for (std::size_t level = 0; level < hot_target; ++level) {
      hot_inputs += hot_levels[level].size();
    }
    if (hot_inputs != 0 || !hot_family_outputs_[family].empty()) {
      family_write_tasks_.push_back(
          FamilyWriteTask{.hot = true, .family = family, .target = hot_target});
    }
    if (!hot_family_outputs_[family].empty()) {
      ++counters_.active_families;
    }
  }
}

void SpineL0Maintenance::enqueue_dirty_source_updates() {
  std::vector<std::uint32_t> sources;
  for (const SpineEdgeRecord &edge : sorted_scan_edges_) {
    if (sources.empty() || sources.back() != edge.src) {
      sources.push_back(edge.src);
    }
  }
  counters_.unique_sources = sources.size();
  std::map<std::uint64_t, std::vector<std::uint8_t>> bitmap_words;
  std::map<std::uint64_t, std::vector<std::uint8_t>> list_words;
  std::uint64_t hash_sum = 0;
  std::uint64_t hash_xor = 0;
  for (std::size_t index = 0; index < sources.size(); ++index) {
    const std::uint32_t src = sources[index];
    const std::uint64_t bitmap = config_.persistent_dirty_bitmap_base +
                                 (src >> 7) * kPersistentRecordBytes;
    const std::uint64_t list = config_.persistent_dirty_list_base +
                               (index >> 2) * kPersistentRecordBytes;
    auto &bitmap_payload = bitmap_words[bitmap];
    if (bitmap_payload.empty()) {
      bitmap_payload.resize(kPersistentRecordBytes, 0);
    }
    bitmap_payload[(src & 127U) >> 3] |=
        static_cast<std::uint8_t>(1U << (src & 7U));
    enqueue_task(*ports_.sorted_edges, MemoryOperation::kRead, bitmap,
                 kPersistentRecordBytes, TaskClass::kPersistent);
    enqueue_task(*ports_.sorted_edges, MemoryOperation::kWrite, bitmap,
                 kPersistentRecordBytes, TaskClass::kPersistent,
                 bitmap_payload);

    auto &list_payload = list_words[list];
    if (list_payload.empty()) {
      list_payload.resize(kPersistentRecordBytes, 0);
    }
    const std::size_t lane = (index & 3U) * sizeof(std::uint32_t);
    for (std::size_t byte = 0; byte < sizeof(src); ++byte) {
      list_payload[lane + byte] =
          static_cast<std::uint8_t>((src >> (byte * 8)) & 0xffU);
    }
    enqueue_task(*ports_.sorted_edges, MemoryOperation::kRead, list,
                 kPersistentRecordBytes, TaskClass::kPersistent);
    enqueue_task(*ports_.sorted_edges, MemoryOperation::kWrite, list,
                 kPersistentRecordBytes, TaskClass::kPersistent, list_payload);
    hash_sum += spine_dirty_hash_sum_term(src);
    hash_xor ^= spine_dirty_hash_xor_term(src);
  }
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  const auto write_word = [&](std::uint64_t word, std::uint64_t value) {
    enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                 config_.metadata_base + word * kMetadataWordBytes,
                 kMetadataWordBytes, TaskClass::kMetadata,
                 encode_u64_words({value}));
  };
  write_word(metadata.dirty_generation_word, 1);
  write_word(metadata.dirty_candidate_valid_word, 0);
  write_word(metadata.dirty_host_valid_word, 0);
  write_word(metadata.dirty_count_word, sources.size());
  write_word(metadata.dirty_hash_sum_word, hash_sum);
  write_word(metadata.dirty_hash_xor_word, hash_xor);
  write_word(metadata.dirty_last_mode_word, 0);
  write_word(metadata.dirty_last_status_word, 0);
}

void SpineL0Maintenance::enqueue_family_writes(bool hot, std::size_t family,
                                               std::size_t target) {
  const auto &edges =
      hot ? hot_family_outputs_[family] : family_outputs_[family];
  const std::uint64_t rows =
      hot ? counters_.hot_family_rows[family] : counters_.family_rows[family];
  const SpineLevelLayout layout = spine_level_layout(config_, hot, target);
  if (edges.size() > layout.edge_capacity || rows > layout.edge_capacity) {
    failed_ = true;
    done_ = true;
    failure_ = "Spine target family exceeds fixed level capacity";
    return;
  }
  std::set<std::uint32_t> pages;
  for (const SpineEdgeRecord &edge : edges) {
    pages.insert(edge.src / config_.page_vertices);
  }

  FixedAxiPort &graph = *ports_.graph[family];
  for (GraphPayloadWrite &write :
       build_level_index_payloads(config_, layout, edges, rows)) {
    const std::uint64_t bytes = write.data.size();
    counters_.graph_index_payload_write_bytes += bytes;
    enqueue_task(graph, MemoryOperation::kWrite, write.address, bytes,
                 TaskClass::kGraph, std::move(write.data));
  }
  std::vector<std::uint8_t> edge_payload;
  edge_payload.reserve(edges.size() * kSpineGraphWordBytes);
  for (const SpineEdgeRecord &edge : edges) {
    const std::vector<std::uint8_t> packed = encode_spine_level_edge(edge);
    edge_payload.insert(edge_payload.end(), packed.begin(), packed.end());
  }
  const std::uint64_t edge_payload_bytes = edge_payload.size();
  counters_.graph_edge_payload_write_bytes += edge_payload_bytes;
  enqueue_task(graph, MemoryOperation::kWrite,
               layout.edge_offset_words * kSpineGraphWordBytes,
               edge_payload_bytes, TaskClass::kGraph, std::move(edge_payload));

  counters_.pages_stamped += pages.size();
  counters_.persisted_edges += edges.size();
  counters_.persisted_rows += rows;
  const std::size_t logical_family = hot ? config_.partitions + family : family;
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  std::uint32_t epoch = ++slice_epochs_[logical_family][target];
  if (epoch == 0) {
    epoch = 1;
    slice_epochs_[logical_family][target] = epoch;
  }
  const std::uint64_t slice = logical_family * config_.levels + target;
  std::set<std::uint64_t> page_epoch_words;
  for (const std::uint32_t page : pages) {
    const std::uint64_t index = slice * metadata.page_count + page;
    page_epochs_[index] = epoch;
    page_epoch_words.insert(index >> 1);
  }
  for (const std::uint64_t word : page_epoch_words) {
    const std::uint64_t low_index = word * 2;
    const auto low = page_epochs_.find(low_index);
    const auto high = page_epochs_.find(low_index + 1);
    const std::uint64_t packed =
        (low == page_epochs_.end() ? 0 : low->second) |
        (static_cast<std::uint64_t>(high == page_epochs_.end() ? 0
                                                               : high->second)
         << 32);
    enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                 config_.metadata_base +
                     (metadata.page_epoch_base + word) * kMetadataWordBytes,
                 kMetadataWordBytes, TaskClass::kMetadata,
                 encode_u64_words({packed}));
  }
}

void SpineL0Maintenance::enqueue_carry_reads(bool hot, std::size_t family,
                                             std::size_t target) {
  const auto &levels = hot ? state_.hot_levels : state_.cold_levels;
  FixedAxiPort &graph = *ports_.graph[family];
  const std::size_t logical_family = hot ? config_.partitions + family : family;
  for (std::size_t level = 0; level < target; ++level) {
    const auto &edges = levels[family][level];
    if (edges.empty()) {
      continue;
    }
    const SpineLevelLayout layout = spine_level_layout(config_, hot, level);
    std::set<std::uint32_t> pages;
    std::uint64_t rows = 0;
    std::uint32_t last_source = 0;
    bool have_source = false;
    std::vector<std::uint32_t> edge_sources;
    edge_sources.reserve(edges.size());
    for (const SpineEdgeRecord &edge : edges) {
      edge_sources.push_back(edge.src);
      pages.insert(edge.src / config_.page_vertices);
      if (!have_source || edge.src != last_source) {
        ++rows;
        last_source = edge.src;
        have_source = true;
      }
    }
    enqueue_task(
        *ports_.metadata, MemoryOperation::kRead,
        config_.metadata_base +
            (logical_family * config_.levels + level) * 8 * kMetadataWordBytes,
        9 * kMetadataWordBytes, TaskClass::kMetadata);
    enqueue_task(*ports_.metadata, MemoryOperation::kRead,
                 config_.metadata_base +
                     (256 + logical_family * config_.levels + level) *
                         kMetadataWordBytes,
                 ((pages.size() + 3) / 4) * kMetadataWordBytes,
                 TaskClass::kMetadata);
    for (const std::uint32_t page : pages) {
      enqueue_task(
          graph, MemoryOperation::kRead,
          (layout.bitmap_offset_words + page * 4) * kSpineGraphWordBytes,
          4 * kSpineGraphWordBytes, TaskClass::kGraph);
      enqueue_task(
          graph, MemoryOperation::kRead,
          (layout.page_base_offset_words + (page >> 1)) * kSpineGraphWordBytes,
          kSpineGraphWordBytes, TaskClass::kGraph);
    }
    enqueue_task(graph, MemoryOperation::kRead,
                 layout.row_offset_offset_words * kSpineGraphWordBytes,
                 ((rows + 2) >> 1) * kSpineGraphWordBytes, TaskClass::kGraph);
    enqueue_task(graph, MemoryOperation::kRead,
                 layout.mask_offset_words * kSpineGraphWordBytes,
                 ((rows + 3) >> 2) * kSpineGraphWordBytes, TaskClass::kGraph);
    enqueue_task(graph, MemoryOperation::kRead,
                 layout.edge_offset_words * kSpineGraphWordBytes,
                 edges.size() * kSpineGraphWordBytes, TaskClass::kGraph, {},
                 std::move(edge_sources));
    counters_.carry_level_payload_reads += edges.size();
  }
}

void SpineL0Maintenance::commit_level_state(bool hot, std::size_t target) {
  auto &levels = hot ? state_.hot_levels : state_.cold_levels;
  const auto &outputs = hot ? hot_family_outputs_ : family_outputs_;
  for (std::size_t family = 0; family < config_.partitions; ++family) {
    levels[family][target] = outputs[family];
    for (std::size_t level = 0; level < target; ++level) {
      levels[family][level].clear();
    }
  }
}

void SpineL0Maintenance::enqueue_committed_metadata() {
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  std::set<std::uint64_t> slice_epoch_words;
  const auto publish = [&](bool hot, std::size_t target) {
    const auto &levels = hot ? state_.hot_levels : state_.cold_levels;
    for (std::size_t family = 0; family < config_.partitions; ++family) {
      const std::size_t logical_family =
          hot ? config_.partitions + family : family;
      for (std::size_t level = 0; level <= target; ++level) {
        const auto &edges = levels[family][level];
        const std::uint64_t slice = logical_family * config_.levels + level;
        std::vector<std::uint8_t> payload;
        if (edges.empty()) {
          payload = encode_u64_words({0, 0, 0, 0, 0, 0, 0, 0});
        } else {
          const SpineLevelLayout layout =
              spine_level_layout(config_, hot, level);
          payload = encode_u64_words(
              {edges.size(), row_count_for_edges(edges),
               layout.bitmap_offset_words, layout.page_base_offset_words,
               layout.row_offset_offset_words, layout.mask_offset_words,
               layout.edge_offset_words, 1});
        }
        const std::uint64_t bytes = payload.size();
        enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                     config_.metadata_base + slice * 8 * kMetadataWordBytes,
                     bytes, TaskClass::kMetadata, std::move(payload));
        slice_epoch_words.insert(slice >> 1);
      }
    }
  };
  publish(false, static_cast<std::size_t>(counters_.target_level));
  if (state_.hot_enabled) {
    publish(true, static_cast<std::size_t>(counters_.hot_target_level));
  }
  for (const std::uint64_t word : slice_epoch_words) {
    const std::uint64_t low_index = word * 2;
    const std::size_t low_family = low_index / config_.levels;
    const std::size_t low_level = low_index % config_.levels;
    std::uint64_t packed = slice_epochs_[low_family][low_level];
    if (low_index + 1 < metadata.slice_count) {
      const std::uint64_t high_index = low_index + 1;
      packed |=
          static_cast<std::uint64_t>(slice_epochs_[high_index / config_.levels]
                                                  [high_index % config_.levels])
          << 32;
    }
    enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                 config_.metadata_base +
                     (metadata.slice_epoch_base + word) * kMetadataWordBytes,
                 kMetadataWordBytes, TaskClass::kMetadata,
                 encode_u64_words({packed}));
  }
}

void SpineL0Maintenance::advance(const CycleContext &context) {
  switch (phase_) {
    case Phase::kInitialize:
      counters_.start_cycle = context.domain_cycle;
      counters_.hot_enabled = state_.hot_enabled;
      for (const SpineEdgeRecord &edge : sorted_scan_edges_) {
        if (edge_is_hot(edge.dst)) {
          ++counters_.hot_input_edges;
        } else {
          ++counters_.cold_input_edges;
        }
      }
      enqueue_task(*ports_.metadata, MemoryOperation::kRead,
                   config_.metadata_base +
                       spine_metadata_layout(config_).hot_enabled_word *
                           kMetadataWordBytes,
                   kMetadataWordBytes, TaskClass::kMetadata);
      phase_ = Phase::kDirtyPreflightBegin;
      return;
    case Phase::kDirtyPreflightBegin:
      begin_sorted_scan(Phase::kDirtyPreflightProcess);
      return;
    case Phase::kDirtyPreflightProcess:
      process_scan_edge(Phase::kDirtyUpdateBegin);
      return;
    case Phase::kDirtyUpdateBegin:
      begin_sorted_scan(Phase::kDirtyUpdateProcess);
      return;
    case Phase::kDirtyUpdateProcess:
      if (scan_index_ + 1 == sorted_scan_edges_.size()) {
        ++counters_.sorted_edge_visits;
        ++scan_index_;
        enqueue_dirty_source_updates();
        phase_ = Phase::kTargetSelect;
      } else {
        process_scan_edge(Phase::kTargetSelect);
      }
      return;
    case Phase::kTargetSelect:
      enqueue_task(*ports_.metadata, MemoryOperation::kRead,
                   config_.metadata_base,
                   config_.partitions * config_.levels * 2 * kMetadataWordBytes,
                   TaskClass::kMetadata);
      counters_.target_level = static_cast<std::int32_t>(target_for(false));
      if (counters_.target_level >= static_cast<std::int32_t>(config_.levels)) {
        failed_ = true;
        done_ = true;
        failure_ = "Spine cold level hierarchy has no free target";
        return;
      }
      counters_.hot_target_level = -1;
      if (state_.hot_enabled) {
        enqueue_task(
            *ports_.metadata, MemoryOperation::kRead,
            config_.metadata_base +
                config_.partitions * config_.levels * 8 * kMetadataWordBytes,
            config_.partitions * config_.levels * 2 * kMetadataWordBytes,
            TaskClass::kMetadata);
        counters_.hot_target_level =
            static_cast<std::int32_t>(target_for(true));
        if (counters_.hot_target_level >=
            static_cast<std::int32_t>(config_.levels)) {
          failed_ = true;
          done_ = true;
          failure_ = "Spine hot level hierarchy has no free target";
          return;
        }
      }
      family_index_ = 0;
      precount_hot_ = false;
      phase_ = Phase::kPrecountBegin;
      return;
    case Phase::kPrecountBegin:
      begin_sorted_scan(Phase::kPrecountProcess);
      return;
    case Phase::kPrecountProcess:
      if (scan_index_ + 1 == sorted_scan_edges_.size()) {
        ++counters_.sorted_edge_visits;
        ++scan_index_;
        ++family_index_;
        if (family_index_ == config_.partitions) {
          if (!precount_hot_ && state_.hot_enabled) {
            precount_hot_ = true;
            family_index_ = 0;
            phase_ = Phase::kPrecountBegin;
          } else {
            phase_ = Phase::kBuildOutputs;
          }
        } else {
          phase_ = Phase::kPrecountBegin;
        }
      } else {
        process_scan_edge(Phase::kPrecountBegin);
      }
      return;
    case Phase::kBuildOutputs:
      build_family_outputs();
      active_family_index_ = 0;
      phase_ = Phase::kWriteSelect;
      return;
    case Phase::kWriteSelect:
      if (active_family_index_ == family_write_tasks_.size()) {
        phase_ = Phase::kCommitMetadata;
      } else {
        phase_ = family_write_tasks_[active_family_index_].target == 0
                     ? Phase::kWriteBegin
                     : Phase::kCarryPrepare;
      }
      return;
    case Phase::kWriteBegin:
      begin_sorted_scan(Phase::kWriteProcess);
      return;
    case Phase::kWriteProcess:
      if (scan_index_ + 1 == sorted_scan_edges_.size()) {
        ++counters_.sorted_edge_visits;
        ++scan_index_;
        const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
        enqueue_family_writes(task.hot, task.family, task.target);
        if (failed_) {
          return;
        }
        phase_ = Phase::kWriteAdvance;
      } else {
        process_scan_edge(Phase::kWriteAdvance);
      }
      return;
    case Phase::kCarryPrepare: {
      const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
      const auto &levels = task.hot ? state_.hot_levels : state_.cold_levels;
      carry_payload_edges_.clear();
      carry_steps_remaining_ = coalesce_family(task.hot, task.family).size();
      for (std::size_t level = 0; level < task.target; ++level) {
        carry_steps_remaining_ += levels[task.family][level].size();
      }
      enqueue_carry_reads(task.hot, task.family, task.target);
      phase_ = Phase::kCarryProcess;
      return;
    }
    case Phase::kCarryProcess: {
      if (carry_steps_remaining_ != 0) {
        --carry_steps_remaining_;
        ++counters_.carry_merge_inputs;
        return;
      }
      const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
      auto &output = task.hot ? hot_family_outputs_[task.family]
                              : family_outputs_[task.family];
      const bool was_active = !output.empty();
      output = merge_family_with_carry_payload(task.hot, task.family);
      const bool is_active = !output.empty();
      if (was_active && !is_active) {
        --counters_.active_families;
      } else if (!was_active && is_active) {
        ++counters_.active_families;
      }
      std::uint64_t rows = 0;
      std::uint32_t last_src = 0;
      bool have_src = false;
      for (const SpineEdgeRecord &edge : output) {
        if (!have_src || edge.src != last_src) {
          ++rows;
          last_src = edge.src;
          have_src = true;
        }
      }
      if (task.hot) {
        counters_.hot_family_edges[task.family] = output.size();
        counters_.hot_family_rows[task.family] = rows;
      } else {
        counters_.family_edges[task.family] = output.size();
        counters_.family_rows[task.family] = rows;
      }
      counters_.carry_outputs += output.size();
      if (!output.empty()) {
        enqueue_family_writes(task.hot, task.family, task.target);
        if (failed_) {
          return;
        }
      }
      phase_ = Phase::kWriteAdvance;
      return;
    }
    case Phase::kWriteAdvance:
      ++active_family_index_;
      phase_ = Phase::kWriteSelect;
      return;
    case Phase::kCommitMetadata:
      commit_level_state(false,
                         static_cast<std::size_t>(counters_.target_level));
      if (state_.hot_enabled) {
        commit_level_state(
            true, static_cast<std::size_t>(counters_.hot_target_level));
      }
      enqueue_committed_metadata();
      phase_ = Phase::kWriteResult;
      return;
    case Phase::kWriteResult:
      enqueue_task(*ports_.metadata, MemoryOperation::kRead,
                   config_.metadata_base,
                   config_.partitions * (state_.hot_enabled ? 2 : 1) *
                       kMetadataWordBytes,
                   TaskClass::kMetadata);
      enqueue_task(*ports_.result, MemoryOperation::kWrite, config_.result_base,
                   kResultWords * 4, TaskClass::kResult);
      phase_ = Phase::kFinish;
      return;
    case Phase::kFinish:
      counters_.end_cycle = context.domain_cycle;
      done_ = true;
      return;
  }
}

}  // namespace spine::sim
