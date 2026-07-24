#include "spine_sim/spine_l0.hpp"

#include <algorithm>
#include <fstream>
#include <limits>
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

}  // namespace

std::vector<std::uint8_t> encode_spine_sort_edge(
    const SpineEdgeRecord &edge) {
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

SpineEdgeRecord decode_spine_sort_edge(
    const std::vector<std::uint8_t> &data) {
  if (data.size() != kSpineSortWordBytes) {
    throw std::invalid_argument("Spine sorted edge payload must be 128 bits");
  }
  std::uint32_t dst = 0;
  std::uint32_t src = 0;
  for (std::size_t byte = 0; byte < sizeof(std::uint32_t); ++byte) {
    dst |= static_cast<std::uint32_t>(data[8 + byte]) << (byte * 8);
    src |= static_cast<std::uint32_t>(data[12 + byte]) << (byte * 8);
  }
  const std::uint16_t weight =
      static_cast<std::uint16_t>(data[4]) |
      (static_cast<std::uint16_t>(data[5]) << 8);
  const std::uint16_t diff =
      static_cast<std::uint16_t>(data[0]) |
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
              data.begin() + static_cast<std::ptrdiff_t>(
                                 index * kSpineSortWordBytes));
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
        data.begin() + static_cast<std::ptrdiff_t>(offset +
                                                   kSpineSortWordBytes))));
  }
  return edges;
}

std::vector<std::uint8_t> encode_spine_level_edge(
    const SpineEdgeRecord &edge) {
  const std::uint64_t packed =
      (static_cast<std::uint64_t>(edge.dst) << 32) |
      (static_cast<std::uint64_t>(edge.weight) << 16) |
      static_cast<std::uint16_t>(edge.diff);
  std::vector<std::uint8_t> data(kSpineGraphWordBytes);
  for (std::size_t byte = 0; byte < data.size(); ++byte) {
    data[byte] = static_cast<std::uint8_t>((packed >> (byte * 8)) & 0xffU);
  }
  return data;
}

SpineEdgeRecord decode_spine_level_edge(
    const std::vector<std::uint8_t> &data, std::uint32_t source) {
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
      config.page_vertices == 0 || config.max_vertices == 0 ||
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
      config_.page_vertices == 0 || config_.max_vertices == 0 ||
      config_.max_sort_edges == 0 || workload_.vertices == 0 ||
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
}

void SpineL0Maintenance::evaluate(const CycleContext &) {
  staged_action_ = StagedAction::kNone;
  if (done_ || failed_) {
    return;
  }
  if (waiting_) {
    if (tasks_.empty()) {
      throw std::logic_error("Spine memory wait has no task");
    }
    if (tasks_.front().port->responses().try_pop(staged_response_)) {
      staged_action_ = StagedAction::kComplete;
    }
    return;
  }
  if (!tasks_.empty()) {
    const MemoryTask &task = tasks_.front();
    if (task.port->requests().try_push(AxiRequest{
            .transaction_id = next_transaction_id_,
            .operation = task.operation,
            .address = task.address,
            .bytes = task.bytes,
            .write_data = task.write_data,
        })) {
      staged_action_ = StagedAction::kIssue;
    }
    return;
  }
  staged_action_ = StagedAction::kAdvance;
}

void SpineL0Maintenance::commit(const CycleContext &context) {
  switch (staged_action_) {
    case StagedAction::kNone:
      return;
    case StagedAction::kIssue:
      expected_transaction_id_ = next_transaction_id_++;
      waiting_ = true;
      return;
    case StagedAction::kComplete:
      if (staged_response_.transaction_id != expected_transaction_id_ ||
          !staged_response_.success) {
        failed_ = true;
        done_ = true;
        failure_ = "Spine AXI response failed or used the wrong transaction ID";
        return;
      }
      consume_memory_response(tasks_.front(), staged_response_);
      waiting_ = false;
      tasks_.pop_front();
      return;
    case StagedAction::kAdvance:
      advance(context);
      return;
  }
}

void SpineL0Maintenance::enqueue_task(FixedAxiPort &port,
                                      MemoryOperation operation,
                                      std::uint64_t address,
                                      std::uint64_t bytes,
                                      TaskClass task_class,
                                      std::vector<std::uint8_t> write_data) {
  if (bytes == 0) {
    return;
  }
  if ((operation == MemoryOperation::kRead && !write_data.empty()) ||
      (operation == MemoryOperation::kWrite && !write_data.empty() &&
       write_data.size() != bytes)) {
    throw std::invalid_argument("invalid Spine maintenance memory payload");
  }
  tasks_.push_back(MemoryTask{
      .port = &port,
      .operation = operation,
      .address = address,
      .bytes = bytes,
      .task_class = task_class,
      .write_data = std::move(write_data),
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
  enqueue_task(*ports_.sorted_edges, MemoryOperation::kRead,
               config_.sorted_edges_base,
               workload_.edges.size() * kSpineSortWordBytes,
               TaskClass::kSorted);
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

void SpineL0Maintenance::consume_memory_response(
    const MemoryTask &task, const AxiResponse &response) {
  if (task.operation == MemoryOperation::kWrite) {
    if (!response.read_data.empty()) {
      throw std::logic_error("Spine maintenance write response carried payload");
    }
    return;
  }
  if (response.read_data.size() != task.bytes) {
    throw std::logic_error("Spine maintenance read response payload mismatch");
  }
  if (task.task_class == TaskClass::kSorted) {
    sorted_scan_edges_ = decode_spine_sort_edges(response.read_data);
    counters_.sorted_payload_read_bytes += response.read_data.size();
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
  for (std::size_t index = 0; index < sources.size(); ++index) {
    const std::uint32_t src = sources[index];
    const std::uint64_t directory =
        config_.persistent_directory_base + (src >> 2) * kPersistentRecordBytes;
    const std::uint64_t bitmap =
        config_.persistent_dirty_bitmap_base +
        (src >> 7) * kPersistentRecordBytes;
    const std::uint64_t list =
        config_.persistent_dirty_list_base +
        (index >> 2) * kPersistentRecordBytes;
    for (const std::uint64_t address : {directory, bitmap, list}) {
      enqueue_task(*ports_.sorted_edges, MemoryOperation::kRead, address,
                   kPersistentRecordBytes, TaskClass::kPersistent);
      enqueue_task(*ports_.sorted_edges, MemoryOperation::kWrite, address,
                   kPersistentRecordBytes, TaskClass::kPersistent);
    }
  }
  enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
               config_.metadata_base + 32 * kMetadataWordBytes,
               7 * kMetadataWordBytes, TaskClass::kMetadata);
}

void SpineL0Maintenance::enqueue_family_writes(bool hot, std::size_t family,
                                               std::size_t target) {
  const auto &edges =
      hot ? hot_family_outputs_[family] : family_outputs_[family];
  const std::uint64_t rows =
      hot ? counters_.hot_family_rows[family] : counters_.family_rows[family];
  const std::uint64_t page_count =
      (config_.max_vertices + config_.page_vertices - 1) /
      config_.page_vertices;
  const SpineLevelLayout layout = spine_level_layout(config_, hot, target);
  if (edges.size() > layout.edge_capacity || rows > layout.edge_capacity) {
    failed_ = true;
    done_ = true;
    failure_ = "Spine target family exceeds fixed level capacity";
    return;
  }
  const std::uint64_t row_words = (rows + 2) >> 1;
  const std::uint64_t mask_words = (rows + 3) >> 2;
  std::set<std::uint32_t> pages;
  for (const SpineEdgeRecord &edge : edges) {
    pages.insert(edge.src / config_.page_vertices);
  }

  FixedAxiPort &graph = *ports_.graph[family];
  for (const std::uint32_t page : pages) {
    enqueue_task(graph, MemoryOperation::kWrite,
                 (layout.bitmap_offset_words + page * 4) * kSpineGraphWordBytes,
                 4 * kSpineGraphWordBytes, TaskClass::kGraph);
    enqueue_task(
        graph, MemoryOperation::kWrite,
        (layout.page_base_offset_words + (page >> 1)) * kSpineGraphWordBytes,
        kSpineGraphWordBytes, TaskClass::kGraph);
  }
  enqueue_task(
      graph, MemoryOperation::kWrite,
      (layout.page_base_offset_words + (page_count >> 1)) * kSpineGraphWordBytes,
      kSpineGraphWordBytes, TaskClass::kGraph);
  enqueue_task(graph, MemoryOperation::kWrite,
               layout.row_offset_offset_words * kSpineGraphWordBytes,
               row_words * kSpineGraphWordBytes, TaskClass::kGraph);
  enqueue_task(graph, MemoryOperation::kWrite,
               layout.mask_offset_words * kSpineGraphWordBytes,
               mask_words * kSpineGraphWordBytes, TaskClass::kGraph);
  std::vector<std::uint8_t> edge_payload;
  edge_payload.reserve(edges.size() * kSpineGraphWordBytes);
  for (const SpineEdgeRecord &edge : edges) {
    const std::vector<std::uint8_t> packed = encode_spine_level_edge(edge);
    edge_payload.insert(edge_payload.end(), packed.begin(), packed.end());
  }
  counters_.graph_edge_payload_write_bytes += edge_payload.size();
  enqueue_task(graph, MemoryOperation::kWrite,
               layout.edge_offset_words * kSpineGraphWordBytes,
               edges.size() * kSpineGraphWordBytes, TaskClass::kGraph,
               std::move(edge_payload));

  counters_.pages_stamped += pages.size();
  counters_.persisted_edges += edges.size();
  counters_.persisted_rows += rows;
  const std::size_t logical_family = hot ? config_.partitions + family : family;
  enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
               config_.metadata_base +
                   (256 + logical_family * config_.levels) * kMetadataWordBytes,
               pages.size() * 3 * kMetadataWordBytes, TaskClass::kMetadata);
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
    for (const SpineEdgeRecord &edge : edges) {
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
      enqueue_task(graph, MemoryOperation::kRead,
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
                 edges.size() * kSpineGraphWordBytes, TaskClass::kGraph);
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
                   config_.metadata_base, 4 * kMetadataWordBytes,
                   TaskClass::kMetadata);
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
      const auto &output = task.hot ? hot_family_outputs_[task.family]
                                    : family_outputs_[task.family];
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
      for (std::size_t family = 0; family < config_.partitions; ++family) {
        enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                     config_.metadata_base +
                         family * config_.levels * 8 * kMetadataWordBytes,
                     8 * kMetadataWordBytes, TaskClass::kMetadata);
      }
      if (counters_.target_level > 0) {
        enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                     config_.metadata_base,
                     static_cast<std::uint64_t>(counters_.target_level) *
                         config_.partitions * 9 * kMetadataWordBytes,
                     TaskClass::kMetadata);
      }
      if (state_.hot_enabled) {
        for (std::size_t family = 0; family < config_.partitions; ++family) {
          enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                       config_.metadata_base + (config_.partitions + family) *
                                                   config_.levels * 8 *
                                                   kMetadataWordBytes,
                       8 * kMetadataWordBytes, TaskClass::kMetadata);
        }
        if (counters_.hot_target_level > 0) {
          enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                       config_.metadata_base,
                       static_cast<std::uint64_t>(counters_.hot_target_level) *
                           config_.partitions * 9 * kMetadataWordBytes,
                       TaskClass::kMetadata);
        }
      }
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
