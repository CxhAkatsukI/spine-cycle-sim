#include "spine_sim/spine_l0.hpp"

#include <algorithm>
#include <array>
#include <bit>
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
constexpr std::uint64_t kMetadataMagic = 0x53504352ULL;
constexpr std::uint64_t kMetadataVersion = 2;
constexpr std::uint64_t kMetadataRequiredFeatures = 3;
constexpr std::uint64_t kCandidateMetadataVersion = 5;
constexpr std::uint64_t kCandidateMetadataRequiredFeatures = 31;
constexpr std::uint64_t kMetadataWordsPerSlice = 8;
constexpr std::uint64_t kMetadataEdgeCountWord = 0;
constexpr std::uint64_t kMetadataOccupiedWord = 7;

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

std::uint64_t read_u64_le(const std::vector<std::uint8_t> &data,
                          std::size_t offset) {
  if (offset + sizeof(std::uint64_t) > data.size()) {
    throw std::logic_error("Spine u64 payload read is out of range");
  }
  std::uint64_t value = 0;
  for (std::size_t byte = 0; byte < sizeof(value); ++byte) {
    value |= static_cast<std::uint64_t>(data[offset + byte]) << (byte * 8);
  }
  return value;
}

std::uint32_t read_u32_le(const std::vector<std::uint8_t> &data,
                          std::size_t offset) {
  if (offset + sizeof(std::uint32_t) > data.size()) {
    throw std::logic_error("Spine u32 payload read is out of range");
  }
  std::uint32_t value = 0;
  for (std::size_t byte = 0; byte < sizeof(value); ++byte) {
    value |= static_cast<std::uint32_t>(data[offset + byte]) << (byte * 8);
  }
  return value;
}

void write_u32_le(std::vector<std::uint8_t> &data, std::size_t offset,
                  std::uint32_t value) {
  if (offset + sizeof(value) > data.size()) {
    throw std::logic_error("Spine u32 payload write is out of range");
  }
  for (std::size_t byte = 0; byte < sizeof(value); ++byte) {
    data[offset + byte] =
        static_cast<std::uint8_t>((value >> (byte * 8)) & 0xffU);
  }
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

std::uint32_t candidate_hash_mix(std::uint32_t term) noexcept {
  term ^= term << 13;
  term ^= term >> 17;
  term ^= term << 5;
  return term;
}

std::uint32_t candidate_tag_hash_term(std::uint32_t source,
                                      std::uint32_t family,
                                      std::uint32_t input_index) noexcept {
  return candidate_hash_mix(source ^ (family << 25) ^ input_index);
}

std::uint32_t candidate_dispatch_hash_term(const SpineEdgeRecord &edge,
                                           std::uint32_t family,
                                           std::uint32_t bucket_index) {
  const std::vector<std::uint8_t> packed = encode_spine_sort_edge(edge);
  std::uint32_t term = 0;
  for (std::size_t word = 0; word < 4; ++word) {
    term ^= read_u32_le(packed, word * sizeof(std::uint32_t));
  }
  return candidate_hash_mix(term ^ (family << 26) ^ bucket_index);
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

std::vector<std::uint8_t> encode_u16_lanes(
    const std::vector<std::uint32_t> &values) {
  std::vector<std::uint8_t> data;
  data.reserve(((values.size() + 3) / 4) * kMetadataWordBytes);
  for (std::size_t base = 0; base < values.size(); base += 4) {
    std::uint64_t packed = 0;
    for (std::size_t lane = 0; lane < 4 && base + lane < values.size();
         ++lane) {
      if (values[base + lane] > std::numeric_limits<std::uint16_t>::max()) {
        throw std::overflow_error("Spine page ID exceeds metadata lane");
      }
      packed |= static_cast<std::uint64_t>(values[base + lane]) << (lane * 16);
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
  layout.hot_bitmap_base = hot_bitmap_base;
  layout.hot_bitmap_words = hot_bitmap_words;
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
  layout.family_directory_valid_word = layout.dirty_base + 16;
  layout.family_tag_base = layout.family_directory_valid_word + 1;
  layout.family_tag_words =
      (static_cast<std::uint64_t>(config.max_sort_edges) + 7) / 8;
  layout.source_record_base = layout.family_tag_base + layout.family_tag_words;
  layout.source_record_words = config.max_sort_edges;
  layout.new_dirty_base =
      layout.source_record_base + layout.source_record_words;
  layout.new_dirty_words =
      (static_cast<std::uint64_t>(config.max_sort_edges) + 1) / 2;
  layout.total_words =
      config.maintenance_architecture ==
              SpineMaintenanceArchitecture::kCandidate10OnePass
          ? layout.new_dirty_base + layout.new_dirty_words
          : layout.dirty_base + 16;
  return layout;
}

std::uint64_t spine_metadata_control_word(bool hot_enabled) {
  return spine_metadata_control_word(
      hot_enabled, SpineMaintenanceArchitecture::kSharedEngineSerial);
}

std::uint64_t spine_metadata_control_word(
    bool hot_enabled, SpineMaintenanceArchitecture architecture) {
  const bool candidate =
      architecture == SpineMaintenanceArchitecture::kCandidate10OnePass;
  const std::uint64_t version =
      candidate ? kCandidateMetadataVersion : kMetadataVersion;
  const std::uint64_t features = candidate ? kCandidateMetadataRequiredFeatures
                                           : kMetadataRequiredFeatures;
  return (kMetadataMagic << 32) | (version << 16) | (features << 1) |
         (hot_enabled ? 1ULL : 0ULL);
}

bool spine_metadata_control_valid(std::uint64_t control) noexcept {
  return spine_metadata_control_valid(
      control, SpineMaintenanceArchitecture::kSharedEngineSerial);
}

bool spine_metadata_control_valid(
    std::uint64_t control,
    SpineMaintenanceArchitecture architecture) noexcept {
  const std::uint64_t magic = control >> 32;
  const std::uint64_t version = (control >> 16) & 0xffffULL;
  const std::uint64_t features = (control >> 1) & 0x7fffULL;
  const bool candidate =
      architecture == SpineMaintenanceArchitecture::kCandidate10OnePass;
  return magic == kMetadataMagic &&
         version ==
             (candidate ? kCandidateMetadataVersion : kMetadataVersion) &&
         features == (candidate ? kCandidateMetadataRequiredFeatures
                                : kMetadataRequiredFeatures);
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

SpineLevelLayout spine_slice_layout(const SpineL0Config &config, bool hot,
                                    std::size_t level,
                                    std::uint64_t row_count) {
  SpineLevelLayout layout = spine_level_layout(config, hot, level);
  if (row_count > layout.edge_capacity) {
    throw std::overflow_error("Spine slice row count exceeds level capacity");
  }
  if (level != 0) {
    return layout;
  }

  // Latest HLS compacts the L0 row and mask arrays to the pre-counted rows.
  // Higher carry levels retain their fixed-capacity layout.
  layout.row_capacity_words = (row_count + 2) >> 1;
  layout.mask_capacity_words = (row_count + 3) >> 2;
  layout.mask_offset_words =
      layout.row_offset_offset_words + layout.row_capacity_words;
  layout.edge_offset_words =
      layout.mask_offset_words + layout.mask_capacity_words;
  return layout;
}

std::vector<std::uint8_t> encode_spine_maintenance_result(
    const SpineMaintenanceResult &result) {
  std::vector<std::uint8_t> data;
  data.reserve(kSpineMaintenanceResultBytes);
  for (const std::int32_t word : result.words) {
    const std::uint32_t bits = std::bit_cast<std::uint32_t>(word);
    for (std::size_t byte = 0; byte < sizeof(bits); ++byte) {
      data.push_back(
          static_cast<std::uint8_t>((bits >> (byte * 8)) & 0xffU));
    }
  }
  return data;
}

SpineMaintenanceResult decode_spine_maintenance_result(
    std::span<const std::uint8_t> data) {
  if (data.size() != kSpineMaintenanceResultBytes) {
    throw std::invalid_argument(
        "Spine maintenance result payload must contain 96 words");
  }
  SpineMaintenanceResult result;
  for (std::size_t word = 0; word < result.words.size(); ++word) {
    std::uint32_t bits = 0;
    for (std::size_t byte = 0; byte < sizeof(bits); ++byte) {
      bits |= static_cast<std::uint32_t>(
                  data[word * sizeof(bits) + byte])
              << (byte * 8);
    }
    result.words[word] = std::bit_cast<std::int32_t>(bits);
  }
  return result;
}

SpineEdgeSlice load_spine_edge_slice(const std::filesystem::path &path,
                                     bool allow_empty) {
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
    if (!allow_empty) {
      throw std::runtime_error("Spine edge slice has no edge records: " +
                               path.string());
    }
    if (slice.vertices == 0) {
      throw std::runtime_error(
          "Empty Spine edge slice requires vertices metadata: " +
          path.string());
    }
    return slice;
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
      config_.range_task_active_gate == 0 || config_.range_task_capacity == 0 ||
      config_.range_task_capacity > 65'536 ||
      config_.range_task_payload_budget == 0 ||
      config_.fallback_replay_threshold == 0 ||
      config_.memory_request_window == 0 ||
      config_.maintenance_target_select_request_window == 0 ||
      config_.maintenance_result_request_window == 0 ||
      config_.maintenance_cold_target_select_min_cycles == 0 ||
      config_.maintenance_hot_target_select_min_cycles == 0 ||
      config_.maintenance_hot_bitmap_request_window == 0 ||
      config_.reader_edge_pipeline_depth == 0 ||
      config_.reader_edge_response_capacity == 0 ||
      config_.maintenance_count_scan_ii == 0 ||
      config_.maintenance_l0_write_scan_ii == 0 ||
      config_.maintenance_scan_response_capacity == 0 ||
      config_.candidate_classify_block_edges == 0 ||
      config_.candidate_classify_block_edges % 8 != 0 ||
      config_.candidate_source_prefetch == 0 ||
      config_.candidate_publication_window == 0 ||
      config_.candidate_memory_request_window == 0 ||
      config_.persistent_family_directory_base <
          config_.persistent_dirty_list_base ||
      config_.persistent_family_bucket_base <
          config_.persistent_family_directory_base ||
      workload_.vertices == 0 || workload_.vertices > config_.max_vertices ||
      (workload_.edges.empty() &&
       config_.maintenance_architecture ==
           SpineMaintenanceArchitecture::kSharedEngineSerial) ||
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
  if (!workload_.edges.empty()) {
    ports_.sorted_edges->initialize_payload(
        config_.sorted_edges_base, encode_spine_sort_edges(workload_.edges));
  }
  const auto initialize_levels = [&](const auto &families, bool hot) {
    for (std::size_t family = 0; family < families.size(); ++family) {
      for (std::size_t level = 0; level < families[family].size(); ++level) {
        const auto &edges = families[family][level];
        if (edges.empty()) {
          continue;
        }
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
        const SpineLevelLayout layout =
            spine_slice_layout(config_, hot, level, rows);
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

void SpineL0Maintenance::reset_batch(SpineEdgeSlice workload) {
  const bool ports_idle =
      std::all_of(ports_.graph.begin(), ports_.graph.end(),
                  [](const FixedAxiPort *port) { return port->idle(); }) &&
      ports_.sorted_edges->idle() && ports_.metadata->idle() &&
      ports_.result->idle();
  if (!done_ || failed_ || !ports_idle || !tasks_.empty() ||
      !inflight_tasks_.empty() || !staged_memory_issues_.empty() ||
      workload.vertices != workload_.vertices || workload.edges.empty() ||
      workload.edges.size() > config_.max_sort_edges ||
      !std::is_sorted(
          workload.edges.begin(), workload.edges.end(),
          [](const SpineEdgeRecord &left, const SpineEdgeRecord &right) {
            return std::pair(left.src, left.dst) <
                   std::pair(right.src, right.dst);
          }) ||
      std::any_of(workload.edges.begin(), workload.edges.end(),
                  [this](const SpineEdgeRecord &edge) {
                    return edge.src >= workload_.vertices ||
                           edge.dst >= workload_.vertices;
                  })) {
    throw std::logic_error(
        "Spine maintenance batch reset requires a valid successful drain");
  }

  workload_ = std::move(workload);
  sorted_scan_edges_ = workload_.edges;
  ports_.sorted_edges->initialize_payload(
      config_.sorted_edges_base, encode_spine_sort_edges(workload_.edges));

  counters_ = {};
  carry_streams_.clear();
  carry_cursor_refill_cycles_remaining_ = 0;
  level_writer_ = {};
  for (auto &family : family_outputs_) {
    family.clear();
  }
  for (auto &family : hot_family_outputs_) {
    family.clear();
  }
  for (auto &family : candidate_family_buckets_) {
    family.clear();
  }
  candidate_family_begin_ = {};
  candidate_family_cursor_ = {};
  candidate_family_tags_.clear();
  candidate_source_records_.clear();
  candidate_classify_block_records_.clear();
  candidate_publication_window_records_.clear();
  candidate_publication_words_.clear();
  candidate_new_dirty_sources_.clear();
  candidate_list_sources_.clear();
  candidate_list_words_.clear();
  staged_writer_epochs_ = {};
  target_edge_counts_ = {};
  target_occupied_ = {};
  target_metadata_ready_ = {};
  result_cold_edge_counts_ = {};
  result_hot_edge_counts_ = {};
  result_cold_edge_counts_ready_ = {};
  result_hot_edge_counts_ready_ = {};
  carry_result_counters_ = {};
  family_write_tasks_.clear();
  tasks_.clear();
  inflight_tasks_.clear();
  scan_response_edges_.clear();
  scan_hot_results_.clear();
  scan_hot_requests_pending_.clear();
  hot_classification_by_vertex_.clear();
  phase_ = Phase::kInitialize;
  scan_kind_ = ScanKind::kDirtyValidate;
  scan_index_ = 0;
  scan_tail_remaining_ = 0;
  next_scan_consume_cycle_ = 0;
  scan_base_address_ = config_.sorted_edges_base;
  scan_transaction_id_ = 0;
  scan_transaction_valid_ = false;
  streaming_scan_ = false;
  edge_by_edge_scan_ = false;
  scan_have_last_source_ = false;
  scan_last_source_ = 0;
  dirty_source_pending_ = false;
  dirty_pending_source_ = 0;
  dirty_count_ = 0;
  dirty_generation_ = 0;
  dirty_hash_sum_ = 0;
  dirty_hash_xor_ = 0;
  dirty_status_ = SpineDirtyStatus::kOk;
  dirty_bitmap_original_payload_.clear();
  candidate_current_source_ = 0;
  candidate_current_source_mask_ = 0;
  candidate_classified_tag_hash_ = 0;
  candidate_dispatched_tag_hash_ = 0;
  candidate_block_begin_ = 0;
  candidate_block_edges_ = 0;
  candidate_reduce_cycles_remaining_ = 0;
  candidate_prefix_cycles_remaining_ = 0;
  candidate_publication_cursor_ = 0;
  candidate_publication_loaded_ = 0;
  candidate_publication_responses_ = 0;
  candidate_publication_writes_ = 0;
  candidate_list_source_cursor_ = 0;
  candidate_list_source_loaded_ = 0;
  candidate_list_read_responses_ = 0;
  candidate_probe_new_count_ = 0;
  candidate_publication_kind_ = CandidatePublicationKind::kDirectory;
  candidate_have_source_ = false;
  candidate_classify_flush_pending_ = false;
  candidate_publication_empty_proven_ = false;
  candidate_dirty_candidate_valid_ = false;
  candidate_dirty_host_valid_ = false;
  family_index_ = 0;
  active_family_index_ = 0;
  precount_hot_ = false;
  metadata_control_ready_ = false;
  metadata_hot_enabled_ = false;
  target_scan_hot_ = false;
  target_scan_level_ = 0;
  target_scan_candidate_ = -1;
  target_scan_start_cycle_ = 0;
  target_scan_min_finish_cycle_ = 0;
  active_writer_current_epoch_ = 0;
  active_writer_next_epoch_ = 0;
  active_writer_epoch_ready_ = false;
  active_writer_epoch_wrapped_ = false;
  logical_overflow_ = false;
  full_rebuild_mode_ = false;
  done_ = false;
  failed_ = false;
  failure_.clear();
  staged_action_ = StagedAction::kNone;
  staged_memory_issues_.clear();
  staged_responses_.clear();
  staged_read_beat_response_ = {};
  staged_memory_completion_ = false;
  staged_read_beat_completion_ = false;
}

void SpineL0Maintenance::reset_full_rebuild(SpineEdgeSlice snapshot) {
  if (std::any_of(snapshot.edges.begin(), snapshot.edges.end(),
                  [](const SpineEdgeRecord &edge) { return edge.diff <= 0; })) {
    throw std::logic_error(
        "Spine full rebuild requires a positive materialized snapshot");
  }
  reset_batch(std::move(snapshot));

  state_.cold_levels = {};
  state_.hot_levels = {};
  slice_epochs_ = {};
  staged_writer_epochs_ = {};
  page_list_counts_ = {};
  page_epochs_.clear();

  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  const auto clear_words = [&](std::uint64_t word, std::uint64_t words) {
    if (words == 0) {
      return;
    }
    const std::uint64_t bytes = words * kMetadataWordBytes;
    enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                 config_.metadata_base + word * kMetadataWordBytes, bytes,
                 TaskClass::kMetadata,
                 std::vector<std::uint8_t>(static_cast<std::size_t>(bytes), 0));
    ++counters_.full_rebuild_clear_requests;
    counters_.full_rebuild_clear_bytes += bytes;
  };
  clear_words(0, metadata.slice_words);
  clear_words(metadata.slice_epoch_base, (metadata.slice_count + 1) / 2);
  clear_words(metadata.page_list_count_base,
              (metadata.slice_count + 1) / 2);
  full_rebuild_mode_ = true;
  phase_ = Phase::kFullRebuildClear;
}

void SpineL0Maintenance::initialize_metadata_payload() {
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  std::map<std::uint64_t, std::uint64_t> page_list_count_words;
  ports_.metadata->initialize_payload(
      config_.metadata_base + metadata.hot_enabled_word * kMetadataWordBytes,
      encode_u64_words({spine_metadata_control_word(
          state_.hot_enabled, config_.maintenance_architecture)}));
  if (config_.maintenance_architecture ==
      SpineMaintenanceArchitecture::kCandidate10OnePass) {
    ports_.metadata->initialize_payload(
        config_.metadata_base +
            metadata.family_directory_valid_word * kMetadataWordBytes,
        encode_u64_words({1}));
  }
  std::map<std::uint64_t, std::uint64_t> hot_bitmap_payload;
  for (const std::uint32_t vertex : state_.hot_vertices) {
    const std::uint64_t word = vertex >> 6;
    hot_bitmap_payload[word] |= std::uint64_t{1} << (vertex & 63U);
  }
  for (const auto &[word, bits] : hot_bitmap_payload) {
    ports_.metadata->initialize_payload(config_.metadata_base +
                                            (metadata.hot_bitmap_base + word) *
                                                kMetadataWordBytes,
                                        encode_u64_words({bits}));
  }

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
        const SpineLevelLayout layout =
            spine_slice_layout(config_, hot, level, rows);
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
        page_list_counts_[logical_family][level] = pages.size();
        const std::uint64_t count_word = slice >> 1;
        page_list_count_words[count_word] |=
            static_cast<std::uint64_t>(pages.size())
            << ((slice & 1U) * 32);
        const std::vector<std::uint32_t> page_ids(pages.begin(), pages.end());
        ports_.metadata->initialize_payload(
            config_.metadata_base +
                (metadata.page_list_base +
                 slice * metadata.page_list_words_per_slice) *
                    kMetadataWordBytes,
            encode_u16_lanes(page_ids));
      }
    }
  };
  initialize_families(state_.cold_levels, false);
  initialize_families(state_.hot_levels, true);

  for (const auto &[word, packed] : page_list_count_words) {
    ports_.metadata->initialize_payload(
        config_.metadata_base +
            (metadata.page_list_count_base + word) * kMetadataWordBytes,
        encode_u64_words({packed}));
  }

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

void SpineL0Maintenance::evaluate(const CycleContext &context) {
  staged_action_ = StagedAction::kNone;
  staged_memory_issues_.clear();
  staged_responses_.clear();
  staged_memory_completion_ = false;
  staged_read_beat_completion_ = false;
  if (done_ || failed_) {
    return;
  }
  if (phase_ == Phase::kFullRebuildClear) {
    if (counters_.full_rebuild_clear_cycles == 0) {
      counters_.start_cycle = context.domain_cycle;
    }
    ++counters_.full_rebuild_clear_cycles;
  }
  staged_read_beat_completion_ = stage_read_beat();
  staged_memory_completion_ = stage_memory_completion();
  if (active_memory_ports() > 1) {
    ++counters_.memory_cross_port_overlap_cycles;
  }
  if (target_selector_phase()) {
    ++counters_.target_selector_cycles;
  }
  const auto writer_task = [](const MemoryTask &task) {
    return task.purpose == TaskPurpose::kLevelWriterGraphWrite ||
           task.purpose == TaskPurpose::kLevelWriterMetadataWrite;
  };
  const bool queued_writer =
      std::any_of(tasks_.begin(), tasks_.end(), writer_task);
  const bool inflight_writer = std::any_of(
      inflight_tasks_.begin(), inflight_tasks_.end(),
      [&](const auto &entry) { return writer_task(entry.second); });
  if (phase_ == Phase::kWriteProcess && (queued_writer || inflight_writer)) {
    ++counters_.l0_writer_memory_overlap_cycles;
  }
  if (phase_ == Phase::kWriteEpochClear &&
      (!tasks_.empty() || !inflight_tasks_.empty())) {
    ++counters_.epoch_clear_wait_cycles;
  }
  stage_memory_issues();
  if (scan_process_phase()) {
    if (scan_can_advance(context)) {
      staged_action_ = StagedAction::kAdvance;
    }
    return;
  }
  if (phase_ == Phase::kCandidateClassifyReduce) {
    staged_action_ = StagedAction::kAdvance;
    return;
  }
  if (phase_ == Phase::kCandidateClassifyFlush) {
    const auto classify_flush_task = [](const MemoryTask &task) {
      return task.purpose == TaskPurpose::kCandidateFamilyTagWrite ||
             task.purpose == TaskPurpose::kCandidateSourceRecordWrite;
    };
    const bool queued =
        std::any_of(tasks_.begin(), tasks_.end(), classify_flush_task);
    const bool inflight = std::any_of(
        inflight_tasks_.begin(), inflight_tasks_.end(),
        [&](const auto &entry) { return classify_flush_task(entry.second); });
    if (queued || inflight || staged_memory_completion_) {
      return;
    }
    staged_action_ = StagedAction::kAdvance;
    return;
  }
  if (!tasks_.empty() || !inflight_tasks_.empty() ||
      staged_memory_completion_ || staged_read_beat_completion_) {
    if (phase_ == Phase::kCarryProcess) {
      ++counters_.carry_refill_wait_cycles;
      ++active_carry_result_counters().refill_stalls;
    }
    if (queued_writer || inflight_writer) {
      if (level_writer_.l0_mode) {
        ++counters_.l0_writer_memory_wait_cycles;
      } else {
        ++counters_.carry_writer_memory_wait_cycles;
      }
    }
    return;
  }
  staged_action_ = StagedAction::kAdvance;
}

void SpineL0Maintenance::commit(const CycleContext &context) {
  if (staged_read_beat_completion_) {
    if (!staged_read_beat_response_.success) {
      failed_ = true;
      done_ = true;
      failure_ = "Spine AXI read beat failed";
      return;
    }
    consume_read_beat(staged_read_beat_response_);
  }
  if (staged_memory_completion_) {
    for (const AxiResponse &response : staged_responses_) {
      const auto found = inflight_tasks_.find(response.transaction_id);
      if (found == inflight_tasks_.end() || !response.success) {
        failed_ = true;
        done_ = true;
        failure_ =
            "Spine AXI response failed or used an unknown transaction ID";
        return;
      }
    }
    for (const AxiResponse &response : staged_responses_) {
      const auto found = inflight_tasks_.find(response.transaction_id);
      consume_memory_response(found->second, response);
      inflight_tasks_.erase(found);
      ++counters_.memory_requests_completed;
    }
  }
  if (!staged_memory_issues_.empty()) {
    std::vector<std::pair<std::uint64_t, MemoryTask>> issued;
    issued.reserve(staged_memory_issues_.size());
    for (auto current = staged_memory_issues_.rbegin();
         current != staged_memory_issues_.rend(); ++current) {
      if (current->task_index >= tasks_.size()) {
        throw std::logic_error("invalid staged Spine memory task index");
      }
      auto task = tasks_.begin() +
                  static_cast<std::ptrdiff_t>(current->task_index);
      issued.emplace_back(current->transaction_id, std::move(*task));
      tasks_.erase(task);
    }
    std::sort(issued.begin(), issued.end(),
              [](const auto &left, const auto &right) {
                return left.first < right.first;
              });
    for (auto &[transaction_id, task] : issued) {
      if (task.stream_sorted_scan) {
        if (scan_transaction_valid_) {
          throw std::logic_error("overlapping Spine sorted scan transactions");
        }
        scan_transaction_id_ = transaction_id;
        scan_transaction_valid_ = true;
      }
      auto [found, inserted] =
          inflight_tasks_.emplace(transaction_id, std::move(task));
      if (!inserted) {
        throw std::logic_error("duplicate Spine memory transaction ID");
      }
      ++counters_.memory_requests_issued;
      counters_.max_memory_requests_inflight =
          std::max(counters_.max_memory_requests_inflight,
                   inflight_tasks_.size());
      update_memory_concurrency_counters(found->second.port);
    }
    next_transaction_id_ += issued.size();
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

std::size_t SpineL0Maintenance::inflight_memory_tasks_for_port(
    const FixedAxiPort *port) const noexcept {
  return static_cast<std::size_t>(std::count_if(
      inflight_tasks_.begin(), inflight_tasks_.end(),
      [port](const auto &entry) { return entry.second.port == port; }));
}

std::size_t SpineL0Maintenance::active_memory_ports() const noexcept {
  std::size_t ports = 0;
  for (auto current = inflight_tasks_.begin();
       current != inflight_tasks_.end(); ++current) {
    bool already_seen = false;
    for (auto prior = inflight_tasks_.begin(); prior != current; ++prior) {
      already_seen = already_seen ||
                     prior->second.port == current->second.port;
    }
    if (!already_seen) {
      ++ports;
    }
  }
  return ports;
}

bool SpineL0Maintenance::target_selector_phase() const noexcept {
  return phase_ == Phase::kTargetSelect ||
         phase_ == Phase::kTargetSelectLevelWait ||
         phase_ == Phase::kTargetSelectPadding;
}

std::size_t SpineL0Maintenance::memory_request_window_for(
    const MemoryTask &task) const noexcept {
  if (task.purpose == TaskPurpose::kTargetMetadataOccupied ||
      task.purpose == TaskPurpose::kTargetMetadataEdgeCount) {
    return config_.maintenance_target_select_request_window;
  }
  if (task.purpose == TaskPurpose::kResultColdEdgeCount ||
      task.purpose == TaskPurpose::kResultHotEdgeCount) {
    return config_.maintenance_result_request_window;
  }
  if (task.purpose == TaskPurpose::kScanHotBitmap ||
      task.purpose == TaskPurpose::kCarryNewBatchHotBitmap) {
    return config_.maintenance_hot_bitmap_request_window;
  }
  if (task.purpose == TaskPurpose::kCandidatePublicationSourceRead ||
      task.purpose == TaskPurpose::kCandidateListSourceRead) {
    return std::min(config_.candidate_source_prefetch,
                    config_.candidate_memory_request_window);
  }
  if (task.purpose == TaskPurpose::kCandidateFamilyTagWrite ||
      task.purpose == TaskPurpose::kCandidateSourceRecordWrite ||
      task.purpose == TaskPurpose::kCandidateBucketWrite ||
      task.purpose == TaskPurpose::kCandidateDirectoryRead ||
      task.purpose == TaskPurpose::kCandidateDirectoryWrite ||
      task.purpose == TaskPurpose::kCandidateBitmapRead ||
      task.purpose == TaskPurpose::kCandidateBitmapWrite ||
      task.purpose == TaskPurpose::kCandidateScratchWrite ||
      task.purpose == TaskPurpose::kCandidateListRead ||
      task.purpose == TaskPurpose::kCandidateListWrite) {
    return config_.candidate_memory_request_window;
  }
  return config_.memory_request_window;
}

void SpineL0Maintenance::update_memory_concurrency_counters(
    const FixedAxiPort *issued_port) {
  const auto target_task = [](const MemoryTask &task) {
    return task.purpose == TaskPurpose::kTargetMetadataOccupied ||
           task.purpose == TaskPurpose::kTargetMetadataEdgeCount;
  };
  const auto hot_bitmap_task = [](const MemoryTask &task) {
    return task.purpose == TaskPurpose::kScanHotBitmap ||
           task.purpose == TaskPurpose::kCarryNewBatchHotBitmap;
  };
  const auto result_task = [](const MemoryTask &task) {
    return task.purpose == TaskPurpose::kResultColdEdgeCount ||
           task.purpose == TaskPurpose::kResultHotEdgeCount;
  };
  const std::size_t on_port = inflight_memory_tasks_for_port(issued_port);
  const std::size_t target_on_port = static_cast<std::size_t>(std::count_if(
      inflight_tasks_.begin(), inflight_tasks_.end(), [&](const auto &entry) {
        return entry.second.port == issued_port && target_task(entry.second);
      }));
  const std::size_t hot_bitmap_on_port = static_cast<std::size_t>(std::count_if(
      inflight_tasks_.begin(), inflight_tasks_.end(), [&](const auto &entry) {
        return entry.second.port == issued_port &&
               hot_bitmap_task(entry.second);
      }));
  const std::size_t result_on_port = static_cast<std::size_t>(std::count_if(
      inflight_tasks_.begin(), inflight_tasks_.end(), [&](const auto &entry) {
        return entry.second.port == issued_port && result_task(entry.second);
      }));
  const std::size_t default_window_on_port =
      on_port - target_on_port - hot_bitmap_on_port - result_on_port;
  counters_.max_memory_requests_inflight_per_port =
      std::max(counters_.max_memory_requests_inflight_per_port, on_port);
  counters_.max_non_target_memory_requests_inflight_per_port =
      std::max(counters_.max_non_target_memory_requests_inflight_per_port,
               default_window_on_port);
  counters_.target_selector_max_inflight =
      std::max(counters_.target_selector_max_inflight, target_on_port);
  counters_.hot_bitmap_max_inflight =
      std::max(counters_.hot_bitmap_max_inflight, hot_bitmap_on_port);
  counters_.result_metadata_max_inflight =
      std::max(counters_.result_metadata_max_inflight, result_on_port);
  counters_.max_active_memory_ports =
      std::max(counters_.max_active_memory_ports, active_memory_ports());
}

void SpineL0Maintenance::stage_memory_issues() {
  std::vector<FixedAxiPort *> visited_ports;
  bool window_stall = false;
  bool dependency_stall = false;
  bool fifo_stall = false;
  for (std::size_t index = 0; index < tasks_.size(); ++index) {
    const MemoryTask &task = tasks_[index];
    if (std::find(visited_ports.begin(), visited_ports.end(), task.port) !=
        visited_ports.end()) {
      continue;
    }
    visited_ports.push_back(task.port);
    if (inflight_memory_tasks_for_port(task.port) >=
        memory_request_window_for(task)) {
      window_stall = true;
      continue;
    }
    if (memory_task_conflicts(task)) {
      dependency_stall = true;
      continue;
    }
    const std::uint64_t transaction_id =
        next_transaction_id_ + staged_memory_issues_.size();
    if (task.port->requests().try_push(AxiRequest{
            .transaction_id = transaction_id,
            .operation = task.operation,
            .address = task.address,
            .bytes = task.bytes,
            .stream_read_beats = task.stream_sorted_scan,
            .write_data = task.write_data,
        })) {
      staged_memory_issues_.push_back(
          StagedMemoryIssue{index, transaction_id});
    } else {
      fifo_stall = true;
    }
  }
  counters_.memory_window_stall_cycles += window_stall ? 1 : 0;
  counters_.memory_dependency_stall_cycles += dependency_stall ? 1 : 0;
  counters_.memory_request_fifo_stall_cycles += fifo_stall ? 1 : 0;
  counters_.max_memory_requests_issued_per_cycle =
      std::max(counters_.max_memory_requests_issued_per_cycle,
               staged_memory_issues_.size());
  if (staged_memory_issues_.size() > 1) {
    ++counters_.multi_port_issue_cycles;
  }
}

bool SpineL0Maintenance::stage_memory_completion() {
  struct Candidate {
    std::uint64_t transaction_id{};
    FixedAxiPort *port{};
  };
  std::vector<Candidate> candidates;
  for (const auto &[transaction_id, task] : inflight_tasks_) {
    const AxiResponse *response = task.port->responses().front();
    if (task.streamed_read_beats_received < task.streamed_read_beats_expected) {
      continue;
    }
    if (response != nullptr && response->transaction_id == transaction_id &&
        std::none_of(candidates.begin(), candidates.end(),
                     [&](const Candidate &candidate) {
                       return candidate.port == task.port;
                     })) {
      candidates.push_back(Candidate{transaction_id, task.port});
    }
  }
  std::sort(candidates.begin(), candidates.end(),
            [](const Candidate &left, const Candidate &right) {
              return left.transaction_id < right.transaction_id;
            });
  for (const Candidate &candidate : candidates) {
    AxiResponse response;
    if (!candidate.port->responses().try_pop(response)) {
      throw std::logic_error("failed to stage ready Spine AXI response");
    }
    staged_responses_.push_back(std::move(response));
  }
  counters_.max_memory_responses_completed_per_cycle =
      std::max(counters_.max_memory_responses_completed_per_cycle,
               staged_responses_.size());
  if (staged_responses_.size() > 1) {
    ++counters_.multi_port_response_cycles;
  }
  return !staged_responses_.empty();
}

bool SpineL0Maintenance::stage_read_beat() {
  if (!ports_.sorted_edges->read_beat_stream_enabled()) {
    return false;
  }
  const AxiReadBeatResponse *beat = ports_.sorted_edges->read_beats().front();
  if (beat == nullptr) {
    return false;
  }
  const auto found = inflight_tasks_.find(beat->transaction_id);
  if (found == inflight_tasks_.end() ||
      found->second.port != ports_.sorted_edges ||
      found->second.operation != MemoryOperation::kRead) {
    throw std::logic_error("Spine read beat has no matching sorted-edge task");
  }
  if (found->second.stream_sorted_scan &&
      scan_response_edges_.size() >=
          config_.maintenance_scan_response_capacity) {
    ++counters_.sorted_scan_reorder_full_stall_cycles;
    return false;
  }
  return ports_.sorted_edges->read_beats().try_pop(staged_read_beat_response_);
}

void SpineL0Maintenance::enqueue_task(
    FixedAxiPort &port, MemoryOperation operation, std::uint64_t address,
    std::uint64_t bytes, TaskClass task_class,
    std::vector<std::uint8_t> write_data,
    std::vector<std::uint32_t> carry_edge_sources, bool stream_sorted_scan,
    TaskPurpose purpose, std::uint32_t source, std::size_t carry_stream,
    std::size_t carry_edge_index, std::size_t metadata_family,
    std::size_t metadata_level, std::size_t candidate_index) {
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
      .purpose = purpose,
      .source = source,
      .carry_stream = carry_stream,
      .carry_edge_index = carry_edge_index,
      .metadata_family = metadata_family,
      .metadata_level = metadata_level,
      .candidate_index = candidate_index,
      .stream_sorted_scan = stream_sorted_scan,
      .streamed_read_beats_expected =
          stream_sorted_scan
              ? static_cast<std::size_t>(
                    (bytes + port.master().config().data_width_bytes - 1) /
                    port.master().config().data_width_bytes)
              : 0,
      .streamed_read_beats_received = 0,
  });
  if (level_writer_.initialized && level_writer_.l0_mode &&
      (purpose == TaskPurpose::kLevelWriterGraphWrite ||
       purpose == TaskPurpose::kLevelWriterMetadataWrite)) {
    const std::size_t queued = static_cast<std::size_t>(std::count_if(
        tasks_.begin(), tasks_.end(), [](const MemoryTask &task) {
          return task.purpose == TaskPurpose::kLevelWriterGraphWrite ||
                 task.purpose == TaskPurpose::kLevelWriterMetadataWrite;
        }));
    counters_.l0_writer_max_pending_tasks =
        std::max(counters_.l0_writer_max_pending_tasks, queued);
    const std::size_t queued_on_port =
        queued_level_writer_tasks_for_port(&port);
    counters_.l0_writer_max_pending_tasks_per_port =
        std::max(counters_.l0_writer_max_pending_tasks_per_port,
                 queued_on_port);
    if (queued_on_port > port.requests().depth()) {
      ++counters_.l0_writer_validation_failures;
      throw std::logic_error("Spine L0 writer exceeded its finite issue queue");
    }
  }
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

void SpineL0Maintenance::begin_sorted_scan(Phase process_phase, ScanKind kind) {
  streaming_scan_ = ports_.sorted_edges->read_beat_stream_enabled();
  if (streaming_scan_ &&
      ports_.sorted_edges->master().config().data_width_bytes !=
          kSpineSortWordBytes) {
    throw std::logic_error(
        "streamed Spine sorted scans require one edge per AXI beat");
  }
  ++counters_.sorted_scan_passes;
  scan_kind_ = kind;
  scan_index_ = 0;
  scan_tail_remaining_ = 0;
  next_scan_consume_cycle_ = 0;
  scan_transaction_valid_ = false;
  scan_response_edges_.clear();
  scan_hot_results_.clear();
  scan_hot_requests_pending_.clear();
  edge_by_edge_scan_ = kind == ScanKind::kDirtyMark;
  if (kind != ScanKind::kCandidateBucketWrite) {
    scan_base_address_ = config_.sorted_edges_base;
  }
  scan_have_last_source_ = false;
  scan_last_source_ = 0;
  dirty_source_pending_ = false;
  if (edge_by_edge_scan_) {
    enqueue_dirty_mark_edge_read();
  } else if (!sorted_scan_edges_.empty()) {
    enqueue_task(*ports_.sorted_edges, MemoryOperation::kRead,
                 scan_base_address_,
                 sorted_scan_edges_.size() * kSpineSortWordBytes,
                 TaskClass::kSorted, {}, {}, streaming_scan_);
  }
  phase_ = process_phase;
}

bool SpineL0Maintenance::scan_process_phase() const noexcept {
  switch (phase_) {
  case Phase::kDirtyPreflightProcess:
  case Phase::kDirtyUpdateProcess:
  case Phase::kHotColdCountProcess:
  case Phase::kPrecountProcess:
  case Phase::kWriteProcess:
  case Phase::kCandidateClassifyProcess:
  case Phase::kCandidateDispatchProcess:
    return true;
  default:
    return false;
  }
}

std::size_t SpineL0Maintenance::scan_initiation_interval() const noexcept {
  return scan_kind_ == ScanKind::kL0Write ||
                 scan_kind_ == ScanKind::kCandidateBucketWrite
             ? config_.maintenance_l0_write_scan_ii
             : config_.maintenance_count_scan_ii;
}

std::size_t SpineL0Maintenance::scan_tail_cycles() const noexcept {
  switch (scan_kind_) {
  case ScanKind::kHotColdCount:
  case ScanKind::kFamilyPrecount:
    return config_.maintenance_count_scan_tail_cycles;
  case ScanKind::kL0Write:
  case ScanKind::kCandidateBucketWrite:
    return config_.maintenance_l0_write_scan_tail_cycles;
  case ScanKind::kDirtyValidate:
  case ScanKind::kDirtyMark:
  case ScanKind::kCandidateClassify:
  case ScanKind::kCandidateDispatch:
    return 0;
  }
  return 0;
}

bool SpineL0Maintenance::scan_requires_hot_bitmap() const noexcept {
  return metadata_hot_enabled_ && (scan_kind_ == ScanKind::kHotColdCount ||
                                   scan_kind_ == ScanKind::kFamilyPrecount ||
                                   scan_kind_ == ScanKind::kL0Write ||
                                   scan_kind_ == ScanKind::kCandidateClassify);
}

void SpineL0Maintenance::enqueue_scan_hot_bitmap_read(
    std::size_t index, std::uint32_t destination) {
  if (!scan_requires_hot_bitmap()) {
    return;
  }
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  const std::uint64_t word = destination >> 6;
  if (index >= sorted_scan_edges_.size() || word >= metadata.hot_bitmap_words ||
      scan_hot_results_.contains(index) ||
      !scan_hot_requests_pending_.insert(index).second) {
    ++counters_.hot_bitmap_validation_failures;
    throw std::logic_error("invalid Spine scan hot-bitmap request");
  }
  enqueue_task(*ports_.metadata, MemoryOperation::kRead,
               config_.metadata_base +
                   (metadata.hot_bitmap_base + word) * kMetadataWordBytes,
               kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
               TaskPurpose::kScanHotBitmap, destination, 0, index);
  ++counters_.hot_bitmap_reads;
  ++counters_.hot_bitmap_scan_reads;
}

void SpineL0Maintenance::enqueue_carry_hot_bitmap_read(
    std::size_t stream_index, const SpineEdgeRecord &edge) {
  if (!metadata_hot_enabled_ || stream_index >= carry_streams_.size()) {
    ++counters_.hot_bitmap_validation_failures;
    throw std::logic_error("invalid Spine carry hot-bitmap request");
  }
  CarryInputStream &stream = carry_streams_[stream_index];
  if (!stream.request_pending || stream.pending_hot_edge_valid) {
    ++counters_.hot_bitmap_validation_failures;
    throw std::logic_error("overlapping Spine carry hot-bitmap request");
  }
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  const std::uint64_t word = edge.dst >> 6;
  if (word >= metadata.hot_bitmap_words) {
    ++counters_.hot_bitmap_validation_failures;
    throw std::logic_error(
        "Spine carry hot-bitmap destination is out of range");
  }
  stream.pending_hot_edge = edge;
  stream.pending_hot_edge_valid = true;
  enqueue_task(*ports_.metadata, MemoryOperation::kRead,
               config_.metadata_base +
                   (metadata.hot_bitmap_base + word) * kMetadataWordBytes,
               kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
               TaskPurpose::kCarryNewBatchHotBitmap, edge.dst, stream_index);
  ++counters_.hot_bitmap_reads;
  ++counters_.hot_bitmap_carry_reads;
}

bool SpineL0Maintenance::scan_can_advance(const CycleContext &context) {
  if (scan_index_ == sorted_scan_edges_.size()) {
    if (scan_kind_ == ScanKind::kL0Write &&
        !l0_writer_has_queue_headroom()) {
      ++counters_.l0_writer_backpressure_stall_cycles;
      return false;
    }
    if (edge_by_edge_scan_ &&
        (dirty_source_pending_ || !tasks_.empty() ||
         !inflight_tasks_.empty() || staged_memory_completion_ ||
         staged_read_beat_completion_)) {
      ++counters_.sorted_scan_response_stall_cycles;
      return false;
    }
    return true;
  }
  if (context.domain_cycle < next_scan_consume_cycle_) {
    ++counters_.sorted_scan_ii_stall_cycles;
    return false;
  }
  if (scan_kind_ == ScanKind::kL0Write &&
      !l0_writer_has_queue_headroom()) {
    ++counters_.l0_writer_backpressure_stall_cycles;
    return false;
  }
  if (streaming_scan_ || edge_by_edge_scan_) {
    if (!scan_response_edges_.contains(scan_index_)) {
      ++counters_.sorted_scan_response_stall_cycles;
      return false;
    }
    if (scan_requires_hot_bitmap() &&
        !scan_hot_results_.contains(scan_index_)) {
      ++counters_.hot_bitmap_scan_wait_cycles;
      return false;
    }
    return true;
  }
  if (scan_requires_hot_bitmap()) {
    if (!scan_hot_results_.contains(scan_index_)) {
      ++counters_.hot_bitmap_scan_wait_cycles;
      return false;
    }
    return true;
  }
  if (!tasks_.empty() || !inflight_tasks_.empty() ||
      staged_memory_completion_) {
    ++counters_.sorted_scan_response_stall_cycles;
    return false;
  }
  return true;
}

bool SpineL0Maintenance::process_scan_edge(const CycleContext &context) {
  if (scan_index_ == sorted_scan_edges_.size()) {
    if (scan_tail_remaining_ != 0) {
      --scan_tail_remaining_;
      ++counters_.sorted_scan_tail_cycles;
      return false;
    }
    return true;
  }
  if (streaming_scan_ || edge_by_edge_scan_) {
    const auto found = scan_response_edges_.find(scan_index_);
    if (found == scan_response_edges_.end()) {
      throw std::logic_error("Spine advanced without the next sorted beat");
    }
    sorted_scan_edges_[scan_index_] = found->second;
    scan_response_edges_.erase(found);
  }
  ++counters_.sorted_edge_visits;
  switch (scan_kind_) {
  case ScanKind::kDirtyValidate:
    ++counters_.dirty_validate_edge_visits;
    if (!scan_have_last_source_ ||
        sorted_scan_edges_[scan_index_].src != scan_last_source_) {
      ++counters_.unique_sources;
      scan_last_source_ = sorted_scan_edges_[scan_index_].src;
      scan_have_last_source_ = true;
    } else {
      ++counters_.dirty_duplicates_suppressed;
    }
    break;
  case ScanKind::kDirtyMark:
    ++counters_.dirty_mark_edge_visits;
    if (!scan_have_last_source_ ||
        sorted_scan_edges_[scan_index_].src != scan_last_source_) {
      scan_last_source_ = sorted_scan_edges_[scan_index_].src;
      scan_have_last_source_ = true;
      enqueue_dirty_bitmap_read(scan_last_source_);
    }
    break;
  case ScanKind::kHotColdCount:
    ++counters_.hot_cold_count_edge_visits;
    break;
  case ScanKind::kFamilyPrecount:
    ++counters_.family_precount_edge_visits;
    break;
  case ScanKind::kL0Write:
    ++counters_.l0_write_edge_visits;
    break;
  case ScanKind::kCandidateClassify: {
    const SpineEdgeRecord &edge = sorted_scan_edges_[scan_index_];
    const bool hot = edge_is_hot(edge.dst);
    const std::size_t family =
        hot ? config_.partitions + spine_hot_shard(edge.dst)
            : family_for(edge.dst);
    if (family >= kSpineFamilyCount) {
      throw std::logic_error("candidate-10 classifier produced bad family");
    }
    candidate_family_tags_[scan_index_] = static_cast<std::uint8_t>(family);
    ++candidate_family_begin_[family + 1];
    if (hot) {
      ++counters_.hot_input_edges;
    } else {
      ++counters_.cold_input_edges;
    }
    ++counters_.candidate_classify_edge_visits;
    if (candidate_have_source_ && edge.src != candidate_current_source_) {
      CandidateSourceRecord record{candidate_current_source_,
                                   candidate_current_source_mask_};
      candidate_source_records_.push_back(record);
      candidate_classify_block_records_.push_back(record);
      candidate_current_source_mask_ = 0;
    }
    candidate_current_source_ = edge.src;
    candidate_current_source_mask_ |= std::uint32_t{1} << family;
    candidate_have_source_ = true;
    const std::uint32_t term = candidate_tag_hash_term(
        edge.src, static_cast<std::uint32_t>(family),
        static_cast<std::uint32_t>(scan_index_));
    candidate_classified_tag_hash_ =
        std::rotl(candidate_classified_tag_hash_, 5) + term;
    break;
  }
  case ScanKind::kCandidateDispatch: {
    const SpineEdgeRecord &edge = sorted_scan_edges_[scan_index_];
    const std::size_t family = candidate_family_tags_.at(scan_index_);
    const std::uint32_t bucket_index = candidate_family_cursor_.at(family);
    if (bucket_index < candidate_family_begin_[family] ||
        bucket_index >= candidate_family_begin_[family + 1] ||
        bucket_index >= config_.max_sort_edges) {
      counters_.dispatch_status = 2;
      ++counters_.dispatch_cursor_mismatches;
      break;
    }
    std::vector<std::uint8_t> payload = encode_spine_sort_edge(edge);
    enqueue_task(*ports_.sorted_edges, MemoryOperation::kWrite,
                 config_.persistent_family_bucket_base +
                     bucket_index * kSpineSortWordBytes,
                 kSpineSortWordBytes, TaskClass::kPersistent,
                 std::move(payload), {}, false,
                 TaskPurpose::kCandidateBucketWrite, edge.src, 0, 0, 0, 0,
                 bucket_index);
    candidate_family_buckets_[family].push_back(edge);
    ++candidate_family_cursor_[family];
    ++counters_.dispatch_input_reads;
    ++counters_.dispatch_bucket_writes;
    const std::uint32_t tag_term = candidate_tag_hash_term(
        edge.src, static_cast<std::uint32_t>(family),
        static_cast<std::uint32_t>(scan_index_));
    candidate_dispatched_tag_hash_ =
        std::rotl(candidate_dispatched_tag_hash_, 5) + tag_term;
    const std::uint32_t hash_term = candidate_dispatch_hash_term(
        edge, static_cast<std::uint32_t>(family), bucket_index);
    counters_.dispatch_hash_sum += hash_term;
    counters_.dispatch_hash_xor ^= hash_term;
    break;
  }
  case ScanKind::kCandidateBucketWrite:
    ++counters_.l0_write_edge_visits;
    break;
  }
  if (scan_requires_hot_bitmap()) {
    if (scan_hot_results_.erase(scan_index_) != 1) {
      ++counters_.hot_bitmap_validation_failures;
      throw std::logic_error(
          "Spine scan consumed an edge without hot-bitmap payload");
    }
  }
  ++scan_index_;
  if (scan_kind_ == ScanKind::kCandidateClassify &&
      (scan_index_ % config_.candidate_classify_block_edges == 0 ||
       scan_index_ == sorted_scan_edges_.size())) {
    if (scan_index_ == sorted_scan_edges_.size() && candidate_have_source_) {
      CandidateSourceRecord record{candidate_current_source_,
                                   candidate_current_source_mask_};
      candidate_source_records_.push_back(record);
      candidate_classify_block_records_.push_back(record);
      candidate_have_source_ = false;
    }
    candidate_block_edges_ = scan_index_ - candidate_block_begin_;
    candidate_reduce_cycles_remaining_ = candidate_block_edges_;
    ++counters_.candidate_classify_blocks;
    phase_ = Phase::kCandidateClassifyReduce;
  }
  next_scan_consume_cycle_ = context.domain_cycle + scan_initiation_interval();
  if (edge_by_edge_scan_ && !dirty_source_pending_ &&
      scan_index_ < sorted_scan_edges_.size()) {
    enqueue_dirty_mark_edge_read();
  }
  if (scan_index_ == sorted_scan_edges_.size()) {
    scan_tail_remaining_ = scan_tail_cycles();
  }
  return false;
}

void SpineL0Maintenance::consume_read_beat(const AxiReadBeatResponse &beat) {
  const auto task = inflight_tasks_.find(beat.transaction_id);
  if (task == inflight_tasks_.end()) {
    throw std::logic_error("Spine consumed an unknown AXI read beat");
  }
  if (task->second.streamed_read_beats_received >=
      task->second.streamed_read_beats_expected) {
    throw std::logic_error("too many Spine AXI read beats for one task");
  }
  ++task->second.streamed_read_beats_received;
  if (!task->second.stream_sorted_scan) {
    return;
  }
  if (!scan_transaction_valid_ || beat.transaction_id != scan_transaction_id_ ||
      beat.parent_offset % kSpineSortWordBytes != 0 ||
      beat.read_data.size() != kSpineSortWordBytes) {
    throw std::logic_error("invalid streamed Spine sorted-edge beat");
  }
  if (beat.address < scan_base_address_) {
    throw std::logic_error("streamed Spine sorted-edge address underflow");
  }
  const std::size_t index = static_cast<std::size_t>(
      (edge_by_edge_scan_ ? beat.address - scan_base_address_
                          : beat.parent_offset) /
      kSpineSortWordBytes);
  const SpineEdgeRecord edge = decode_spine_sort_edge(beat.read_data);
  if (index >= sorted_scan_edges_.size() ||
      !scan_response_edges_.emplace(index, edge).second) {
    throw std::logic_error("duplicate or out-of-range Spine sorted-edge beat");
  }
  enqueue_scan_hot_bitmap_read(index, edge.dst);
  ++counters_.sorted_read_beats_received;
  counters_.sorted_payload_read_bytes += beat.read_data.size();
  counters_.max_sorted_scan_buffered_edges = std::max(
      counters_.max_sorted_scan_buffered_edges, scan_response_edges_.size());
}

void SpineL0Maintenance::consume_memory_response(const MemoryTask &task,
                                                 const AxiResponse &response) {
  const bool control_response = task.purpose == TaskPurpose::kMetadataControl;
  const bool hot_bitmap_response =
      task.purpose == TaskPurpose::kScanHotBitmap ||
      task.purpose == TaskPurpose::kCarryNewBatchHotBitmap;
  const bool target_response =
      task.purpose == TaskPurpose::kTargetMetadataOccupied ||
      task.purpose == TaskPurpose::kTargetMetadataEdgeCount;
  const bool result_metadata_response =
      task.purpose == TaskPurpose::kResultColdEdgeCount ||
      task.purpose == TaskPurpose::kResultHotEdgeCount;
  const bool result_write_response =
      task.purpose == TaskPurpose::kMaintenanceResultWrite;
  const bool epoch_read_response =
      task.purpose == TaskPurpose::kLevelWriterSliceEpochRead;
  const bool epoch_clear_response =
      task.purpose == TaskPurpose::kLevelWriterEpochClear;
  const bool epoch_retire_response =
      task.purpose == TaskPurpose::kEpochRetireWrite;
  const bool carry_response =
      task.purpose == TaskPurpose::kCarryNewBatchRead ||
      task.purpose == TaskPurpose::kCarryNewBatchHotBitmap ||
      task.purpose == TaskPurpose::kCarryCursorSliceMetadata ||
      task.purpose == TaskPurpose::kCarryCursorSliceEpoch ||
      task.purpose == TaskPurpose::kCarryCursorPageCount ||
      task.purpose == TaskPurpose::kCarryCursorPageList ||
      task.purpose == TaskPurpose::kCarryCursorPageEpoch ||
      task.purpose == TaskPurpose::kCarryCursorPageBase ||
      task.purpose == TaskPurpose::kCarryCursorBitmap ||
      task.purpose == TaskPurpose::kCarryCursorRowOffsets ||
      task.purpose == TaskPurpose::kCarryLevelEdgeRead ||
      task.purpose == TaskPurpose::kLevelWriterGraphWrite ||
      task.purpose == TaskPurpose::kLevelWriterMetadataWrite;
  const bool candidate_response =
      task.purpose == TaskPurpose::kCandidateFamilyTagWrite ||
      task.purpose == TaskPurpose::kCandidateSourceRecordWrite ||
      task.purpose == TaskPurpose::kCandidateBucketWrite ||
      task.purpose == TaskPurpose::kCandidatePublicationSourceRead ||
      task.purpose == TaskPurpose::kCandidateDirectoryRead ||
      task.purpose == TaskPurpose::kCandidateDirectoryWrite ||
      task.purpose == TaskPurpose::kCandidateBitmapRead ||
      task.purpose == TaskPurpose::kCandidateBitmapWrite ||
      task.purpose == TaskPurpose::kCandidateScratchWrite ||
      task.purpose == TaskPurpose::kCandidateListSourceRead ||
      task.purpose == TaskPurpose::kCandidateListRead ||
      task.purpose == TaskPurpose::kCandidateListWrite;
  if (task.operation == MemoryOperation::kWrite) {
    if (!response.read_data.empty()) {
      throw std::logic_error(
          "Spine maintenance write response carried payload");
    }
    if (result_write_response) {
      ++counters_.result_write_responses;
    } else if (epoch_clear_response) {
      ++counters_.epoch_clear_write_responses;
    } else if (epoch_retire_response) {
      ++counters_.epoch_retire_write_responses;
    } else if (control_response || hot_bitmap_response) {
      ++counters_.hot_bitmap_validation_failures;
      throw std::logic_error("Spine hot-metadata read path issued a write");
    } else if (target_response) {
      ++counters_.target_selector_validation_failures;
      throw std::logic_error("Spine target-selector read path issued a write");
    } else if (result_metadata_response) {
      ++counters_.result_validation_failures;
      throw std::logic_error("Spine result metadata read path issued a write");
    } else if (carry_response) {
      consume_carry_memory_response(task, response);
    } else if (candidate_response) {
      consume_candidate_memory_response(task, response);
    } else if (task.purpose != TaskPurpose::kGeneric) {
      consume_dirty_memory_response(task, response);
    }
    return;
  }
  if (response.read_data.size() != task.bytes) {
    throw std::logic_error("Spine maintenance read response payload mismatch");
  }
  if (control_response) {
    consume_metadata_control_response(response);
  } else if (hot_bitmap_response) {
    consume_hot_bitmap_response(task, response);
  } else if (target_response) {
    consume_target_selector_response(task, response);
  } else if (result_metadata_response) {
    consume_result_metadata_response(task, response);
  } else if (epoch_read_response) {
    consume_active_writer_epoch_response(task, response);
  } else if (carry_response) {
    consume_carry_memory_response(task, response);
  } else if (candidate_response) {
    consume_candidate_memory_response(task, response);
  } else if (task.purpose != TaskPurpose::kGeneric) {
    consume_dirty_memory_response(task, response);
  }
  if (task.stream_sorted_scan) {
    scan_transaction_valid_ = false;
  }
  if (task.task_class == TaskClass::kSorted) {
    if (!task.stream_sorted_scan && task.purpose == TaskPurpose::kGeneric) {
      sorted_scan_edges_ = decode_spine_sort_edges(response.read_data);
      counters_.sorted_payload_read_bytes += response.read_data.size();
      if (scan_requires_hot_bitmap()) {
        for (std::size_t index = 0; index < sorted_scan_edges_.size();
             ++index) {
          enqueue_scan_hot_bitmap_read(index, sorted_scan_edges_[index].dst);
        }
      }
    }
  }
}

std::size_t SpineL0Maintenance::family_for(std::uint32_t dst) const {
  return std::min<std::size_t>(dst / config_.vertex_partition_size,
                               config_.partitions - 1);
}

bool SpineL0Maintenance::edge_is_hot(std::uint32_t dst) const {
  if (!metadata_hot_enabled_) {
    return false;
  }
  const auto found = hot_classification_by_vertex_.find(dst);
  if (found == hot_classification_by_vertex_.end()) {
    throw std::logic_error(
        "Spine hot classification bypassed its HBM bitmap response");
  }
  return found->second;
}

std::vector<SpineEdgeRecord> SpineL0Maintenance::coalesce_family(
    bool hot, std::size_t family) const {
  if (config_.maintenance_architecture ==
      SpineMaintenanceArchitecture::kCandidate10OnePass) {
    const std::size_t logical_family = hot ? config_.partitions + family : family;
    return coalesce_records(candidate_family_buckets_.at(logical_family));
  }
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
  const std::size_t family_base = hot ? config_.partitions : 0;
  for (std::size_t level = 0; level < config_.levels; ++level) {
    bool occupied = false;
    for (std::size_t family = 0; family < config_.partitions; ++family) {
      const std::size_t logical_family = family_base + family;
      occupied = occupied || target_occupied_[logical_family][level] != 0 ||
                 target_edge_counts_[logical_family][level] != 0;
    }
    if (!occupied) {
      return level;
    }
  }
  return config_.levels;
}

void SpineL0Maintenance::initialize_target_selector(
    bool hot, const CycleContext &context) {
  target_scan_hot_ = hot;
  target_scan_level_ = 0;
  target_scan_candidate_ = -1;
  target_scan_start_cycle_ = context.domain_cycle + (hot ? 1 : 0);
  const std::uint64_t minimum =
      hot ? config_.maintenance_hot_target_select_min_cycles
          : config_.maintenance_cold_target_select_min_cycles;
  target_scan_min_finish_cycle_ = target_scan_start_cycle_ + minimum - 1;
  const std::size_t family_base = hot ? config_.partitions : 0;
  for (std::size_t family = 0; family < config_.partitions; ++family) {
    target_edge_counts_[family_base + family].fill(0);
    target_occupied_[family_base + family].fill(0);
    target_metadata_ready_[family_base + family].fill(0);
  }
  ++counters_.target_selector_invocations;
}

void SpineL0Maintenance::enqueue_target_selector_level() {
  if (target_scan_level_ >= config_.levels) {
    ++counters_.target_selector_validation_failures;
    throw std::logic_error("Spine target selector level is out of range");
  }
  const std::size_t family_base = target_scan_hot_ ? config_.partitions : 0;
  for (std::size_t family = 0; family < config_.partitions; ++family) {
    const std::size_t logical_family = family_base + family;
    const std::uint64_t slice =
        logical_family * config_.levels + target_scan_level_;
    const std::uint64_t base_word = slice * kMetadataWordsPerSlice;
    enqueue_task(
        *ports_.metadata, MemoryOperation::kRead,
        config_.metadata_base +
            (base_word + kMetadataOccupiedWord) * kMetadataWordBytes,
        kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
        TaskPurpose::kTargetMetadataOccupied, 0, 0, 0, logical_family,
        target_scan_level_);
    enqueue_task(
        *ports_.metadata, MemoryOperation::kRead,
        config_.metadata_base +
            (base_word + kMetadataEdgeCountWord) * kMetadataWordBytes,
        kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
        TaskPurpose::kTargetMetadataEdgeCount, 0, 0, 0, logical_family,
        target_scan_level_);
  }
  counters_.target_selector_family_iterations += config_.partitions;
  counters_.target_selector_metadata_reads += config_.partitions * 2;
}

void SpineL0Maintenance::consume_target_selector_response(
    const MemoryTask &task, const AxiResponse &response) {
  if (task.operation != MemoryOperation::kRead ||
      response.read_data.size() != kMetadataWordBytes ||
      task.metadata_family >= kSpineFamilyCount ||
      task.metadata_level >= config_.levels) {
    ++counters_.target_selector_validation_failures;
    throw std::logic_error("invalid Spine target-selector metadata response");
  }
  const std::uint8_t ready_bit =
      task.purpose == TaskPurpose::kTargetMetadataOccupied ? 1U : 2U;
  std::uint8_t &ready =
      target_metadata_ready_[task.metadata_family][task.metadata_level];
  if ((ready & ready_bit) != 0) {
    ++counters_.target_selector_validation_failures;
    throw std::logic_error("duplicate Spine target-selector metadata response");
  }
  const std::uint64_t value = read_u64_le(response.read_data, 0);
  if (task.purpose == TaskPurpose::kTargetMetadataOccupied) {
    target_occupied_[task.metadata_family][task.metadata_level] = value;
  } else {
    target_edge_counts_[task.metadata_family][task.metadata_level] = value;
  }
  ready |= ready_bit;
  ++counters_.target_selector_responses;
  counters_.target_selector_payload_read_bytes += response.read_data.size();
}

void SpineL0Maintenance::consume_metadata_control_response(
    const AxiResponse &response) {
  if (metadata_control_ready_ ||
      response.read_data.size() != kMetadataWordBytes) {
    ++counters_.hot_bitmap_validation_failures;
    throw std::logic_error("invalid Spine metadata control response");
  }
  const std::uint64_t control = read_u64_le(response.read_data, 0);
  if (!spine_metadata_control_valid(control,
                                    config_.maintenance_architecture)) {
    ++counters_.hot_bitmap_validation_failures;
    throw std::logic_error("invalid Spine metadata control payload");
  }
  metadata_control_ready_ = true;
  metadata_hot_enabled_ = (control & 1U) != 0;
  state_.hot_enabled = metadata_hot_enabled_;
  counters_.hot_enabled = metadata_hot_enabled_;
  ++counters_.metadata_control_reads;
  counters_.metadata_control_payload_read_bytes += response.read_data.size();
}

void SpineL0Maintenance::consume_hot_bitmap_response(
    const MemoryTask &task, const AxiResponse &response) {
  if (!metadata_control_ready_ || !metadata_hot_enabled_ ||
      task.operation != MemoryOperation::kRead ||
      response.read_data.size() != kMetadataWordBytes ||
      task.source >= config_.max_vertices) {
    ++counters_.hot_bitmap_validation_failures;
    throw std::logic_error("invalid Spine hot-bitmap response");
  }
  const std::uint64_t bits = read_u64_le(response.read_data, 0);
  const bool hot = (bits & (std::uint64_t{1} << (task.source & 63U))) != 0;
  hot_classification_by_vertex_[task.source] = hot;
  ++counters_.hot_bitmap_responses;
  counters_.hot_bitmap_payload_read_bytes += response.read_data.size();

  if (task.purpose == TaskPurpose::kScanHotBitmap) {
    if (task.carry_edge_index >= sorted_scan_edges_.size() ||
        scan_hot_requests_pending_.erase(task.carry_edge_index) != 1 ||
        !scan_hot_results_.emplace(task.carry_edge_index, hot).second) {
      ++counters_.hot_bitmap_validation_failures;
      throw std::logic_error("invalid Spine scan hot-bitmap retirement");
    }
    return;
  }
  if (task.purpose != TaskPurpose::kCarryNewBatchHotBitmap ||
      task.carry_stream >= carry_streams_.size()) {
    ++counters_.hot_bitmap_validation_failures;
    throw std::logic_error("unknown Spine hot-bitmap response purpose");
  }
  CarryInputStream &stream = carry_streams_[task.carry_stream];
  if (!stream.new_batch || !stream.request_pending ||
      !stream.pending_hot_edge_valid ||
      stream.pending_hot_edge.dst != task.source) {
    ++counters_.hot_bitmap_validation_failures;
    throw std::logic_error("invalid Spine carry hot-bitmap retirement");
  }
  const SpineEdgeRecord edge = stream.pending_hot_edge;
  stream.pending_hot_edge_valid = false;
  stream.request_pending = false;
  const FamilyWriteTask &active = family_write_tasks_[active_family_index_];
  const std::size_t family =
      hot ? spine_hot_shard(edge.dst) : family_for(edge.dst);
  if (hot == active.hot && family == active.family) {
    stream.buffered.push_back(edge);
  } else {
    enqueue_carry_stream_refill(task.carry_stream);
  }
  std::size_t buffered = 0;
  for (const CarryInputStream &candidate : carry_streams_) {
    buffered += candidate.buffered.size();
  }
  counters_.carry_max_buffered_heads =
      std::max(counters_.carry_max_buffered_heads, buffered);
}

void SpineL0Maintenance::enqueue_result_metadata_reads() {
  result_cold_edge_counts_.fill(0);
  result_hot_edge_counts_.fill(0);
  result_cold_edge_counts_ready_.fill(false);
  result_hot_edge_counts_ready_.fill(false);
  if (logical_overflow_) {
    return;
  }
  if (counters_.target_level < 0 ||
      (metadata_hot_enabled_ && counters_.hot_target_level < 0)) {
    begin_logical_overflow("Spine result has no committed target",
                           SpineDirtyStatus::kInvalidState);
    return;
  }
  const auto enqueue_family_range = [&](bool hot, std::size_t level) {
    const std::size_t family_base = hot ? config_.partitions : 0;
    const TaskPurpose purpose = hot ? TaskPurpose::kResultHotEdgeCount
                                    : TaskPurpose::kResultColdEdgeCount;
    for (std::size_t family = 0; family < config_.partitions; ++family) {
      const std::size_t logical_family = family_base + family;
      const std::uint64_t slice =
          logical_family * config_.levels + level;
      enqueue_task(
          *ports_.metadata, MemoryOperation::kRead,
          config_.metadata_base +
              (slice * kMetadataWordsPerSlice + kMetadataEdgeCountWord) *
                  kMetadataWordBytes,
          kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false, purpose, 0,
          0, 0, logical_family, level);
      ++counters_.result_metadata_reads;
    }
  };
  enqueue_family_range(false,
                       static_cast<std::size_t>(counters_.target_level));
  if (metadata_hot_enabled_) {
    enqueue_family_range(
        true, static_cast<std::size_t>(counters_.hot_target_level));
  }
}

void SpineL0Maintenance::consume_result_metadata_response(
    const MemoryTask &task, const AxiResponse &response) {
  const bool hot = task.purpose == TaskPurpose::kResultHotEdgeCount;
  const std::size_t family_base = hot ? config_.partitions : 0;
  if ((task.purpose != TaskPurpose::kResultColdEdgeCount && !hot) ||
      task.operation != MemoryOperation::kRead ||
      response.read_data.size() != kMetadataWordBytes ||
      task.metadata_family < family_base ||
      task.metadata_family >= family_base + config_.partitions) {
    ++counters_.result_validation_failures;
    throw std::logic_error("invalid Spine result metadata response");
  }
  const std::size_t family = task.metadata_family - family_base;
  auto &counts = hot ? result_hot_edge_counts_ : result_cold_edge_counts_;
  auto &ready = hot ? result_hot_edge_counts_ready_
                    : result_cold_edge_counts_ready_;
  if (ready[family]) {
    ++counters_.result_validation_failures;
    throw std::logic_error("duplicate Spine result metadata response");
  }
  counts[family] = read_u64_le(response.read_data, 0);
  ready[family] = true;
  ++counters_.result_metadata_responses;
  counters_.result_metadata_payload_read_bytes += response.read_data.size();
}

SpineMaintenanceResult SpineL0Maintenance::build_maintenance_result() const {
  const auto as_i32 = [](std::uint64_t value) {
    return std::bit_cast<std::int32_t>(static_cast<std::uint32_t>(value));
  };
  SpineMaintenanceResult result;
  result.words[SpineMaintenanceResult::kInputEdges] =
      as_i32(workload_.edges.size());
  result.words[SpineMaintenanceResult::kOverflow] =
      logical_overflow_ ? 1 : 0;
  result.words[SpineMaintenanceResult::kLevels] =
      static_cast<std::int32_t>(config_.levels);
  result.words[SpineMaintenanceResult::kPartitions] =
      static_cast<std::int32_t>(config_.partitions);
  result.words[SpineMaintenanceResult::kMaxSort] =
      as_i32(config_.max_sort_edges);
  result.words[SpineMaintenanceResult::kTargetLevel] =
      logical_overflow_ ? -1 : counters_.target_level;
  result.words[SpineMaintenanceResult::kConsumedLevelMask] =
      logical_overflow_ || counters_.target_level <= 0
          ? 0
          : static_cast<std::int32_t>((1U << counters_.target_level) - 1U);
  result.words[SpineMaintenanceResult::kPath] = static_cast<std::int32_t>(
      logical_overflow_
          ? SpineMaintenancePath::kOverflow
          : (counters_.target_level == 0 ? SpineMaintenancePath::kStoreL0
                                         : SpineMaintenancePath::kCascade));

  std::uint64_t persisted_edges = 0;
  std::int32_t nonempty_partitions = 0;
  if (!logical_overflow_) {
    for (std::size_t family = 0; family < config_.partitions; ++family) {
      if (!result_cold_edge_counts_ready_[family] ||
          (metadata_hot_enabled_ &&
           !result_hot_edge_counts_ready_[family])) {
        throw std::logic_error("incomplete Spine result metadata payload");
      }
      const std::uint64_t cold = result_cold_edge_counts_[family];
      if (cold > static_cast<std::uint64_t>(
                     std::numeric_limits<std::int32_t>::max())) {
        throw std::overflow_error("Spine result edge count exceeds int32");
      }
      result.words[SpineMaintenanceResult::kPartitionEdgeCountBase + family] =
          static_cast<std::int32_t>(cold);
      persisted_edges += cold;
      nonempty_partitions += cold != 0 ? 1 : 0;
      if (metadata_hot_enabled_) {
        persisted_edges += result_hot_edge_counts_[family];
      }
    }
  }
  result.words[SpineMaintenanceResult::kPersistedEdges] =
      as_i32(persisted_edges);
  result.words[SpineMaintenanceResult::kNonemptyPartitions] =
      nonempty_partitions;
  if (config_.maintenance_architecture ==
      SpineMaintenanceArchitecture::kCandidate10OnePass) {
    result.words[SpineMaintenanceResult::kDispatchStatus] =
        as_i32(counters_.dispatch_status);
    result.words[SpineMaintenanceResult::kDispatchInputReads] =
        as_i32(counters_.dispatch_input_reads);
    result.words[SpineMaintenanceResult::kDispatchBucketWrites] =
        as_i32(counters_.dispatch_bucket_writes);
    result.words[SpineMaintenanceResult::kDispatchHashSum] =
        as_i32(counters_.dispatch_hash_sum);
    result.words[SpineMaintenanceResult::kDispatchHashXor] =
        as_i32(counters_.dispatch_hash_xor);
    result.words[SpineMaintenanceResult::kFamilyDirectoryWordReads] =
        as_i32(counters_.family_directory_word_reads);
    result.words[SpineMaintenanceResult::kFamilyDirectoryWordWrites] =
        as_i32(counters_.family_directory_word_writes);
    result.words[SpineMaintenanceResult::kFamilyDirectoryBitsSet] =
        as_i32(counters_.family_directory_bits_set);
  }
  result.words[SpineMaintenanceResult::kEpochPartitionsWritten] =
      logical_overflow_ ? 0 : as_i32(counters_.active_families);
  result.words[SpineMaintenanceResult::kEpochPagesStamped] =
      as_i32(counters_.pages_stamped);
  result.words[SpineMaintenanceResult::kEpochFullClearFallbacks] =
      as_i32(counters_.epoch_full_clear_fallbacks);
  result.words[SpineMaintenanceResult::kEpochWrapEvents] =
      as_i32(counters_.epoch_wrap_events);
  result.words[SpineMaintenanceResult::kEpochCommitFailures] =
      as_i32(counters_.epoch_commit_failures);
  result.words[SpineMaintenanceResult::kHotEdges] =
      as_i32(counters_.hot_input_edges);
  result.words[SpineMaintenanceResult::kColdEdges] =
      as_i32(counters_.cold_input_edges);

  const auto write_carry = [&](std::size_t base,
                               const CarryResultCounters &carry) {
    const std::array<std::uint64_t, 9> values{
        carry.page_ids_written, carry.validation_failures,
        carry.pages_visited,    carry.bits_inspected,
        carry.rows_entered,     carry.payload_reads,
        carry.refill_stalls,    carry.merge_inputs,
        carry.outputs,
    };
    for (std::size_t counter = 0; counter < values.size(); ++counter) {
      result.words[base + counter * 2] = as_i32(values[counter]);
      result.words[base + counter * 2 + 1] =
          as_i32(values[counter] >> 32);
    }
  };
  write_carry(SpineMaintenanceResult::kCarryColdBase,
              carry_result_counters_[0]);
  write_carry(SpineMaintenanceResult::kCarryHotBase,
              carry_result_counters_[1]);

  const bool candidate =
      config_.maintenance_architecture ==
      SpineMaintenanceArchitecture::kCandidate10OnePass;
  result.words[SpineMaintenanceResult::kLayoutVersion] = candidate ? 6 : 3;
  result.words[SpineMaintenanceResult::kMetadataFormatVersion] =
      static_cast<std::int32_t>(candidate ? kCandidateMetadataVersion
                                          : kMetadataVersion);
  result.words[SpineMaintenanceResult::kDirtyMode] = 0;
  result.words[SpineMaintenanceResult::kDirtyStatus] =
      static_cast<std::int32_t>(dirty_status_);
  result.words[SpineMaintenanceResult::kDirtyCount] = as_i32(dirty_count_);
  result.words[SpineMaintenanceResult::kDirtyGeneration] =
      as_i32(dirty_generation_);
  result.words[SpineMaintenanceResult::kDirtyHashSumLow] =
      as_i32(dirty_hash_sum_);
  result.words[SpineMaintenanceResult::kDirtyHashSumHigh] =
      as_i32(dirty_hash_sum_ >> 32);
  result.words[SpineMaintenanceResult::kDirtyHashXorLow] =
      as_i32(dirty_hash_xor_);
  result.words[SpineMaintenanceResult::kDirtyHashXorHigh] =
      as_i32(dirty_hash_xor_ >> 32);
  result.words[SpineMaintenanceResult::kDirtyUniqueInputSources] =
      as_i32(counters_.unique_sources);
  result.words[SpineMaintenanceResult::kDirtyBitmapReads] =
      as_i32(counters_.dirty_bitmap_reads);
  result.words[SpineMaintenanceResult::kDirtyBitmapWrites] =
      as_i32(counters_.dirty_bitmap_writes);
  result.words[SpineMaintenanceResult::kDirtyListAppends] =
      as_i32(counters_.dirty_list_appends);
  result.words[SpineMaintenanceResult::kDirtyDuplicatesSuppressed] =
      as_i32(counters_.dirty_duplicates_suppressed);
  if (candidate) {
    const std::uint32_t publication_flags =
        (counters_.dirty_generation_advances != 0 ? 1U : 0U) |
        (static_cast<std::uint32_t>(
             counters_.publication_scratch_word_writes & 0x1ffffU)
         << 1) |
        (counters_.publication_fallback ? (1U << 18) : 0U) |
        (counters_.publication_empty_frontier_fast_path ? (1U << 19) : 0U);
    result.words[SpineMaintenanceResult::kDirtyGenerationAdvances] =
        as_i32(publication_flags);
    const std::uint32_t list_flags =
        static_cast<std::uint32_t>(
            counters_.publication_list_word_writes & 0xffffU) |
        (static_cast<std::uint32_t>(
             counters_.publication_list_word_reads & 0x3U)
         << 16) |
        (counters_.publication_complete ? (1U << 18) : 0U);
    result.words[SpineMaintenanceResult::kDirtyAux] = as_i32(list_flags);
  } else {
    result.words[SpineMaintenanceResult::kDirtyGenerationAdvances] =
        as_i32(counters_.dirty_generation_advances);
  }
  result.words[SpineMaintenanceResult::kDirtyConservativeSources] =
      logical_overflow_ ? as_i32(counters_.unique_sources) : 0;
  return result;
}

void SpineL0Maintenance::enqueue_maintenance_result() {
  std::vector<std::uint8_t> payload =
      encode_spine_maintenance_result(build_maintenance_result());
  const std::uint64_t bytes = payload.size();
  counters_.result_payload_write_bytes += bytes;
  enqueue_task(*ports_.result, MemoryOperation::kWrite, config_.result_base,
               bytes, TaskClass::kResult, std::move(payload), {},
               false, TaskPurpose::kMaintenanceResultWrite);
}

void SpineL0Maintenance::begin_logical_overflow(
    std::string failure, SpineDirtyStatus dirty_status) {
  if (!logical_overflow_) {
    ++counters_.logical_overflow_events;
  }
  logical_overflow_ = true;
  dirty_status_ = dirty_status;
  failure_ = std::move(failure);
  phase_ = Phase::kWriteResult;
}

void SpineL0Maintenance::enqueue_active_writer_epoch_read() {
  if (active_family_index_ >= family_write_tasks_.size()) {
    ++counters_.slice_epoch_validation_failures;
    throw std::logic_error("Spine epoch read has no active writer");
  }
  const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
  const std::size_t logical_family =
      task.hot ? config_.partitions + task.family : task.family;
  const std::uint64_t slice =
      logical_family * config_.levels + task.target;
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  active_writer_epoch_ready_ = false;
  active_writer_epoch_wrapped_ = false;
  enqueue_task(
      *ports_.metadata, MemoryOperation::kRead,
      config_.metadata_base +
          (metadata.slice_epoch_base + (slice >> 1)) * kMetadataWordBytes,
      kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
      TaskPurpose::kLevelWriterSliceEpochRead, 0, 0, 0, logical_family,
      task.target);
  ++counters_.slice_epoch_reads;
}

void SpineL0Maintenance::consume_active_writer_epoch_response(
    const MemoryTask &task, const AxiResponse &response) {
  if (task.operation != MemoryOperation::kRead ||
      response.read_data.size() != kMetadataWordBytes ||
      task.metadata_family >= kSpineFamilyCount ||
      task.metadata_level >= config_.levels || active_writer_epoch_ready_ ||
      active_family_index_ >= family_write_tasks_.size()) {
    ++counters_.slice_epoch_validation_failures;
    throw std::logic_error("invalid Spine slice-epoch response");
  }
  const FamilyWriteTask &active = family_write_tasks_[active_family_index_];
  const std::size_t logical_family =
      active.hot ? config_.partitions + active.family : active.family;
  if (task.metadata_family != logical_family ||
      task.metadata_level != active.target) {
    ++counters_.slice_epoch_validation_failures;
    throw std::logic_error("Spine slice-epoch response changed writer");
  }
  const std::uint64_t packed = read_u64_le(response.read_data, 0);
  const std::uint64_t slice =
      logical_family * config_.levels + active.target;
  const std::uint64_t low_slice = slice & ~std::uint64_t{1};
  slice_epochs_[low_slice / config_.levels][low_slice % config_.levels] =
      static_cast<std::uint32_t>(packed);
  if (low_slice + 1 < kSpineFamilyCount * config_.levels) {
    slice_epochs_[(low_slice + 1) / config_.levels]
                 [(low_slice + 1) % config_.levels] =
        static_cast<std::uint32_t>(packed >> 32);
  }
  active_writer_current_epoch_ =
      static_cast<std::uint32_t>(packed >> ((slice & 1U) * 32));
  active_writer_epoch_ready_ = true;
  ++counters_.slice_epoch_responses;
  counters_.slice_epoch_payload_read_bytes += response.read_data.size();
}

void SpineL0Maintenance::prepare_active_writer_epoch() {
  if (!active_writer_epoch_ready_ ||
      active_family_index_ >= family_write_tasks_.size()) {
    ++counters_.slice_epoch_validation_failures;
    throw std::logic_error("Spine writer advanced without its slice epoch");
  }
  const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
  active_writer_next_epoch_ = active_writer_current_epoch_ + 1U;
  active_writer_epoch_wrapped_ = active_writer_next_epoch_ == 0;
  if (active_writer_epoch_wrapped_) {
    active_writer_next_epoch_ = 1;
    ++counters_.epoch_full_clear_fallbacks;
    ++counters_.epoch_wrap_events;
    enqueue_epoch_full_clear(task);
  }
  const std::size_t logical_family =
      task.hot ? config_.partitions + task.family : task.family;
  staged_writer_epochs_[logical_family][task.target] =
      active_writer_next_epoch_;
}

void SpineL0Maintenance::enqueue_epoch_full_clear(
    const FamilyWriteTask &task) {
  const std::uint64_t page_count =
      spine_metadata_layout(config_).page_count;
  const std::uint64_t bitmap_words = page_count * 4;
  const std::uint64_t page_base_words = (page_count + 2) >> 1;
  const std::uint64_t rows =
      task.hot ? counters_.hot_family_rows[task.family]
               : counters_.family_rows[task.family];
  const SpineLevelLayout layout =
      task.target == 0
          ? spine_slice_layout(config_, task.hot, task.target, rows)
          : spine_level_layout(config_, task.hot, task.target);
  const auto enqueue_range = [&](std::uint64_t offset_words,
                                 std::uint64_t words) {
    if (words == 0) {
      return;
    }
    const std::uint64_t bytes = words * kSpineGraphWordBytes;
    enqueue_task(*ports_.graph[task.family], MemoryOperation::kWrite,
                 offset_words * kSpineGraphWordBytes, bytes,
                 TaskClass::kGraph,
                 std::vector<std::uint8_t>(
                     static_cast<std::size_t>(bytes), 0),
                 {}, false, TaskPurpose::kLevelWriterEpochClear);
    ++counters_.epoch_clear_parent_writes;
    counters_.epoch_clear_word_writes += words;
    counters_.epoch_clear_payload_write_bytes += bytes;
  };
  enqueue_range(layout.bitmap_offset_words, bitmap_words);
  enqueue_range(layout.page_base_offset_words, page_base_words);
  enqueue_range(layout.row_offset_offset_words, layout.row_capacity_words);
  enqueue_range(layout.mask_offset_words, layout.mask_capacity_words);
}

void SpineL0Maintenance::begin_active_family_write() {
  if (active_family_index_ >= family_write_tasks_.size()) {
    throw std::logic_error("Spine writer start has no active family");
  }
  const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
  if (task.target == 0) {
    initialize_l0_level_writer(task);
    if (config_.maintenance_architecture ==
        SpineMaintenanceArchitecture::kCandidate10OnePass) {
      const std::size_t logical_family =
          task.hot ? config_.partitions + task.family : task.family;
      sorted_scan_edges_ = candidate_family_buckets_[logical_family];
      scan_base_address_ =
          config_.persistent_family_bucket_base +
          static_cast<std::uint64_t>(candidate_family_begin_[logical_family]) *
              kSpineSortWordBytes;
      begin_sorted_scan(Phase::kWriteProcess,
                        ScanKind::kCandidateBucketWrite);
    } else {
      begin_sorted_scan(Phase::kWriteProcess, ScanKind::kL0Write);
    }
  } else {
    initialize_carry_engine(task);
    phase_ = Phase::kCarryProcess;
  }
}

bool SpineL0Maintenance::enqueue_retired_writer_epochs() {
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  std::set<std::uint64_t> words;
  for (std::size_t family = 0; family < kSpineFamilyCount; ++family) {
    for (std::size_t level = 0; level < config_.levels; ++level) {
      if (staged_writer_epochs_[family][level] == 0) {
        continue;
      }
      slice_epochs_[family][level] = staged_writer_epochs_[family][level];
      const std::uint64_t slice = family * config_.levels + level;
      words.insert(slice >> 1);
    }
  }
  if (words.empty()) {
    return false;
  }
  counters_.epoch_commit_failures = 1;
  for (const std::uint64_t word : words) {
    const std::uint64_t low_slice = word * 2;
    std::uint64_t packed =
        slice_epochs_[low_slice / config_.levels]
                     [low_slice % config_.levels];
    if (low_slice + 1 < metadata.slice_count) {
      packed |= static_cast<std::uint64_t>(
                    slice_epochs_[(low_slice + 1) / config_.levels]
                                 [(low_slice + 1) % config_.levels])
                << 32;
    }
    enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                 config_.metadata_base +
                     (metadata.slice_epoch_base + word) * kMetadataWordBytes,
                 kMetadataWordBytes, TaskClass::kMetadata,
                 encode_u64_words({packed}), {}, false,
                 TaskPurpose::kEpochRetireWrite);
    ++counters_.epoch_retire_writes;
  }
  return true;
}

void SpineL0Maintenance::resolve_target_selector_level(
    const CycleContext &context) {
  const std::size_t family_base = target_scan_hot_ ? config_.partitions : 0;
  bool occupied = false;
  for (std::size_t family = 0; family < config_.partitions; ++family) {
    const std::size_t logical_family = family_base + family;
    if (target_metadata_ready_[logical_family][target_scan_level_] != 3U) {
      ++counters_.target_selector_validation_failures;
      throw std::logic_error("incomplete Spine target-selector metadata level");
    }
    occupied = occupied ||
               target_occupied_[logical_family][target_scan_level_] != 0 ||
               target_edge_counts_[logical_family][target_scan_level_] != 0;
  }
  if (!occupied && target_scan_candidate_ < 0) {
    target_scan_candidate_ = static_cast<std::int32_t>(target_scan_level_);
  }
  ++counters_.target_selector_levels_scanned;
  ++target_scan_level_;
  if (target_scan_level_ < config_.levels) {
    enqueue_target_selector_level();
    return;
  }
  if (context.domain_cycle < target_scan_min_finish_cycle_) {
    phase_ = Phase::kTargetSelectPadding;
    return;
  }
  finish_target_selector(context);
}

void SpineL0Maintenance::finish_target_selector(
    const CycleContext &context) {
  const std::size_t selected = target_for(target_scan_hot_);
  const std::size_t candidate =
      target_scan_candidate_ < 0
          ? config_.levels
          : static_cast<std::size_t>(target_scan_candidate_);
  if (selected != candidate) {
    ++counters_.target_selector_validation_failures;
    throw std::logic_error("Spine target-selector reduction mismatch");
  }
  if (target_scan_hot_) {
    counters_.hot_target_level = target_scan_candidate_;
  } else {
    counters_.target_level = target_scan_candidate_;
  }
  if (target_scan_candidate_ < 0) {
    begin_logical_overflow(
        target_scan_hot_ ? "Spine hot level hierarchy has no free target"
                         : "Spine cold level hierarchy has no free target",
        SpineDirtyStatus::kOk);
    return;
  }
  if (!target_scan_hot_ && metadata_hot_enabled_) {
    initialize_target_selector(true, context);
    enqueue_target_selector_level();
    phase_ = Phase::kTargetSelectLevelWait;
    return;
  }
  family_index_ = 0;
  precount_hot_ = false;
  phase_ = config_.maintenance_architecture ==
                   SpineMaintenanceArchitecture::kCandidate10OnePass
               ? Phase::kBuildOutputs
               : Phase::kPrecountBegin;
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

void SpineL0Maintenance::enqueue_dirty_metadata_load() {
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  for (std::uint32_t field = 0; field < 4; ++field) {
    enqueue_task(*ports_.metadata, MemoryOperation::kRead,
                 config_.metadata_base +
                     (metadata.dirty_count_word + field) * kMetadataWordBytes,
                 kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
                 TaskPurpose::kDirtyMetadataLoad, field);
  }
  if (config_.maintenance_architecture ==
      SpineMaintenanceArchitecture::kCandidate10OnePass) {
    for (const std::uint32_t field : {8U, 13U}) {
      enqueue_task(
          *ports_.metadata, MemoryOperation::kRead,
          config_.metadata_base +
              (metadata.dirty_count_word + field) * kMetadataWordBytes,
          kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
          TaskPurpose::kDirtyMetadataLoad, field);
    }
  }
}

void SpineL0Maintenance::candidate_finish_classify_block() {
  if (candidate_block_edges_ == 0 ||
      candidate_block_begin_ + candidate_block_edges_ >
          candidate_family_tags_.size()) {
    throw std::logic_error("invalid candidate-10 classify block");
  }
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  const std::size_t tag_words = (candidate_block_edges_ + 7) / 8;
  for (std::size_t word = 0; word < tag_words; ++word) {
    std::uint64_t packed = 0;
    for (std::size_t lane = 0; lane < 8; ++lane) {
      const std::size_t index = candidate_block_begin_ + word * 8 + lane;
      if (index < candidate_block_begin_ + candidate_block_edges_) {
        packed |= static_cast<std::uint64_t>(candidate_family_tags_[index])
                  << (lane * 8);
      }
    }
    enqueue_task(
        *ports_.metadata, MemoryOperation::kWrite,
        config_.metadata_base +
            (metadata.family_tag_base + candidate_block_begin_ / 8 + word) *
                kMetadataWordBytes,
        kMetadataWordBytes, TaskClass::kMetadata,
        encode_u64_words({packed}), {}, false,
        TaskPurpose::kCandidateFamilyTagWrite, 0, 0, 0, 0, 0, word);
    ++counters_.candidate_family_tag_word_writes;
  }
  const std::size_t record_base =
      candidate_source_records_.size() - candidate_classify_block_records_.size();
  for (std::size_t record = 0;
       record < candidate_classify_block_records_.size(); ++record) {
    const CandidateSourceRecord &value = candidate_classify_block_records_[record];
    const std::uint64_t packed =
        (static_cast<std::uint64_t>(value.family_mask) << 32) | value.source;
    enqueue_task(
        *ports_.metadata, MemoryOperation::kWrite,
        config_.metadata_base +
            (metadata.source_record_base + record_base + record) *
                kMetadataWordBytes,
        kMetadataWordBytes, TaskClass::kMetadata,
        encode_u64_words({packed}), {}, false,
        TaskPurpose::kCandidateSourceRecordWrite, value.source, 0, 0, 0, 0,
        record_base + record);
    ++counters_.candidate_source_record_word_writes;
  }
  candidate_classify_block_records_.clear();
  candidate_block_begin_ += candidate_block_edges_;
  candidate_block_edges_ = 0;
  candidate_classify_flush_pending_ = true;
}

void SpineL0Maintenance::candidate_begin_publication_pass() {
  candidate_publication_cursor_ = 0;
  candidate_publication_loaded_ = 0;
  candidate_publication_responses_ = 0;
  candidate_publication_writes_ = 0;
  candidate_publication_window_records_.clear();
  candidate_publication_words_.clear();
  phase_ = Phase::kCandidatePublicationLoad;
  candidate_load_publication_window();
}

void SpineL0Maintenance::candidate_load_publication_window() {
  const std::size_t remaining =
      candidate_source_records_.size() - candidate_publication_cursor_;
  candidate_publication_loaded_ = 0;
  std::size_t completed_groups = 0;
  std::uint64_t open_word = 0;
  bool have_open_word = false;
  const bool directory =
      candidate_publication_kind_ == CandidatePublicationKind::kDirectory;
  while (candidate_publication_loaded_ < remaining) {
    const CandidateSourceRecord &record = candidate_source_records_[
        candidate_publication_cursor_ + candidate_publication_loaded_];
    const std::uint64_t word =
        directory ? record.source >> 2 : record.source >> 7;
    if (have_open_word && word != open_word) {
      ++completed_groups;
      if (completed_groups == config_.candidate_publication_window) {
        break;
      }
    }
    open_word = word;
    have_open_word = true;
    ++candidate_publication_loaded_;
  }
  if (candidate_publication_loaded_ == 0) {
    throw std::logic_error("candidate publication made no source progress");
  }
  candidate_publication_window_records_.assign(candidate_publication_loaded_,
                                                CandidateSourceRecord{});
  candidate_publication_responses_ = 0;
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  for (std::size_t local = 0; local < candidate_publication_loaded_; ++local) {
    const std::size_t index = candidate_publication_cursor_ + local;
    enqueue_task(
        *ports_.metadata, MemoryOperation::kRead,
        config_.metadata_base + (metadata.source_record_base + index) *
                                    kMetadataWordBytes,
        kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
        TaskPurpose::kCandidatePublicationSourceRead, 0, 0, 0, 0, 0, index);
    ++counters_.publication_source_record_reads;
  }
  candidate_publication_cursor_ += candidate_publication_loaded_;
}

void SpineL0Maintenance::candidate_build_publication_groups() {
  candidate_publication_words_.clear();
  const bool directory =
      candidate_publication_kind_ == CandidatePublicationKind::kDirectory;
  for (const CandidateSourceRecord &record :
       candidate_publication_window_records_) {
    const std::uint64_t word_index =
        directory ? record.source >> 2 : record.source >> 7;
    const std::size_t lane =
        directory ? (record.source & 3U) : ((record.source >> 5) & 3U);
    const std::uint32_t mask =
        directory ? record.family_mask
                  : (std::uint32_t{1} << (record.source & 31U));
    if (candidate_publication_words_.empty() ||
        candidate_publication_words_.back().word_index != word_index) {
      if (candidate_publication_words_.size() >=
          config_.candidate_publication_window) {
        throw std::logic_error("candidate publication window overflow");
      }
      candidate_publication_words_.push_back(
          CandidatePublicationWord{
              .word_index = word_index,
              .requested = {},
              .persisted = {},
              .output = {},
              .write = false,
          });
    }
    candidate_publication_words_.back().requested[lane] |= mask;
  }
  candidate_publication_responses_ = 0;
  const bool skip_bitmap_reads =
      candidate_publication_kind_ == CandidatePublicationKind::kBitmap &&
      candidate_publication_empty_proven_;
  if (skip_bitmap_reads) {
    for (CandidatePublicationWord &word : candidate_publication_words_) {
      word.persisted.assign(kPersistentRecordBytes, 0);
    }
    return;
  }
  for (std::size_t slot = 0; slot < candidate_publication_words_.size(); ++slot) {
    const CandidatePublicationWord &word = candidate_publication_words_[slot];
    const std::uint64_t base = directory
                                   ? config_.persistent_family_directory_base
                                   : config_.persistent_dirty_bitmap_base;
    enqueue_task(
        *ports_.sorted_edges, MemoryOperation::kRead,
        base + word.word_index * kPersistentRecordBytes,
        kPersistentRecordBytes, TaskClass::kPersistent, {}, {}, false,
        directory ? TaskPurpose::kCandidateDirectoryRead
                  : TaskPurpose::kCandidateBitmapRead,
        0, 0, 0, 0, 0, slot);
    if (directory) {
      ++counters_.family_directory_word_reads;
    } else if (candidate_publication_kind_ ==
               CandidatePublicationKind::kBitmapProbe) {
      ++counters_.publication_bitmap_probe_reads;
    } else {
      ++counters_.dirty_bitmap_reads;
    }
  }
}

void SpineL0Maintenance::candidate_write_publication_groups() {
  const bool directory =
      candidate_publication_kind_ == CandidatePublicationKind::kDirectory;
  const bool probe =
      candidate_publication_kind_ == CandidatePublicationKind::kBitmapProbe;
  candidate_publication_writes_ = 0;
  for (std::size_t slot = 0; slot < candidate_publication_words_.size(); ++slot) {
    CandidatePublicationWord &word = candidate_publication_words_[slot];
    if (word.persisted.size() != kPersistentRecordBytes) {
      throw std::logic_error("candidate publication missed HBM payload");
    }
    word.output = word.persisted;
    std::size_t new_bits = 0;
    for (std::size_t lane = 0; lane < 4; ++lane) {
      const std::uint32_t old_value =
          read_u32_le(word.persisted, lane * sizeof(std::uint32_t));
      const std::uint32_t requested = word.requested[lane];
      const std::uint32_t added = requested & ~old_value;
      new_bits += std::popcount(added);
      write_u32_le(word.output, lane * sizeof(std::uint32_t),
                   old_value | requested);
      if (!directory && !probe) {
        for (std::size_t bit = 0; bit < 32; ++bit) {
          if ((added & (std::uint32_t{1} << bit)) != 0) {
            candidate_new_dirty_sources_.push_back(static_cast<std::uint32_t>(
                word.word_index * 128 + lane * 32 + bit));
          }
        }
      }
    }
    if (directory) {
      counters_.family_directory_bits_set += new_bits;
      word.write = true;
    } else if (probe) {
      candidate_probe_new_count_ += new_bits;
      word.write = false;
    } else {
      word.write = new_bits != 0;
    }
    if (!word.write) {
      continue;
    }
    const std::uint64_t base = directory
                                   ? config_.persistent_family_directory_base
                                   : config_.persistent_dirty_bitmap_base;
    enqueue_task(
        *ports_.sorted_edges, MemoryOperation::kWrite,
        base + word.word_index * kPersistentRecordBytes,
        kPersistentRecordBytes, TaskClass::kPersistent, word.output, {}, false,
        directory ? TaskPurpose::kCandidateDirectoryWrite
                  : TaskPurpose::kCandidateBitmapWrite,
        0, 0, 0, 0, 0, slot);
    ++candidate_publication_writes_;
    if (directory) {
      ++counters_.family_directory_word_writes;
    } else {
      ++counters_.dirty_bitmap_writes;
    }
  }
}

void SpineL0Maintenance::candidate_advance_publication_pass() {
  if (candidate_publication_cursor_ < candidate_source_records_.size()) {
    phase_ = Phase::kCandidatePublicationLoad;
    candidate_load_publication_window();
    return;
  }
  if (candidate_publication_kind_ == CandidatePublicationKind::kDirectory) {
    candidate_publication_kind_ =
        counters_.publication_fallback ? CandidatePublicationKind::kBitmapProbe
                                       : CandidatePublicationKind::kBitmap;
    candidate_probe_new_count_ = 0;
    candidate_begin_publication_pass();
    return;
  }
  if (candidate_publication_kind_ == CandidatePublicationKind::kBitmapProbe) {
    if (static_cast<std::uint64_t>(dirty_count_) +
            candidate_probe_new_count_ >
        config_.max_vertices) {
      begin_logical_overflow("candidate dirty frontier exceeds MAX_N",
                             SpineDirtyStatus::kInvalidState);
      return;
    }
    candidate_publication_kind_ = CandidatePublicationKind::kBitmap;
    candidate_new_dirty_sources_.clear();
    candidate_begin_publication_pass();
    return;
  }
  counters_.dirty_list_appends = candidate_new_dirty_sources_.size();
  counters_.dirty_duplicates_suppressed +=
      candidate_source_records_.size() - candidate_new_dirty_sources_.size();
  phase_ = Phase::kCandidateListBegin;
}

void SpineL0Maintenance::candidate_begin_list_source_load() {
  candidate_list_sources_.assign(candidate_new_dirty_sources_.size(), 0);
  candidate_list_source_cursor_ = 0;
  candidate_list_source_loaded_ = 0;
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  if (candidate_publication_empty_proven_) {
    for (std::size_t index = 0; index < candidate_new_dirty_sources_.size();
         ++index) {
      enqueue_task(
          *ports_.metadata, MemoryOperation::kRead,
          config_.metadata_base + (metadata.source_record_base + index) *
                                      kMetadataWordBytes,
          kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
          TaskPurpose::kCandidateListSourceRead, 0, 0, 0, 0, 0, index);
      ++counters_.publication_source_record_reads;
    }
  } else {
    const std::size_t words = (candidate_new_dirty_sources_.size() + 1) / 2;
    for (std::size_t word = 0; word < words; ++word) {
      enqueue_task(
          *ports_.metadata, MemoryOperation::kRead,
          config_.metadata_base +
              (metadata.new_dirty_base + word) * kMetadataWordBytes,
          kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
          TaskPurpose::kCandidateListSourceRead, 0, 0, 0, 0, 0, word);
      ++counters_.publication_scratch_word_reads;
    }
  }
}

void SpineL0Maintenance::candidate_build_list_words() {
  candidate_list_words_.clear();
  candidate_list_read_responses_ = 0;
  const std::size_t new_count = candidate_list_sources_.size();
  if (new_count == 0) {
    return;
  }
  const std::uint64_t first_word = dirty_count_ >> 2;
  const std::uint64_t final_count = dirty_count_ + new_count;
  const std::uint64_t last_word = (final_count - 1) >> 2;
  candidate_list_words_.assign(
      static_cast<std::size_t>(last_word - first_word + 1),
      std::vector<std::uint8_t>(kPersistentRecordBytes, 0));
  for (std::size_t slot = 0; slot < candidate_list_words_.size(); ++slot) {
    const std::uint64_t word_index = first_word + slot;
    const bool preserve_first = word_index == first_word && (dirty_count_ & 3U);
    const bool preserve_last =
        word_index == last_word && (final_count & 3U);
    if (!preserve_first && !preserve_last) {
      continue;
    }
    enqueue_task(
        *ports_.sorted_edges, MemoryOperation::kRead,
        config_.persistent_dirty_list_base +
            word_index * kPersistentRecordBytes,
        kPersistentRecordBytes, TaskClass::kPersistent, {}, {}, false,
        TaskPurpose::kCandidateListRead, 0, 0, 0, 0, 0, slot);
    ++counters_.publication_list_word_reads;
  }
}

void SpineL0Maintenance::candidate_write_list_words() {
  const std::size_t new_count = candidate_list_sources_.size();
  if (new_count == 0) {
    return;
  }
  const std::uint64_t first_word = dirty_count_ >> 2;
  for (std::size_t source_index = 0; source_index < new_count; ++source_index) {
    const std::uint64_t logical = dirty_count_ + source_index;
    const std::size_t slot = static_cast<std::size_t>((logical >> 2) - first_word);
    write_u32_le(candidate_list_words_.at(slot),
                 (logical & 3U) * sizeof(std::uint32_t),
                 candidate_list_sources_[source_index]);
  }
  for (std::size_t slot = 0; slot < candidate_list_words_.size(); ++slot) {
    enqueue_task(
        *ports_.sorted_edges, MemoryOperation::kWrite,
        config_.persistent_dirty_list_base +
            (first_word + slot) * kPersistentRecordBytes,
        kPersistentRecordBytes, TaskClass::kPersistent,
        candidate_list_words_[slot], {}, false,
        TaskPurpose::kCandidateListWrite, 0, 0, 0, 0, 0, slot);
    ++counters_.publication_list_word_writes;
  }
}

void SpineL0Maintenance::consume_candidate_memory_response(
    const MemoryTask &task, const AxiResponse &response) {
  if (task.operation == MemoryOperation::kWrite) {
    if (!response.read_data.empty()) {
      throw std::logic_error("candidate-10 write returned payload");
    }
    return;
  }
  if (task.purpose == TaskPurpose::kCandidatePublicationSourceRead) {
    const std::size_t window_start =
        candidate_publication_cursor_ - candidate_publication_loaded_;
    if (task.candidate_index < window_start ||
        task.candidate_index >= candidate_publication_cursor_) {
      throw std::logic_error("candidate source-record response is out of window");
    }
    const std::uint64_t packed = read_u64_le(response.read_data, 0);
    const CandidateSourceRecord record{static_cast<std::uint32_t>(packed),
                                       static_cast<std::uint32_t>(packed >> 32)};
    if (record.source != candidate_source_records_[task.candidate_index].source ||
        record.family_mask !=
            candidate_source_records_[task.candidate_index].family_mask) {
      throw std::logic_error("candidate source-record payload mismatch");
    }
    candidate_publication_window_records_[task.candidate_index - window_start] =
        record;
    ++candidate_publication_responses_;
    return;
  }
  if (task.purpose == TaskPurpose::kCandidateDirectoryRead ||
      task.purpose == TaskPurpose::kCandidateBitmapRead) {
    if (task.candidate_index >= candidate_publication_words_.size()) {
      throw std::logic_error("candidate publication response slot overflow");
    }
    candidate_publication_words_[task.candidate_index].persisted =
        response.read_data;
    ++candidate_publication_responses_;
    return;
  }
  if (task.purpose == TaskPurpose::kCandidateListSourceRead) {
    if (candidate_publication_empty_proven_) {
      if (task.candidate_index >= candidate_list_sources_.size()) {
        throw std::logic_error("candidate list source response overflow");
      }
      const std::uint64_t packed = read_u64_le(response.read_data, 0);
      candidate_list_sources_[task.candidate_index] =
          static_cast<std::uint32_t>(packed);
      ++candidate_list_source_loaded_;
    } else {
      const std::size_t low = task.candidate_index * 2;
      if (low >= candidate_list_sources_.size()) {
        throw std::logic_error("candidate scratch response overflow");
      }
      candidate_list_sources_[low] = read_u32_le(response.read_data, 0);
      ++candidate_list_source_loaded_;
      if (low + 1 < candidate_list_sources_.size()) {
        candidate_list_sources_[low + 1] = read_u32_le(response.read_data, 4);
        ++candidate_list_source_loaded_;
      }
    }
    return;
  }
  if (task.purpose == TaskPurpose::kCandidateListRead) {
    if (task.candidate_index >= candidate_list_words_.size()) {
      throw std::logic_error("candidate list response slot overflow");
    }
    candidate_list_words_[task.candidate_index] = response.read_data;
    ++candidate_list_read_responses_;
    return;
  }
  throw std::logic_error("unexpected candidate-10 read response");
}

void SpineL0Maintenance::enqueue_dirty_generation_prepare() {
  ++dirty_generation_;
  if (dirty_generation_ == 0) {
    dirty_generation_ = 1;
  }
  ++counters_.dirty_generation_advances;
  counters_.dirty_generation = dirty_generation_;
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  const auto write_word = [&](std::uint64_t word, std::uint64_t value) {
    enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                 config_.metadata_base + word * kMetadataWordBytes,
                 kMetadataWordBytes, TaskClass::kMetadata,
                 encode_u64_words({value}));
  };
  write_word(metadata.dirty_generation_word, dirty_generation_);
  write_word(metadata.dirty_candidate_valid_word, 0);
  write_word(metadata.dirty_host_valid_word, 0);
}

void SpineL0Maintenance::enqueue_dirty_mark_edge_read() {
  if (scan_index_ >= sorted_scan_edges_.size()) {
    return;
  }
  enqueue_task(
      *ports_.sorted_edges, MemoryOperation::kRead,
      config_.sorted_edges_base + scan_index_ * kSpineSortWordBytes,
      kSpineSortWordBytes, TaskClass::kSorted, {}, {}, streaming_scan_,
      TaskPurpose::kDirtyMarkEdge);
}

void SpineL0Maintenance::enqueue_dirty_bitmap_read(std::uint32_t source) {
  if (dirty_source_pending_) {
    throw std::logic_error("overlapping Spine dirty-source updates");
  }
  dirty_source_pending_ = true;
  dirty_pending_source_ = source;
  enqueue_task(*ports_.sorted_edges, MemoryOperation::kRead,
               config_.persistent_dirty_bitmap_base +
                   (source >> 7) * kPersistentRecordBytes,
               kPersistentRecordBytes, TaskClass::kPersistent, {}, {}, false,
               TaskPurpose::kDirtyBitmapRead, source);
}

void SpineL0Maintenance::enqueue_dirty_final_metadata() {
  counters_.dirty_count = dirty_count_;
  counters_.dirty_generation = dirty_generation_;
  counters_.dirty_hash_sum = dirty_hash_sum_;
  counters_.dirty_hash_xor = dirty_hash_xor_;
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  const auto write_word = [&](std::uint64_t word, std::uint64_t value) {
    enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                 config_.metadata_base + word * kMetadataWordBytes,
                 kMetadataWordBytes, TaskClass::kMetadata,
                 encode_u64_words({value}));
  };
  write_word(metadata.dirty_count_word, dirty_count_);
  write_word(metadata.dirty_hash_sum_word, dirty_hash_sum_);
  write_word(metadata.dirty_hash_xor_word, dirty_hash_xor_);
  write_word(metadata.dirty_last_mode_word, 0);
  write_word(metadata.dirty_last_status_word,
             static_cast<std::uint32_t>(dirty_status_));
}

void SpineL0Maintenance::finish_dirty_source_update() {
  dirty_source_pending_ = false;
  dirty_bitmap_original_payload_.clear();
  if (scan_index_ < sorted_scan_edges_.size()) {
    enqueue_dirty_mark_edge_read();
  }
}

void SpineL0Maintenance::consume_dirty_memory_response(
    const MemoryTask &task, const AxiResponse &response) {
  switch (task.purpose) {
  case TaskPurpose::kGeneric:
    return;
  case TaskPurpose::kDirtyMetadataLoad: {
    const std::uint64_t value = read_u64_le(response.read_data, 0);
    switch (task.source) {
    case 0:
      dirty_count_ = static_cast<std::uint32_t>(value);
      counters_.dirty_count = dirty_count_;
      if (value > config_.max_vertices) {
        begin_logical_overflow(
            "Spine persistent dirty count exceeds MAX_N",
            SpineDirtyStatus::kInvalidState);
        return;
      }
      break;
    case 1:
      dirty_generation_ = static_cast<std::uint32_t>(value);
      counters_.dirty_generation = dirty_generation_;
      break;
    case 2:
      dirty_hash_sum_ = value;
      counters_.dirty_hash_sum = dirty_hash_sum_;
      break;
    case 3:
      dirty_hash_xor_ = value;
      counters_.dirty_hash_xor = dirty_hash_xor_;
      break;
    case 8:
      candidate_dirty_candidate_valid_ = value != 0;
      break;
    case 13:
      candidate_dirty_host_valid_ = value != 0;
      break;
    default:
      throw std::logic_error("unknown Spine dirty metadata field");
    }
    return;
  }
  case TaskPurpose::kDirtyMarkEdge: {
    if (task.stream_sorted_scan) {
      return;
    }
    if (task.address < config_.sorted_edges_base ||
        response.read_data.size() != kSpineSortWordBytes) {
      throw std::logic_error("invalid non-streamed dirty mark edge response");
    }
    const std::size_t index = static_cast<std::size_t>(
        (task.address - config_.sorted_edges_base) / kSpineSortWordBytes);
    if (index >= sorted_scan_edges_.size() ||
        !scan_response_edges_
             .emplace(index, decode_spine_sort_edge(response.read_data))
             .second) {
      throw std::logic_error("duplicate dirty mark edge response");
    }
    counters_.sorted_payload_read_bytes += response.read_data.size();
    counters_.max_sorted_scan_buffered_edges = std::max(
        counters_.max_sorted_scan_buffered_edges, scan_response_edges_.size());
    return;
  }
  case TaskPurpose::kDirtyBitmapRead: {
    if (!dirty_source_pending_ || task.source != dirty_pending_source_) {
      throw std::logic_error("dirty bitmap response source mismatch");
    }
    ++counters_.dirty_bitmap_reads;
    const std::size_t byte = (task.source & 127U) >> 3;
    const std::uint8_t mask =
        static_cast<std::uint8_t>(1U << (task.source & 7U));
    if ((response.read_data[byte] & mask) != 0) {
      ++counters_.dirty_duplicates_suppressed;
      finish_dirty_source_update();
      return;
    }
    dirty_bitmap_original_payload_ = response.read_data;
    std::vector<std::uint8_t> payload = response.read_data;
    payload[byte] |= mask;
    const bool overflow = dirty_count_ >= config_.max_vertices;
    enqueue_task(*ports_.sorted_edges, MemoryOperation::kWrite, task.address,
                 kPersistentRecordBytes, TaskClass::kPersistent,
                 std::move(payload), {}, false,
                 overflow ? TaskPurpose::kDirtyBitmapOverflowSet
                          : TaskPurpose::kDirtyBitmapWrite,
                 task.source);
    return;
  }
  case TaskPurpose::kDirtyBitmapWrite:
    ++counters_.dirty_bitmap_writes;
    enqueue_task(*ports_.sorted_edges, MemoryOperation::kRead,
                 config_.persistent_dirty_list_base +
                     (dirty_count_ >> 2) * kPersistentRecordBytes,
                 kPersistentRecordBytes, TaskClass::kPersistent, {}, {}, false,
                 TaskPurpose::kDirtyListRead, task.source);
    return;
  case TaskPurpose::kDirtyBitmapOverflowSet:
    enqueue_task(*ports_.sorted_edges, MemoryOperation::kWrite, task.address,
                 kPersistentRecordBytes, TaskClass::kPersistent,
                 dirty_bitmap_original_payload_, {}, false,
                 TaskPurpose::kDirtyBitmapOverflowClear, task.source);
    return;
  case TaskPurpose::kDirtyBitmapOverflowClear:
    dirty_status_ = SpineDirtyStatus::kInvalidState;
    enqueue_dirty_final_metadata();
    begin_logical_overflow("Spine persistent dirty list exceeds MAX_N",
                           dirty_status_);
    return;
  case TaskPurpose::kDirtyListRead: {
    ++counters_.dirty_list_reads;
    std::vector<std::uint8_t> payload = response.read_data;
    write_u32_le(payload, (dirty_count_ & 3U) * sizeof(std::uint32_t),
                 task.source);
    enqueue_task(*ports_.sorted_edges, MemoryOperation::kWrite, task.address,
                 kPersistentRecordBytes, TaskClass::kPersistent,
                 std::move(payload), {}, false, TaskPurpose::kDirtyListWrite,
                 task.source);
    return;
  }
  case TaskPurpose::kDirtyListWrite:
    ++counters_.dirty_list_appends;
    ++dirty_count_;
    dirty_hash_sum_ += spine_dirty_hash_sum_term(task.source);
    dirty_hash_xor_ ^= spine_dirty_hash_xor_term(task.source);
    finish_dirty_source_update();
    return;
  case TaskPurpose::kCandidateFamilyTagWrite:
  case TaskPurpose::kCandidateSourceRecordWrite:
  case TaskPurpose::kCandidateBucketWrite:
  case TaskPurpose::kCandidatePublicationSourceRead:
  case TaskPurpose::kCandidateDirectoryRead:
  case TaskPurpose::kCandidateDirectoryWrite:
  case TaskPurpose::kCandidateBitmapRead:
  case TaskPurpose::kCandidateBitmapWrite:
  case TaskPurpose::kCandidateScratchWrite:
  case TaskPurpose::kCandidateListSourceRead:
  case TaskPurpose::kCandidateListRead:
  case TaskPurpose::kCandidateListWrite:
    throw std::logic_error(
        "candidate response reached the serial dirty response handler");
  case TaskPurpose::kTargetMetadataOccupied:
  case TaskPurpose::kTargetMetadataEdgeCount:
    throw std::logic_error(
        "target-selector response reached the dirty response handler");
  case TaskPurpose::kResultColdEdgeCount:
  case TaskPurpose::kResultHotEdgeCount:
  case TaskPurpose::kMaintenanceResultWrite:
    throw std::logic_error(
        "result response reached the dirty response handler");
  case TaskPurpose::kLevelWriterSliceEpochRead:
  case TaskPurpose::kLevelWriterEpochClear:
  case TaskPurpose::kEpochRetireWrite:
    throw std::logic_error(
        "epoch response reached the dirty response handler");
  case TaskPurpose::kMetadataControl:
  case TaskPurpose::kScanHotBitmap:
  case TaskPurpose::kCarryNewBatchHotBitmap:
    throw std::logic_error(
        "hot-metadata response reached the dirty response handler");
  case TaskPurpose::kCarryNewBatchRead:
  case TaskPurpose::kCarryCursorSliceMetadata:
  case TaskPurpose::kCarryCursorSliceEpoch:
  case TaskPurpose::kCarryCursorPageCount:
  case TaskPurpose::kCarryCursorPageList:
  case TaskPurpose::kCarryCursorPageEpoch:
  case TaskPurpose::kCarryCursorPageBase:
  case TaskPurpose::kCarryCursorBitmap:
  case TaskPurpose::kCarryCursorRowOffsets:
  case TaskPurpose::kCarryLevelEdgeRead:
  case TaskPurpose::kLevelWriterGraphWrite:
  case TaskPurpose::kLevelWriterMetadataWrite:
    throw std::logic_error("carry response reached the dirty response handler");
  }
}

void SpineL0Maintenance::enqueue_carry_cursor_metadata(
    std::size_t stream_index) {
  const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
  const CarryInputStream &stream = carry_streams_[stream_index];
  const std::size_t logical_family =
      task.hot ? config_.partitions + task.family : task.family;
  const std::uint64_t slice =
      logical_family * config_.levels + stream.level;
  enqueue_task(*ports_.metadata, MemoryOperation::kRead,
               config_.metadata_base + slice * 8 * kMetadataWordBytes,
               8 * kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
               TaskPurpose::kCarryCursorSliceMetadata, 0, stream_index);
}

void SpineL0Maintenance::maybe_enqueue_carry_page_list(
    std::size_t stream_index) {
  CarryInputStream &stream = carry_streams_[stream_index];
  if (!stream.slice_epoch_ready || !stream.page_count_ready ||
      stream.page_list_requested) {
    return;
  }
  if (stream.slice_epoch == 0 || stream.page_count == 0 ||
      stream.page_count > spine_metadata_layout(config_).page_count ||
      stream.page_count > stream.row_count) {
    ++counters_.carry_cursor_validation_failures;
    throw std::logic_error("invalid Spine carry page-list metadata");
  }
  const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
  const std::size_t logical_family =
      task.hot ? config_.partitions + task.family : task.family;
  const std::uint64_t slice =
      logical_family * config_.levels + stream.level;
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  stream.page_list_requested = true;
  enqueue_task(
      *ports_.metadata, MemoryOperation::kRead,
      config_.metadata_base +
          (metadata.page_list_base +
           slice * metadata.page_list_words_per_slice) *
              kMetadataWordBytes,
      ((stream.page_count + 3) / 4) * kMetadataWordBytes,
      TaskClass::kMetadata, {}, {}, false, TaskPurpose::kCarryCursorPageList,
      0, stream_index);
}

void SpineL0Maintenance::enqueue_carry_page_indexes(
    std::size_t stream_index) {
  CarryInputStream &stream = carry_streams_[stream_index];
  const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
  const std::size_t logical_family =
      task.hot ? config_.partitions + task.family : task.family;
  const std::uint64_t slice =
      logical_family * config_.levels + stream.level;
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  stream.page_epochs.assign(stream.pages.size(), 0);
  stream.page_bases.assign(stream.pages.size(), 0);
  stream.page_bitmaps.assign(stream.pages.size(), {});
  stream.page_index_responses_pending = stream.pages.size() * 3;
  for (std::size_t index = 0; index < stream.pages.size(); ++index) {
    const std::uint32_t page = stream.pages[index];
    const std::uint64_t epoch_index = slice * metadata.page_count + page;
    enqueue_task(*ports_.metadata, MemoryOperation::kRead,
                 config_.metadata_base +
                     (metadata.page_epoch_base + (epoch_index >> 1)) *
                         kMetadataWordBytes,
                 kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
                 TaskPurpose::kCarryCursorPageEpoch, page, stream_index,
                 index);
    enqueue_task(*ports_.graph[task.family], MemoryOperation::kRead,
                 (stream.page_base_offset_words + (page >> 1)) *
                     kSpineGraphWordBytes,
                 kSpineGraphWordBytes, TaskClass::kGraph, {}, {}, false,
                 TaskPurpose::kCarryCursorPageBase, page, stream_index, index);
    enqueue_task(*ports_.graph[task.family], MemoryOperation::kRead,
                 (stream.bitmap_offset_words + page * 4) *
                     kSpineGraphWordBytes,
                 4 * kSpineGraphWordBytes, TaskClass::kGraph, {}, {}, false,
                 TaskPurpose::kCarryCursorBitmap, page, stream_index, index);
  }
}

void SpineL0Maintenance::finalize_carry_page_indexes(
    std::size_t stream_index) {
  CarryInputStream &stream = carry_streams_[stream_index];
  stream.sources.clear();
  for (std::size_t page_index = 0; page_index < stream.pages.size();
       ++page_index) {
    if (stream.page_epochs[page_index] != stream.slice_epoch ||
        stream.page_bases[page_index] != stream.sources.size()) {
      ++counters_.carry_cursor_validation_failures;
      throw std::logic_error("Spine carry page epoch/base validation failed");
    }
    for (std::size_t word = 0; word < 4; ++word) {
      const std::uint64_t bitmap = stream.page_bitmaps[page_index][word];
      for (std::size_t bit = 0; bit < 64; ++bit) {
        ++counters_.carry_cursor_bits_inspected;
        ++active_carry_result_counters().bits_inspected;
        if ((bitmap & (std::uint64_t{1} << bit)) != 0) {
          stream.sources.push_back(
              stream.pages[page_index] * config_.page_vertices + word * 64 +
              bit);
        }
      }
    }
    // The HLS cursor executes one II=1 FIND_SOURCE iteration per bitmap bit,
    // plus page load, three bitmap-word transitions, and page finish.
    carry_cursor_refill_cycles_remaining_ += 4 * 64 + 5;
  }
  if (stream.sources.size() != stream.row_count) {
    ++counters_.carry_cursor_validation_failures;
    throw std::logic_error("Spine carry bitmap row count mismatch");
  }
  const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
  enqueue_task(*ports_.graph[task.family], MemoryOperation::kRead,
               stream.row_offset_offset_words * kSpineGraphWordBytes,
               ((stream.row_count + 2) >> 1) * kSpineGraphWordBytes,
               TaskClass::kGraph, {}, {}, false,
               TaskPurpose::kCarryCursorRowOffsets, 0, stream_index);
}

void SpineL0Maintenance::level_writer_flush_graph_word(
    std::uint64_t base_word, LevelPendingWord &pending,
    std::uint64_t &counter) {
  if (!pending.valid) {
    return;
  }
  const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
  enqueue_task(*ports_.graph[task.family], MemoryOperation::kWrite,
               (base_word + pending.index) * kSpineGraphWordBytes,
               kSpineGraphWordBytes, TaskClass::kGraph,
               encode_u64_words({pending.value}), {}, false,
               TaskPurpose::kLevelWriterGraphWrite);
  counters_.graph_index_payload_write_bytes += kSpineGraphWordBytes;
  ++counter;
  pending = LevelPendingWord{};
}

void SpineL0Maintenance::level_writer_write_u32(
    std::uint64_t base_word, std::uint32_t index, std::uint32_t value,
    LevelPendingWord &pending, std::uint64_t &counter) {
  const std::uint32_t word = index >> 1;
  if (pending.valid && pending.index != word) {
    level_writer_flush_graph_word(base_word, pending, counter);
  }
  if (!pending.valid) {
    pending.valid = true;
    pending.index = word;
    pending.value = 0;
  }
  const std::size_t shift = (index & 1U) * 32;
  const std::uint64_t mask = std::uint64_t{0xffffffffU} << shift;
  pending.value = (pending.value & ~mask) |
                  (static_cast<std::uint64_t>(value) << shift);
}

void SpineL0Maintenance::level_writer_write_u16(
    std::uint64_t base_word, std::uint32_t index, std::uint16_t value,
    LevelPendingWord &pending, std::uint64_t &counter) {
  const std::uint32_t word = index >> 2;
  if (pending.valid && pending.index != word) {
    level_writer_flush_graph_word(base_word, pending, counter);
  }
  if (!pending.valid) {
    pending.valid = true;
    pending.index = word;
    pending.value = 0;
  }
  const std::size_t shift = (index & 3U) * 16;
  const std::uint64_t mask = std::uint64_t{0xffffU} << shift;
  pending.value = (pending.value & ~mask) |
                  (static_cast<std::uint64_t>(value) << shift);
}

void SpineL0Maintenance::level_writer_flush_bitmap() {
  if (!level_writer_.bitmap_valid) {
    return;
  }
  const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
  std::vector<std::uint8_t> payload;
  payload.reserve(4 * kSpineGraphWordBytes);
  for (const std::uint64_t word : level_writer_.bitmap) {
    append_u64_le(payload, word);
  }
  const std::uint64_t payload_bytes = payload.size();
  enqueue_task(
      *ports_.graph[task.family], MemoryOperation::kWrite,
      (level_writer_.layout.bitmap_offset_words +
       static_cast<std::uint64_t>(level_writer_.bitmap_page) * 4) *
          kSpineGraphWordBytes,
      payload_bytes, TaskClass::kGraph, std::move(payload), {}, false,
      TaskPurpose::kLevelWriterGraphWrite);
  counters_.graph_index_payload_write_bytes += 4 * kSpineGraphWordBytes;
  ++level_writer_.stats.bitmap_page_writes;
  level_writer_.bitmap.fill(0);
  level_writer_.bitmap_valid = false;
}

void SpineL0Maintenance::level_writer_flush_page_list() {
  LevelPendingWord &pending = level_writer_.page_list;
  if (!pending.valid) {
    return;
  }
  const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
  const std::size_t logical_family =
      task.hot ? config_.partitions + task.family : task.family;
  const std::uint64_t slice =
      logical_family * config_.levels + task.target;
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  enqueue_task(
      *ports_.metadata, MemoryOperation::kWrite,
      config_.metadata_base +
          (metadata.page_list_base +
           slice * metadata.page_list_words_per_slice + pending.index) *
              kMetadataWordBytes,
      kMetadataWordBytes, TaskClass::kMetadata,
      encode_u64_words({pending.value}), {}, false,
      TaskPurpose::kLevelWriterMetadataWrite);
  counters_.page_list_payload_write_bytes += kMetadataWordBytes;
  ++level_writer_.stats.page_list_word_writes;
  pending = LevelPendingWord{};
}

std::size_t SpineL0Maintenance::queued_level_writer_tasks_for_port(
    const FixedAxiPort *port) const noexcept {
  return static_cast<std::size_t>(std::count_if(
      tasks_.begin(), tasks_.end(), [port](const MemoryTask &task) {
        return task.port == port &&
               (task.purpose == TaskPurpose::kLevelWriterGraphWrite ||
                task.purpose == TaskPurpose::kLevelWriterMetadataWrite);
      }));
}

bool SpineL0Maintenance::l0_writer_has_queue_headroom() const noexcept {
  if (!level_writer_.initialized || !level_writer_.l0_mode ||
      active_family_index_ >= family_write_tasks_.size()) {
    return true;
  }
  const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
  const FixedAxiPort *graph = ports_.graph[task.family];
  constexpr std::size_t kMaxGraphTasksPerAdvance = 12;
  constexpr std::size_t kMaxMetadataTasksPerAdvance = 4;
  const std::size_t graph_capacity = graph->requests().depth();
  const std::size_t metadata_capacity = ports_.metadata->requests().depth();
  return graph_capacity >= kMaxGraphTasksPerAdvance &&
         metadata_capacity >= kMaxMetadataTasksPerAdvance &&
         queued_level_writer_tasks_for_port(graph) <=
             graph_capacity - kMaxGraphTasksPerAdvance &&
         queued_level_writer_tasks_for_port(ports_.metadata) <=
             metadata_capacity - kMaxMetadataTasksPerAdvance;
}

void SpineL0Maintenance::level_writer_append_page(std::uint32_t page) {
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  if (page >= metadata.page_count ||
      page > std::numeric_limits<std::uint16_t>::max() ||
      level_writer_.page_list_count >= metadata.page_count ||
      (level_writer_.have_last_page && page <= level_writer_.last_page)) {
    if (level_writer_.l0_mode) {
      ++counters_.l0_writer_validation_failures;
    } else {
      ++counters_.carry_cursor_validation_failures;
    }
    throw std::logic_error("invalid Spine level-writer page sequence");
  }
  const std::uint32_t word = level_writer_.page_list_count >> 2;
  const std::uint32_t lane = level_writer_.page_list_count & 3U;
  LevelPendingWord &pending = level_writer_.page_list;
  if (pending.valid && pending.index != word) {
    level_writer_flush_page_list();
  }
  if (!pending.valid) {
    pending.valid = true;
    pending.index = word;
    pending.value = 0;
  }
  pending.value |= static_cast<std::uint64_t>(page) << (lane * 16);
  ++level_writer_.page_list_count;
  if (!level_writer_.l0_mode) {
    ++active_carry_result_counters().page_ids_written;
  }
  level_writer_.last_page = page;
  level_writer_.have_last_page = true;
  if (lane == 3) {
    level_writer_flush_page_list();
  }
}

void SpineL0Maintenance::initialize_carry_level_writer(
    const FamilyWriteTask &task) {
  if (!active_writer_epoch_ready_ || active_writer_next_epoch_ == 0) {
    ++counters_.slice_epoch_validation_failures;
    throw std::logic_error("Spine carry writer has no prepared epoch");
  }
  level_writer_ = LevelWriterState{};
  level_writer_.initialized = true;
  level_writer_.layout = spine_level_layout(config_, task.hot, task.target);
  auto &output = task.hot ? hot_family_outputs_[task.family]
                          : family_outputs_[task.family];
  level_writer_.was_active = !output.empty();
  level_writer_.expected_rows = static_cast<std::uint32_t>(
      task.hot ? counters_.hot_family_rows[task.family]
               : counters_.family_rows[task.family]);
  level_writer_.expected_edges = static_cast<std::uint32_t>(
      task.hot ? counters_.hot_family_edges[task.family]
               : counters_.family_edges[task.family]);
  output.clear();

  level_writer_.epoch = active_writer_next_epoch_;
}

void SpineL0Maintenance::initialize_l0_level_writer(
    const FamilyWriteTask &task) {
  if (!active_writer_epoch_ready_ || active_writer_next_epoch_ == 0) {
    ++counters_.slice_epoch_validation_failures;
    throw std::logic_error("Spine L0 writer has no prepared epoch");
  }
  level_writer_ = LevelWriterState{};
  level_writer_.initialized = true;
  level_writer_.l0_mode = true;
  level_writer_.expected_rows = static_cast<std::uint32_t>(
      task.hot ? counters_.hot_family_rows[task.family]
               : counters_.family_rows[task.family]);
  level_writer_.expected_edges = static_cast<std::uint32_t>(
      task.hot ? counters_.hot_family_edges[task.family]
               : counters_.family_edges[task.family]);
  level_writer_.layout = spine_slice_layout(
      config_, task.hot, task.target, level_writer_.expected_rows);
  auto &output = task.hot ? hot_family_outputs_[task.family]
                          : family_outputs_[task.family];
  level_writer_.was_active = !output.empty();
  output.clear();

  level_writer_.epoch = active_writer_next_epoch_;
}

void SpineL0Maintenance::accumulate_level_writer(
    const SpineEdgeRecord &entry) {
  if (level_writer_.group_valid && level_writer_.group.src == entry.src &&
      level_writer_.group.dst == entry.dst) {
    level_writer_.group_diff += entry.diff;
    level_writer_.group.weight =
        std::min(level_writer_.group.weight, entry.weight);
    return;
  }
  if (level_writer_.group_valid) {
    emit_level_writer_group(family_write_tasks_[active_family_index_]);
  }
  level_writer_.group = entry;
  level_writer_.group_diff = entry.diff;
  level_writer_.group_valid = true;
}

void SpineL0Maintenance::emit_level_writer_group(
    const FamilyWriteTask &task) {
  if (!level_writer_.group_valid) {
    return;
  }
  ++level_writer_.stats.groups_seen;
  const SpineEdgeRecord group = level_writer_.group;
  const std::int64_t diff = level_writer_.group_diff;
  level_writer_.group_valid = false;
  level_writer_.group_diff = 0;
  if (diff == 0) {
    ++level_writer_.stats.groups_cancelled;
    return;
  }
  if (diff < std::numeric_limits<std::int16_t>::min() ||
      diff > std::numeric_limits<std::int16_t>::max()) {
    throw std::overflow_error("Spine level-writer differential exceeds int16");
  }
  if (level_writer_.edge_index >= level_writer_.layout.edge_capacity) {
    if (level_writer_.l0_mode) {
      ++counters_.l0_writer_validation_failures;
    }
    begin_logical_overflow("Spine level writer exceeds target edge capacity",
                           SpineDirtyStatus::kOk);
    return;
  }

  if (!level_writer_.have_last_source ||
      group.src != level_writer_.last_source) {
    level_writer_write_u32(
        level_writer_.layout.row_offset_offset_words,
        level_writer_.row_index, level_writer_.edge_index, level_writer_.row,
        level_writer_.stats.row_word_writes);

    const std::uint32_t page = group.src / config_.page_vertices;
    if (level_writer_.bitmap_valid && page != level_writer_.bitmap_page) {
      level_writer_flush_bitmap();
    }
    if (!level_writer_.bitmap_valid) {
      level_writer_.bitmap_valid = true;
      level_writer_.bitmap_page = page;
      level_writer_.bitmap.fill(0);
    }
    const std::uint32_t in_page = group.src % config_.page_vertices;
    level_writer_.bitmap[in_page >> 6] |=
        std::uint64_t{1} << (in_page & 63U);

    if (!level_writer_.have_last_page || page != level_writer_.last_page) {
      level_writer_append_page(page);
      const std::size_t logical_family =
          task.hot ? config_.partitions + task.family : task.family;
      const SpineMetadataLayout metadata = spine_metadata_layout(config_);
      const std::uint64_t slice =
          logical_family * config_.levels + task.target;
      const std::uint64_t epoch_index = slice * metadata.page_count + page;
      page_epochs_[epoch_index] = level_writer_.epoch;
      const std::uint64_t low_index = epoch_index & ~std::uint64_t{1};
      const auto low = page_epochs_.find(low_index);
      const auto high = page_epochs_.find(low_index + 1);
      const std::uint64_t packed =
          (low == page_epochs_.end() ? 0 : low->second) |
          (static_cast<std::uint64_t>(
               high == page_epochs_.end() ? 0 : high->second)
           << 32);
      enqueue_task(
          *ports_.metadata, MemoryOperation::kWrite,
          config_.metadata_base +
              (metadata.page_epoch_base + (epoch_index >> 1)) *
                  kMetadataWordBytes,
          kMetadataWordBytes, TaskClass::kMetadata,
          encode_u64_words({packed}), {}, false,
          TaskPurpose::kLevelWriterMetadataWrite);
      ++level_writer_.stats.page_epoch_word_writes;
      ++counters_.pages_stamped;
      level_writer_write_u32(
          level_writer_.layout.page_base_offset_words, page,
          level_writer_.row_index, level_writer_.page_base,
          level_writer_.stats.page_base_word_writes);
    }
    level_writer_.current_mask_index = level_writer_.row_index;
    level_writer_.current_mask = 0;
    ++level_writer_.row_index;
    level_writer_.last_source = group.src;
    level_writer_.have_last_source = true;
  }

  const std::size_t partition = std::min<std::size_t>(
      group.dst / config_.vertex_partition_size, config_.partitions - 1);
  const std::uint16_t next_mask = static_cast<std::uint16_t>(
      level_writer_.current_mask | (std::uint16_t{1} << partition));
  if (next_mask != level_writer_.current_mask) {
    level_writer_.current_mask = next_mask;
    level_writer_write_u16(
        level_writer_.layout.mask_offset_words,
        level_writer_.current_mask_index, level_writer_.current_mask,
        level_writer_.mask, level_writer_.stats.mask_word_writes);
  }

  SpineEdgeRecord output = group;
  output.diff = static_cast<std::int16_t>(diff);
  std::vector<std::uint8_t> payload = encode_spine_level_edge(output);
  enqueue_task(
      *ports_.graph[task.family], MemoryOperation::kWrite,
      (level_writer_.layout.edge_offset_words + level_writer_.edge_index) *
          kSpineGraphWordBytes,
      kSpineGraphWordBytes, TaskClass::kGraph, std::move(payload), {}, false,
      TaskPurpose::kLevelWriterGraphWrite);
  counters_.graph_edge_payload_write_bytes += kSpineGraphWordBytes;
  ++level_writer_.stats.edge_word_writes;
  ++level_writer_.stats.groups_emitted;
  if (!level_writer_.l0_mode) {
    ++counters_.carry_outputs;
  }
  ++level_writer_.edge_index;
  auto &output_level = task.hot ? hot_family_outputs_[task.family]
                                : family_outputs_[task.family];
  output_level.push_back(output);
}

void SpineL0Maintenance::finalize_level_writer(
    const FamilyWriteTask &task) {
  if (!level_writer_.initialized || level_writer_.finalized) {
    throw std::logic_error("invalid Spine level-writer finalization");
  }
  emit_level_writer_group(task);
  if (logical_overflow_) {
    return;
  }
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  level_writer_write_u32(
      level_writer_.layout.row_offset_offset_words, level_writer_.row_index,
      level_writer_.edge_index, level_writer_.row,
      level_writer_.stats.row_word_writes);
  level_writer_write_u32(
      level_writer_.layout.page_base_offset_words,
      static_cast<std::uint32_t>(metadata.page_count),
      level_writer_.row_index, level_writer_.page_base,
      level_writer_.stats.page_base_word_writes);
  level_writer_flush_graph_word(
      level_writer_.layout.row_offset_offset_words, level_writer_.row,
      level_writer_.stats.row_word_writes);
  level_writer_flush_graph_word(
      level_writer_.layout.mask_offset_words, level_writer_.mask,
      level_writer_.stats.mask_word_writes);
  level_writer_flush_graph_word(
      level_writer_.layout.page_base_offset_words, level_writer_.page_base,
      level_writer_.stats.page_base_word_writes);
  level_writer_flush_bitmap();
  level_writer_flush_page_list();

  const std::size_t logical_family =
      task.hot ? config_.partitions + task.family : task.family;
  page_list_counts_[logical_family][task.target] =
      level_writer_.page_list_count;
  counters_.persisted_edges += level_writer_.edge_index;
  counters_.persisted_rows += level_writer_.row_index;
  if (task.hot) {
    counters_.hot_family_edges[task.family] = level_writer_.edge_index;
    counters_.hot_family_rows[task.family] = level_writer_.row_index;
  } else {
    counters_.family_edges[task.family] = level_writer_.edge_index;
    counters_.family_rows[task.family] = level_writer_.row_index;
  }
  const bool is_active = level_writer_.edge_index != 0;
  if (is_active) {
    slice_epochs_[logical_family][task.target] = level_writer_.epoch;
  }
  if (level_writer_.was_active && !is_active) {
    --counters_.active_families;
  } else if (!level_writer_.was_active && is_active) {
    ++counters_.active_families;
  }
  if (is_active != (level_writer_.page_list_count != 0)) {
    if (level_writer_.l0_mode) {
      ++counters_.l0_writer_validation_failures;
    } else {
      ++counters_.carry_cursor_validation_failures;
    }
    throw std::logic_error("Spine level-writer page-list occupancy mismatch");
  }
  if (level_writer_.l0_mode &&
      (level_writer_.row_index != level_writer_.expected_rows ||
       level_writer_.edge_index != level_writer_.expected_edges)) {
    ++counters_.l0_writer_validation_failures;
    throw std::logic_error("Spine level-writer output diverged from precount");
  }

  const LevelWriterStats &stats = level_writer_.stats;
  if (level_writer_.l0_mode) {
    counters_.l0_writer_groups_seen += stats.groups_seen;
    counters_.l0_writer_groups_emitted += stats.groups_emitted;
    counters_.l0_writer_groups_cancelled += stats.groups_cancelled;
    counters_.l0_writer_edge_word_writes += stats.edge_word_writes;
    counters_.l0_writer_row_word_writes += stats.row_word_writes;
    counters_.l0_writer_mask_word_writes += stats.mask_word_writes;
    counters_.l0_writer_page_base_word_writes +=
        stats.page_base_word_writes;
    counters_.l0_writer_bitmap_page_writes += stats.bitmap_page_writes;
    counters_.l0_writer_page_list_word_writes +=
        stats.page_list_word_writes;
    counters_.l0_writer_page_epoch_word_writes +=
        stats.page_epoch_word_writes;
  } else {
    counters_.carry_writer_groups_seen += stats.groups_seen;
    counters_.carry_writer_groups_emitted += stats.groups_emitted;
    counters_.carry_writer_groups_cancelled += stats.groups_cancelled;
    counters_.carry_writer_edge_word_writes += stats.edge_word_writes;
    counters_.carry_writer_row_word_writes += stats.row_word_writes;
    counters_.carry_writer_mask_word_writes += stats.mask_word_writes;
    counters_.carry_writer_page_base_word_writes +=
        stats.page_base_word_writes;
    counters_.carry_writer_bitmap_page_writes += stats.bitmap_page_writes;
    counters_.carry_writer_page_list_word_writes +=
        stats.page_list_word_writes;
    counters_.carry_writer_page_epoch_word_writes +=
        stats.page_epoch_word_writes;
    active_carry_result_counters().outputs += stats.groups_emitted;
  }
  level_writer_.finalized = true;
}

SpineL0Maintenance::CarryResultCounters &
SpineL0Maintenance::active_carry_result_counters() {
  if (active_family_index_ >= family_write_tasks_.size()) {
    throw std::logic_error("Spine carry counter has no active family");
  }
  return carry_result_counters_[family_write_tasks_[active_family_index_].hot
                                    ? 1
                                    : 0];
}

void SpineL0Maintenance::initialize_carry_engine(
    const FamilyWriteTask &task) {
  carry_streams_.clear();
  carry_cursor_refill_cycles_remaining_ = 0;
  initialize_carry_level_writer(task);
  CarryInputStream new_batch;
  new_batch.new_batch = true;
  carry_streams_.push_back(std::move(new_batch));

  const auto &levels = task.hot ? state_.hot_levels : state_.cold_levels;
  for (std::size_t level = 0; level < task.target; ++level) {
    const auto &edges = levels[task.family][level];
    if (edges.empty()) {
      continue;
    }
    CarryInputStream stream;
    stream.level = level;
    carry_streams_.push_back(std::move(stream));
  }

  for (std::size_t stream = 0; stream < carry_streams_.size(); ++stream) {
    if (carry_streams_[stream].new_batch) {
      enqueue_carry_stream_refill(stream);
    } else {
      enqueue_carry_cursor_metadata(stream);
    }
  }
}

void SpineL0Maintenance::enqueue_carry_stream_refill(
    std::size_t stream_index) {
  if (stream_index >= carry_streams_.size()) {
    throw std::logic_error("invalid Spine carry stream index");
  }
  CarryInputStream &stream = carry_streams_[stream_index];
  if (stream.request_pending) {
    return;
  }

  const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
  if (stream.new_batch) {
    if (!stream.buffered.empty()) {
      return;
    }
    const std::size_t logical_family =
        task.hot ? config_.partitions + task.family : task.family;
    const bool candidate =
        config_.maintenance_architecture ==
        SpineMaintenanceArchitecture::kCandidate10OnePass;
    const std::size_t new_batch_edges =
        candidate ? candidate_family_buckets_[logical_family].size()
                  : workload_.edges.size();
    if (stream.next_index >= new_batch_edges) {
      stream.exhausted = true;
      return;
    }
    const std::size_t edge_index = stream.next_index++;
    stream.request_pending = true;
    const std::uint64_t base =
        candidate
            ? config_.persistent_family_bucket_base +
                  static_cast<std::uint64_t>(
                      candidate_family_begin_[logical_family]) *
                      kSpineSortWordBytes
            : config_.sorted_edges_base;
    enqueue_task(*ports_.sorted_edges, MemoryOperation::kRead,
                 base + edge_index * kSpineSortWordBytes,
                 kSpineSortWordBytes, TaskClass::kSorted, {}, {}, false,
                 TaskPurpose::kCarryNewBatchRead, 0, stream_index, edge_index);
    return;
  }

  if (stream.buffered.size() >= 2) {
    return;
  }
  if (!stream.cursor_ready) {
    return;
  }
  if (stream.next_index >= stream.sources.size()) {
    stream.exhausted = true;
    return;
  }
  const std::size_t edge_index = stream.next_index++;
  const std::uint32_t source = stream.sources[edge_index];
  stream.request_pending = true;
  enqueue_task(*ports_.graph[task.family], MemoryOperation::kRead,
               (stream.edge_offset_words + edge_index) *
                   kSpineGraphWordBytes,
               kSpineGraphWordBytes, TaskClass::kGraph, {}, {}, false,
               TaskPurpose::kCarryLevelEdgeRead, source, stream_index,
               edge_index);
}

void SpineL0Maintenance::consume_carry_memory_response(
    const MemoryTask &task, const AxiResponse &response) {
  if (task.purpose == TaskPurpose::kLevelWriterGraphWrite ||
      task.purpose == TaskPurpose::kLevelWriterMetadataWrite) {
    if (task.operation != MemoryOperation::kWrite ||
        !response.read_data.empty()) {
      throw std::logic_error("invalid Spine level-writer response");
    }
    return;
  }
  if (task.carry_stream >= carry_streams_.size()) {
    throw std::logic_error("Spine carry response has invalid stream index");
  }
  CarryInputStream &stream = carry_streams_[task.carry_stream];
  const bool edge_response =
      task.purpose == TaskPurpose::kCarryNewBatchRead ||
      task.purpose == TaskPurpose::kCarryLevelEdgeRead;
  if (edge_response) {
    if (!stream.request_pending) {
      throw std::logic_error("unexpected Spine carry stream response");
    }
    if (task.purpose != TaskPurpose::kCarryNewBatchRead ||
        !metadata_hot_enabled_) {
      stream.request_pending = false;
    }
  }

  const FamilyWriteTask &active =
      family_write_tasks_[active_family_index_];
  const std::size_t logical_family =
      active.hot ? config_.partitions + active.family : active.family;
  const std::uint64_t slice =
      logical_family * config_.levels + stream.level;
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  const auto finish_page_index_response = [&] {
    if (stream.page_index_responses_pending == 0) {
      throw std::logic_error("too many Spine carry page-index responses");
    }
    --stream.page_index_responses_pending;
    if (stream.page_index_responses_pending == 0) {
      finalize_carry_page_indexes(task.carry_stream);
    }
  };

  if (task.purpose == TaskPurpose::kCarryNewBatchRead) {
    if (!stream.new_batch || response.read_data.size() != kSpineSortWordBytes) {
      throw std::logic_error("invalid Spine new-batch carry response");
    }
    const SpineEdgeRecord edge = decode_spine_sort_edge(response.read_data);
    ++counters_.carry_new_batch_reads;
    counters_.carry_new_batch_read_bytes += response.read_data.size();
    counters_.sorted_payload_read_bytes += response.read_data.size();
    if (config_.maintenance_architecture ==
        SpineMaintenanceArchitecture::kCandidate10OnePass) {
      stream.buffered.push_back(edge);
    } else if (metadata_hot_enabled_) {
      enqueue_carry_hot_bitmap_read(task.carry_stream, edge);
    } else {
      const std::size_t family = family_for(edge.dst);
      if (!active.hot && family == active.family) {
        stream.buffered.push_back(edge);
      } else {
        enqueue_carry_stream_refill(task.carry_stream);
      }
    }
  } else if (task.purpose == TaskPurpose::kCarryCursorSliceMetadata) {
    if (stream.new_batch || response.read_data.size() != 8 * kMetadataWordBytes) {
      throw std::logic_error("invalid Spine carry slice metadata response");
    }
    counters_.carry_cursor_metadata_read_bytes += response.read_data.size();
    const std::uint64_t edge_count = read_u64_le(response.read_data, 0);
    const std::uint64_t row_count = read_u64_le(response.read_data, 8);
    const std::uint64_t occupied = read_u64_le(response.read_data, 56);
    if (edge_count == 0 || edge_count > std::numeric_limits<std::uint32_t>::max() ||
        row_count == 0 || row_count > edge_count ||
        row_count > std::numeric_limits<std::uint32_t>::max() || occupied == 0) {
      ++counters_.carry_cursor_validation_failures;
      throw std::logic_error("invalid Spine carry slice shape");
    }
    stream.edge_count = static_cast<std::uint32_t>(edge_count);
    stream.row_count = static_cast<std::uint32_t>(row_count);
    stream.bitmap_offset_words = read_u64_le(response.read_data, 16);
    stream.page_base_offset_words = read_u64_le(response.read_data, 24);
    stream.row_offset_offset_words = read_u64_le(response.read_data, 32);
    stream.edge_offset_words = read_u64_le(response.read_data, 48);
    enqueue_task(*ports_.metadata, MemoryOperation::kRead,
                 config_.metadata_base +
                     (metadata.slice_epoch_base + (slice >> 1)) *
                         kMetadataWordBytes,
                 kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
                 TaskPurpose::kCarryCursorSliceEpoch, 0, task.carry_stream);
    enqueue_task(*ports_.metadata, MemoryOperation::kRead,
                 config_.metadata_base +
                     (metadata.page_list_count_base + (slice >> 1)) *
                         kMetadataWordBytes,
                 kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
                 TaskPurpose::kCarryCursorPageCount, 0, task.carry_stream);
  } else if (task.purpose == TaskPurpose::kCarryCursorSliceEpoch) {
    counters_.carry_cursor_metadata_read_bytes += response.read_data.size();
    stream.slice_epoch =
        read_u32_le(response.read_data, (slice & 1U) * sizeof(std::uint32_t));
    stream.slice_epoch_ready = true;
    maybe_enqueue_carry_page_list(task.carry_stream);
  } else if (task.purpose == TaskPurpose::kCarryCursorPageCount) {
    counters_.carry_cursor_metadata_read_bytes += response.read_data.size();
    stream.page_count =
        read_u32_le(response.read_data, (slice & 1U) * sizeof(std::uint32_t));
    stream.page_count_ready = true;
    maybe_enqueue_carry_page_list(task.carry_stream);
  } else if (task.purpose == TaskPurpose::kCarryCursorPageList) {
    counters_.carry_cursor_metadata_read_bytes += response.read_data.size();
    stream.pages.clear();
    stream.pages.reserve(stream.page_count);
    for (std::size_t index = 0; index < stream.page_count; ++index) {
      const std::uint32_t page =
          static_cast<std::uint32_t>(response.read_data[index * 2]) |
          (static_cast<std::uint32_t>(response.read_data[index * 2 + 1]) << 8);
      if (page >= metadata.page_count ||
          (!stream.pages.empty() && page <= stream.pages.back())) {
        ++counters_.carry_cursor_validation_failures;
        throw std::logic_error("invalid Spine carry page-list payload");
      }
      stream.pages.push_back(page);
    }
    counters_.carry_cursor_page_ids += stream.pages.size();
    enqueue_carry_page_indexes(task.carry_stream);
  } else if (task.purpose == TaskPurpose::kCarryCursorPageEpoch) {
    counters_.carry_cursor_metadata_read_bytes += response.read_data.size();
    if (task.carry_edge_index >= stream.page_epochs.size()) {
      throw std::logic_error("invalid Spine carry page-epoch response index");
    }
    const std::uint64_t epoch_index = slice * metadata.page_count + task.source;
    stream.page_epochs[task.carry_edge_index] = read_u32_le(
        response.read_data, (epoch_index & 1U) * sizeof(std::uint32_t));
    finish_page_index_response();
  } else if (task.purpose == TaskPurpose::kCarryCursorPageBase) {
    if (task.carry_edge_index >= stream.page_bases.size()) {
      throw std::logic_error("invalid Spine carry page-base response index");
    }
    stream.page_bases[task.carry_edge_index] = read_u32_le(
        response.read_data, (task.source & 1U) * sizeof(std::uint32_t));
    finish_page_index_response();
  } else if (task.purpose == TaskPurpose::kCarryCursorBitmap) {
    if (task.carry_edge_index >= stream.page_bitmaps.size() ||
        response.read_data.size() != 4 * kSpineGraphWordBytes) {
      throw std::logic_error("invalid Spine carry bitmap response");
    }
    for (std::size_t word = 0; word < 4; ++word) {
      stream.page_bitmaps[task.carry_edge_index][word] =
          read_u64_le(response.read_data, word * kSpineGraphWordBytes);
    }
    ++counters_.carry_cursor_pages_visited;
    ++active_carry_result_counters().pages_visited;
    counters_.carry_cursor_bitmap_words += 4;
    finish_page_index_response();
  } else if (task.purpose == TaskPurpose::kCarryCursorRowOffsets) {
    const std::vector<std::uint32_t> row_sources = stream.sources;
    std::vector<std::uint32_t> edge_sources;
    edge_sources.reserve(stream.edge_count);
    std::uint32_t expected_start = 0;
    for (std::size_t row = 0; row < stream.row_count; ++row) {
      const std::uint32_t start =
          read_u32_le(response.read_data, row * sizeof(std::uint32_t));
      const std::uint32_t end =
          read_u32_le(response.read_data, (row + 1) * sizeof(std::uint32_t));
      if (start != expected_start || end <= start || end > stream.edge_count) {
        ++counters_.carry_cursor_validation_failures;
        throw std::logic_error("invalid Spine carry row-offset payload");
      }
      edge_sources.insert(edge_sources.end(), end - start, row_sources[row]);
      expected_start = end;
    }
    if (expected_start != stream.edge_count ||
        edge_sources.size() != stream.edge_count) {
      ++counters_.carry_cursor_validation_failures;
      throw std::logic_error("Spine carry terminal row offset mismatch");
    }
    counters_.carry_cursor_row_offset_reads += stream.row_count + 1;
    counters_.carry_cursor_rows_entered += stream.row_count;
    active_carry_result_counters().rows_entered += stream.row_count;
    stream.sources = std::move(edge_sources);
    stream.cursor_ready = true;
    enqueue_carry_stream_refill(task.carry_stream);
  } else if (task.purpose == TaskPurpose::kCarryLevelEdgeRead) {
    if (stream.new_batch || response.read_data.size() != kSpineGraphWordBytes) {
      throw std::logic_error("invalid Spine level carry response");
    }
    stream.buffered.push_back(
        decode_spine_level_edge(response.read_data, task.source));
    ++counters_.carry_level_payload_reads;
    ++active_carry_result_counters().payload_reads;
    counters_.carry_level_payload_read_bytes += response.read_data.size();
    enqueue_carry_stream_refill(task.carry_stream);
  } else {
    throw std::logic_error("non-carry task reached the carry response handler");
  }

  std::size_t buffered = 0;
  for (const CarryInputStream &candidate : carry_streams_) {
    buffered += candidate.buffered.size();
  }
  counters_.carry_max_buffered_heads =
      std::max(counters_.carry_max_buffered_heads, buffered);
}

bool SpineL0Maintenance::advance_carry_merge() {
  std::size_t winner = carry_streams_.size();
  for (std::size_t stream = 0; stream < carry_streams_.size(); ++stream) {
    if (carry_streams_[stream].buffered.empty()) {
      continue;
    }
    if (winner == carry_streams_.size() ||
        std::pair(carry_streams_[stream].buffered.front().src,
                  carry_streams_[stream].buffered.front().dst) <
            std::pair(carry_streams_[winner].buffered.front().src,
                      carry_streams_[winner].buffered.front().dst)) {
      winner = stream;
    }
  }
  if (winner == carry_streams_.size()) {
    const bool complete =
        std::all_of(carry_streams_.begin(), carry_streams_.end(),
                    [](const CarryInputStream &stream) {
                      return stream.exhausted && !stream.request_pending &&
                             stream.buffered.empty();
                    });
    if (!complete) {
      throw std::logic_error("Spine carry merge lost a refill request");
    }
    finalize_level_writer(family_write_tasks_[active_family_index_]);
    return true;
  }

  CarryInputStream &stream = carry_streams_[winner];
  accumulate_level_writer(stream.buffered.front());
  stream.buffered.pop_front();
  ++counters_.carry_merge_inputs;
  ++active_carry_result_counters().merge_inputs;
  enqueue_carry_stream_refill(winner);
  return false;
}

void SpineL0Maintenance::finish_carry_merge(const FamilyWriteTask &task) {
  if (!level_writer_.finalized) {
    throw std::logic_error("Spine carry merge finished before its writer");
  }
  (void)task;
}

void SpineL0Maintenance::commit_level_state(bool hot, std::size_t target) {
  auto &levels = hot ? state_.hot_levels : state_.cold_levels;
  const auto &outputs = hot ? hot_family_outputs_ : family_outputs_;
  for (std::size_t family = 0; family < config_.partitions; ++family) {
    const std::size_t logical_family =
        hot ? config_.partitions + family : family;
    levels[family][target] = outputs[family];
    if (outputs[family].empty()) {
      page_list_counts_[logical_family][target] = 0;
    }
    for (std::size_t level = 0; level < target; ++level) {
      levels[family][level].clear();
      page_list_counts_[logical_family][level] = 0;
    }
  }
}

void SpineL0Maintenance::enqueue_committed_metadata() {
  const SpineMetadataLayout metadata = spine_metadata_layout(config_);
  std::set<std::uint64_t> slice_epoch_words;
  std::set<std::uint64_t> page_list_count_words;
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
          const std::uint64_t rows = row_count_for_edges(edges);
          const SpineLevelLayout layout =
              spine_slice_layout(config_, hot, level, rows);
          payload = encode_u64_words(
              {edges.size(), rows,
               layout.bitmap_offset_words, layout.page_base_offset_words,
               layout.row_offset_offset_words, layout.mask_offset_words,
               layout.edge_offset_words, 1});
        }
        const std::uint64_t bytes = payload.size();
        enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                     config_.metadata_base + slice * 8 * kMetadataWordBytes,
                     bytes, TaskClass::kMetadata, std::move(payload));
        slice_epoch_words.insert(slice >> 1);
        page_list_count_words.insert(slice >> 1);
      }
    }
  };
  publish(false, static_cast<std::size_t>(counters_.target_level));
  if (metadata_hot_enabled_) {
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
  for (const std::uint64_t word : page_list_count_words) {
    const std::uint64_t low_index = word * 2;
    const std::size_t low_family = low_index / config_.levels;
    const std::size_t low_level = low_index % config_.levels;
    std::uint64_t packed = page_list_counts_[low_family][low_level];
    if (low_index + 1 < metadata.slice_count) {
      const std::uint64_t high_index = low_index + 1;
      packed |= static_cast<std::uint64_t>(
                    page_list_counts_[high_index / config_.levels]
                                     [high_index % config_.levels])
                << 32;
    }
    counters_.page_list_count_write_bytes += kMetadataWordBytes;
    enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                 config_.metadata_base +
                     (metadata.page_list_count_base + word) *
                         kMetadataWordBytes,
                 kMetadataWordBytes, TaskClass::kMetadata,
                 encode_u64_words({packed}));
  }
}

void SpineL0Maintenance::advance(const CycleContext &context) {
  switch (phase_) {
  case Phase::kFullRebuildClear:
    phase_ = Phase::kInitialize;
    return;
  case Phase::kInitialize:
    if (!full_rebuild_mode_) {
      counters_.start_cycle = context.domain_cycle;
    }
    enqueue_task(*ports_.metadata, MemoryOperation::kRead,
                 config_.metadata_base +
                     spine_metadata_layout(config_).hot_enabled_word *
                         kMetadataWordBytes,
                 kMetadataWordBytes, TaskClass::kMetadata, {}, {}, false,
                 TaskPurpose::kMetadataControl);
    enqueue_dirty_metadata_load();
    phase_ = Phase::kDirtyMetadataLoad;
    return;
  case Phase::kDirtyMetadataLoad:
    phase_ = Phase::kDirtyPreflightBegin;
    return;
  case Phase::kDirtyPreflightBegin:
    begin_sorted_scan(Phase::kDirtyPreflightProcess, ScanKind::kDirtyValidate);
    return;
  case Phase::kDirtyPreflightProcess:
    if (process_scan_edge(context)) {
      phase_ = config_.maintenance_architecture ==
                       SpineMaintenanceArchitecture::kCandidate10OnePass
                   ? Phase::kCandidateClassifyBegin
                   : Phase::kDirtyGenerationPrepare;
    }
    return;
  case Phase::kDirtyGenerationPrepare:
    enqueue_dirty_generation_prepare();
    phase_ = Phase::kDirtyUpdateBegin;
    return;
  case Phase::kDirtyUpdateBegin:
    begin_sorted_scan(Phase::kDirtyUpdateProcess, ScanKind::kDirtyMark);
    return;
  case Phase::kDirtyUpdateProcess:
    if (process_scan_edge(context)) {
      phase_ = Phase::kDirtyFinalize;
    }
    return;
  case Phase::kDirtyFinalize:
    enqueue_dirty_final_metadata();
    phase_ = Phase::kHotColdCountBegin;
    return;
  case Phase::kCandidateClassifyBegin:
    candidate_family_tags_.assign(sorted_scan_edges_.size(), 0);
    candidate_family_begin_ = {};
    candidate_source_records_.clear();
    candidate_classify_block_records_.clear();
    candidate_block_begin_ = 0;
    candidate_have_source_ = false;
    candidate_current_source_mask_ = 0;
    candidate_classified_tag_hash_ = 0;
    begin_sorted_scan(Phase::kCandidateClassifyProcess,
                      ScanKind::kCandidateClassify);
    return;
  case Phase::kCandidateClassifyProcess:
    if (process_scan_edge(context)) {
      if (candidate_source_records_.size() != counters_.unique_sources) {
        begin_logical_overflow("candidate classify source count mismatch",
                               SpineDirtyStatus::kInvalidState);
        return;
      }
      candidate_prefix_cycles_remaining_ = kSpineFamilyCount;
      phase_ = Phase::kCandidatePrefix;
    }
    return;
  case Phase::kCandidateClassifyReduce:
    if (candidate_reduce_cycles_remaining_ == 0) {
      throw std::logic_error("candidate reduce phase has no work");
    }
    --candidate_reduce_cycles_remaining_;
    ++counters_.candidate_reduce_edge_visits;
    if (candidate_reduce_cycles_remaining_ == 0) {
      candidate_finish_classify_block();
      phase_ = Phase::kCandidateClassifyFlush;
    }
    return;
  case Phase::kCandidateClassifyFlush:
    candidate_classify_flush_pending_ = false;
    phase_ = Phase::kCandidateClassifyProcess;
    return;
  case Phase::kCandidatePrefix:
    if (candidate_prefix_cycles_remaining_ == 0) {
      throw std::logic_error("candidate prefix phase has no work");
    }
    --candidate_prefix_cycles_remaining_;
    ++counters_.candidate_prefix_iterations;
    if (candidate_prefix_cycles_remaining_ == 0) {
      std::uint32_t running = 0;
      for (std::size_t family = 0; family < kSpineFamilyCount; ++family) {
        const std::uint32_t count = candidate_family_begin_[family + 1];
        candidate_family_begin_[family] = running;
        running += count;
      }
      candidate_family_begin_[kSpineFamilyCount] = running;
      candidate_family_cursor_ = {};
      for (std::size_t family = 0; family < kSpineFamilyCount; ++family) {
        candidate_family_cursor_[family] = candidate_family_begin_[family];
      }
      phase_ = Phase::kCandidateDispatchBegin;
    }
    return;
  case Phase::kCandidateDispatchBegin:
    for (auto &bucket : candidate_family_buckets_) {
      bucket.clear();
    }
    counters_.dispatch_status = 0;
    counters_.dispatch_input_reads = 0;
    counters_.dispatch_bucket_writes = 0;
    counters_.dispatch_cursor_mismatches = 0;
    counters_.dispatch_hash_sum = 0;
    counters_.dispatch_hash_xor = 0;
    candidate_dispatched_tag_hash_ = 0;
    begin_sorted_scan(Phase::kCandidateDispatchProcess,
                      ScanKind::kCandidateDispatch);
    return;
  case Phase::kCandidateDispatchProcess:
    if (process_scan_edge(context)) {
      phase_ = Phase::kCandidateDispatchValidate;
    }
    return;
  case Phase::kCandidateDispatchValidate: {
    for (std::size_t family = 0; family < kSpineFamilyCount; ++family) {
      if (candidate_family_cursor_[family] !=
          candidate_family_begin_[family + 1]) {
        counters_.dispatch_status = 3;
        ++counters_.dispatch_cursor_mismatches;
      }
    }
    if (counters_.dispatch_input_reads != sorted_scan_edges_.size() ||
        counters_.dispatch_bucket_writes != sorted_scan_edges_.size() ||
        candidate_dispatched_tag_hash_ != candidate_classified_tag_hash_) {
      counters_.dispatch_status = 3;
      ++counters_.dispatch_cursor_mismatches;
    }
    if (counters_.dispatch_status != 0) {
      begin_logical_overflow("candidate family dispatch validation failed",
                             SpineDirtyStatus::kInvalidState);
      return;
    }
    counters_.publication_fallback =
        static_cast<std::uint64_t>(dirty_count_) +
            candidate_source_records_.size() >
        config_.max_vertices;
    candidate_publication_empty_proven_ =
        dirty_count_ == 0 && dirty_hash_sum_ == 0 && dirty_hash_xor_ == 0 &&
        !candidate_dirty_candidate_valid_ && !candidate_dirty_host_valid_;
    counters_.publication_empty_frontier_fast_path =
        candidate_publication_empty_proven_;
    candidate_new_dirty_sources_.clear();
    candidate_probe_new_count_ = 0;
    phase_ = Phase::kCandidatePublicationBegin;
    return;
  }
  case Phase::kCandidatePublicationBegin:
    if (candidate_source_records_.empty()) {
      phase_ = Phase::kCandidateListBegin;
      return;
    }
    candidate_publication_kind_ = CandidatePublicationKind::kDirectory;
    candidate_begin_publication_pass();
    return;
  case Phase::kCandidatePublicationLoad:
    if (candidate_publication_responses_ != candidate_publication_loaded_) {
      throw std::logic_error("candidate source-record window did not close");
    }
    candidate_build_publication_groups();
    phase_ = Phase::kCandidatePublicationRead;
    return;
  case Phase::kCandidatePublicationRead: {
    const bool skipped =
        candidate_publication_kind_ == CandidatePublicationKind::kBitmap &&
        candidate_publication_empty_proven_;
    if (!skipped && candidate_publication_responses_ !=
                        candidate_publication_words_.size()) {
      throw std::logic_error("candidate publication read window did not close");
    }
    candidate_write_publication_groups();
    phase_ = Phase::kCandidatePublicationWrite;
    return;
  }
  case Phase::kCandidatePublicationWrite:
    phase_ = Phase::kCandidatePublicationAdvance;
    return;
  case Phase::kCandidatePublicationAdvance:
    candidate_advance_publication_pass();
    return;
  case Phase::kCandidateListBegin: {
    if (!candidate_publication_empty_proven_) {
      const SpineMetadataLayout metadata = spine_metadata_layout(config_);
      for (std::size_t base = 0; base < candidate_new_dirty_sources_.size();
           base += 2) {
        std::uint64_t packed = candidate_new_dirty_sources_[base];
        if (base + 1 < candidate_new_dirty_sources_.size()) {
          packed |= static_cast<std::uint64_t>(
                        candidate_new_dirty_sources_[base + 1])
                    << 32;
        }
        enqueue_task(
            *ports_.metadata, MemoryOperation::kWrite,
            config_.metadata_base +
                (metadata.new_dirty_base + base / 2) * kMetadataWordBytes,
            kMetadataWordBytes, TaskClass::kMetadata,
            encode_u64_words({packed}), {}, false,
            TaskPurpose::kCandidateScratchWrite, 0, 0, 0, 0, 0, base / 2);
        ++counters_.publication_scratch_word_writes;
      }
    }
    phase_ = Phase::kCandidateListSourceLoad;
    return;
  }
  case Phase::kCandidateListSourceLoad:
    candidate_begin_list_source_load();
    phase_ = Phase::kCandidateListRead;
    return;
  case Phase::kCandidateListRead:
    if (candidate_list_source_loaded_ != candidate_list_sources_.size() ||
        candidate_list_sources_ != candidate_new_dirty_sources_) {
      throw std::logic_error("candidate list source payload mismatch");
    }
    candidate_build_list_words();
    phase_ = Phase::kCandidateListWrite;
    return;
  case Phase::kCandidateListWrite:
    candidate_write_list_words();
    phase_ = Phase::kCandidateFinalize;
    return;
  case Phase::kCandidateFinalize: {
    for (const std::uint32_t source : candidate_list_sources_) {
      dirty_hash_sum_ += spine_dirty_hash_sum_term(source);
      dirty_hash_xor_ ^= spine_dirty_hash_xor_term(source);
    }
    dirty_count_ += static_cast<std::uint32_t>(candidate_list_sources_.size());
    enqueue_dirty_generation_prepare();
    enqueue_dirty_final_metadata();
    counters_.publication_complete = true;
    phase_ = Phase::kTargetSelect;
    return;
  }
  case Phase::kHotColdCountBegin:
    begin_sorted_scan(Phase::kHotColdCountProcess, ScanKind::kHotColdCount);
    return;
  case Phase::kHotColdCountProcess: {
    const std::size_t before = scan_index_;
    if (process_scan_edge(context)) {
      phase_ = Phase::kTargetSelect;
    } else if (scan_index_ != before) {
      const SpineEdgeRecord &edge = sorted_scan_edges_[before];
      if (edge_is_hot(edge.dst)) {
        ++counters_.hot_input_edges;
      } else {
        ++counters_.cold_input_edges;
      }
    }
    return;
  }
  case Phase::kTargetSelect:
    initialize_target_selector(false, context);
    enqueue_target_selector_level();
    phase_ = Phase::kTargetSelectLevelWait;
    return;
  case Phase::kTargetSelectLevelWait:
    resolve_target_selector_level(context);
    return;
  case Phase::kTargetSelectPadding:
    if (context.domain_cycle < target_scan_min_finish_cycle_) {
      ++counters_.target_selector_min_padding_cycles;
      return;
    }
    finish_target_selector(context);
    return;
  case Phase::kPrecountBegin:
    begin_sorted_scan(Phase::kPrecountProcess, ScanKind::kFamilyPrecount);
    return;
  case Phase::kPrecountProcess:
    if (process_scan_edge(context)) {
      ++family_index_;
      if (family_index_ == config_.partitions) {
        if (!precount_hot_ && metadata_hot_enabled_) {
          precount_hot_ = true;
          family_index_ = 0;
          phase_ = Phase::kPrecountBegin;
        } else {
          phase_ = Phase::kBuildOutputs;
        }
      } else {
        phase_ = Phase::kPrecountBegin;
      }
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
      enqueue_active_writer_epoch_read();
      phase_ = Phase::kWriteEpochResolve;
    }
    return;
  case Phase::kWriteEpochResolve:
    prepare_active_writer_epoch();
    if (active_writer_epoch_wrapped_) {
      phase_ = Phase::kWriteEpochClear;
    } else {
      begin_active_family_write();
    }
    return;
  case Phase::kWriteEpochClear:
    begin_active_family_write();
    return;
  case Phase::kWriteProcess: {
    const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
    const std::size_t before = scan_index_;
    if (process_scan_edge(context)) {
      finalize_level_writer(task);
      if (logical_overflow_) {
        return;
      }
      phase_ = Phase::kWriteAdvance;
    } else if (scan_index_ != before) {
      const SpineEdgeRecord &edge = sorted_scan_edges_[before];
      if (scan_kind_ == ScanKind::kCandidateBucketWrite) {
        accumulate_level_writer(edge);
      } else {
        const bool hot = edge_is_hot(edge.dst);
        const std::size_t family =
            hot ? spine_hot_shard(edge.dst) : family_for(edge.dst);
        if (hot == task.hot && family == task.family) {
          accumulate_level_writer(edge);
        }
      }
    }
    return;
  }
  case Phase::kCarryProcess: {
    if (carry_cursor_refill_cycles_remaining_ != 0) {
      --carry_cursor_refill_cycles_remaining_;
      ++counters_.carry_cursor_refill_cycles;
      return;
    }
    if (!advance_carry_merge()) {
      return;
    }
    const FamilyWriteTask &task = family_write_tasks_[active_family_index_];
    if (logical_overflow_) {
      return;
    }
    finish_carry_merge(task);
    phase_ = Phase::kWriteAdvance;
    return;
  }
  case Phase::kWriteAdvance:
    active_writer_epoch_ready_ = false;
    active_writer_epoch_wrapped_ = false;
    active_writer_current_epoch_ = 0;
    active_writer_next_epoch_ = 0;
    ++active_family_index_;
    phase_ = Phase::kWriteSelect;
    return;
  case Phase::kCommitMetadata:
    commit_level_state(false, static_cast<std::size_t>(counters_.target_level));
    if (metadata_hot_enabled_) {
      commit_level_state(true,
                         static_cast<std::size_t>(counters_.hot_target_level));
    }
    enqueue_committed_metadata();
    phase_ = Phase::kWriteResult;
    return;
  case Phase::kWriteResult:
    if (logical_overflow_ && enqueue_retired_writer_epochs()) {
      phase_ = Phase::kRetireEpochs;
      return;
    }
    enqueue_result_metadata_reads();
    phase_ = Phase::kCollectResult;
    return;
  case Phase::kRetireEpochs:
    enqueue_result_metadata_reads();
    phase_ = Phase::kCollectResult;
    return;
  case Phase::kCollectResult:
    enqueue_maintenance_result();
    phase_ = Phase::kFinish;
    return;
  case Phase::kFinish:
    counters_.end_cycle = context.domain_cycle;
    done_ = true;
    failed_ = logical_overflow_;
    return;
  }
}

} // namespace spine::sim
