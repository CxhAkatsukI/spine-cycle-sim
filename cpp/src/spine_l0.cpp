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

constexpr std::uint64_t kEdgeRecordBytes = 16;
constexpr std::uint64_t kGraphWordBytes = 16;
constexpr std::uint64_t kMetadataWordBytes = 8;
constexpr std::uint64_t kResultWords = 96;

std::string trim(std::string text) {
  const auto first = text.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) {
    return {};
  }
  const auto last = text.find_last_not_of(" \t\r\n");
  return text.substr(first, last - first + 1);
}

std::uint64_t parse_unsigned(const std::string& text, const char* field) {
  std::size_t consumed = 0;
  const std::uint64_t value = std::stoull(text, &consumed, 0);
  if (consumed != text.size()) {
    throw std::invalid_argument(std::string("invalid ") + field + ": " + text);
  }
  return value;
}

}  // namespace

SpineEdgeSlice load_spine_edge_slice(const std::filesystem::path& path) {
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
    max_vertex = std::max(max_vertex, static_cast<std::uint32_t>(std::max(src, dst)));
  }
  if (slice.edges.empty()) {
    throw std::runtime_error("Spine edge slice has no edge records: " +
                             path.string());
  }
  if (slice.vertices == 0) {
    slice.vertices = static_cast<std::size_t>(max_vertex) + 1;
  }
  if (slice.vertices <= max_vertex) {
    throw std::runtime_error("Spine edge slice vertex count does not cover IDs");
  }
  if (!std::is_sorted(
          slice.edges.begin(), slice.edges.end(),
          [](const SpineEdgeRecord& left, const SpineEdgeRecord& right) {
            return std::pair(left.src, left.dst) < std::pair(right.src, right.dst);
          })) {
    throw std::runtime_error("Spine maintenance input must be sorted by src,dst");
  }
  return slice;
}

SpineL0Maintenance::SpineL0Maintenance(
    std::string name, ClockId clock_id, SpineL0Config config,
    SpineEdgeSlice workload, SpineL0Ports ports, SpineL0State& state)
    : Component(std::move(name), clock_id),
      config_(config),
      workload_(std::move(workload)),
      ports_(ports),
      state_(state) {
  if (config_.partitions != ports_.graph.size() || config_.partitions != 16 ||
      config_.levels != 11 || config_.vertex_partition_size == 0 ||
      config_.page_vertices == 0 || config_.max_vertices == 0 ||
      workload_.vertices == 0 || workload_.vertices > config_.max_vertices ||
      workload_.edges.empty() || ports_.sorted_edges == nullptr ||
      ports_.metadata == nullptr || ports_.result == nullptr) {
    throw std::invalid_argument("invalid Spine L0 maintenance configuration");
  }
  for (FixedAxiPort* port : ports_.graph) {
    if (port == nullptr) {
      throw std::invalid_argument("Spine graph AXI port is null");
    }
  }
}

void SpineL0Maintenance::evaluate(const CycleContext&) {
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
    const MemoryTask& task = tasks_.front();
    if (task.port->requests().try_push(AxiRequest{
            .transaction_id = next_transaction_id_,
            .operation = task.operation,
            .address = task.address,
            .bytes = task.bytes,
        })) {
      staged_action_ = StagedAction::kIssue;
    }
    return;
  }
  staged_action_ = StagedAction::kAdvance;
}

void SpineL0Maintenance::commit(const CycleContext& context) {
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
      waiting_ = false;
      tasks_.pop_front();
      return;
    case StagedAction::kAdvance:
      advance(context);
      return;
  }
}

void SpineL0Maintenance::enqueue_task(
    FixedAxiPort& port, MemoryOperation operation, std::uint64_t address,
    std::uint64_t bytes, TaskClass task_class) {
  if (bytes == 0) {
    return;
  }
  tasks_.push_back(MemoryTask{
      .port = &port,
      .operation = operation,
      .address = address,
      .bytes = bytes,
      .task_class = task_class,
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
      counters_.graph_write_bytes += bytes;
      break;
    case TaskClass::kResult:
      counters_.result_write_bytes += bytes;
      break;
  }
}

void SpineL0Maintenance::begin_sorted_scan(Phase process_phase) {
  enqueue_task(*ports_.sorted_edges, MemoryOperation::kRead,
               config_.sorted_edges_base,
               workload_.edges.size() * kEdgeRecordBytes,
               TaskClass::kSorted);
  ++counters_.sorted_scan_passes;
  scan_index_ = 0;
  phase_ = process_phase;
}

void SpineL0Maintenance::process_scan_edge(Phase next_phase) {
  if (scan_index_ >= workload_.edges.size()) {
    phase_ = next_phase;
    return;
  }
  ++counters_.sorted_edge_visits;
  ++scan_index_;
  if (scan_index_ == workload_.edges.size()) {
    phase_ = next_phase;
  }
}

std::size_t SpineL0Maintenance::family_for(std::uint32_t dst) const {
  return std::min<std::size_t>(
      dst / config_.vertex_partition_size, config_.partitions - 1);
}

std::vector<SpineEdgeRecord> SpineL0Maintenance::coalesce_family(
    std::size_t family) const {
  std::vector<SpineEdgeRecord> output;
  std::size_t index = 0;
  while (index < workload_.edges.size()) {
    const SpineEdgeRecord& first = workload_.edges[index];
    const std::uint32_t src = first.src;
    const std::uint32_t dst = first.dst;
    std::uint16_t weight = first.weight;
    std::int64_t diff = 0;
    while (index < workload_.edges.size() &&
           workload_.edges[index].src == src &&
           workload_.edges[index].dst == dst) {
      weight = std::min(weight, workload_.edges[index].weight);
      diff += workload_.edges[index].diff;
      ++index;
    }
    if (family_for(dst) != family || diff == 0) {
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

void SpineL0Maintenance::build_family_outputs() {
  active_families_.clear();
  for (std::size_t family = 0; family < config_.partitions; ++family) {
    family_outputs_[family] = coalesce_family(family);
    counters_.family_edges[family] = family_outputs_[family].size();
    std::uint64_t rows = 0;
    std::uint32_t last_src = 0;
    bool have_src = false;
    for (const SpineEdgeRecord& edge : family_outputs_[family]) {
      if (!have_src || edge.src != last_src) {
        ++rows;
        last_src = edge.src;
        have_src = true;
      }
    }
    counters_.family_rows[family] = rows;
    if (!family_outputs_[family].empty()) {
      active_families_.push_back(family);
    }
  }
  counters_.active_families = active_families_.size();
}

void SpineL0Maintenance::enqueue_dirty_source_updates() {
  std::vector<std::uint32_t> sources;
  for (const SpineEdgeRecord& edge : workload_.edges) {
    if (sources.empty() || sources.back() != edge.src) {
      sources.push_back(edge.src);
    }
  }
  counters_.unique_sources = sources.size();
  for (std::size_t index = 0; index < sources.size(); ++index) {
    const std::uint32_t src = sources[index];
    const std::uint64_t directory =
        config_.persistent_directory_base + (src >> 2) * kEdgeRecordBytes;
    const std::uint64_t bitmap =
        config_.persistent_dirty_bitmap_base + (src >> 7) * kEdgeRecordBytes;
    const std::uint64_t list =
        config_.persistent_dirty_list_base + (index >> 2) * kEdgeRecordBytes;
    for (const std::uint64_t address : {directory, bitmap, list}) {
      enqueue_task(*ports_.sorted_edges, MemoryOperation::kRead, address,
                   kEdgeRecordBytes, TaskClass::kPersistent);
      enqueue_task(*ports_.sorted_edges, MemoryOperation::kWrite, address,
                   kEdgeRecordBytes, TaskClass::kPersistent);
    }
  }
  enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
               config_.metadata_base + 32 * kMetadataWordBytes,
               7 * kMetadataWordBytes, TaskClass::kMetadata);
}

void SpineL0Maintenance::enqueue_family_writes(std::size_t family) {
  const auto& edges = family_outputs_[family];
  const std::uint64_t rows = counters_.family_rows[family];
  const std::uint64_t page_count =
      (config_.max_vertices + config_.page_vertices - 1) /
      config_.page_vertices;
  const std::uint64_t bitmap_words = page_count * 4;
  const std::uint64_t page_base_words = (page_count + 2) >> 1;
  const std::uint64_t row_offset = bitmap_words + page_base_words;
  const std::uint64_t row_words = (rows + 2) >> 1;
  const std::uint64_t mask_offset = row_offset + row_words;
  const std::uint64_t mask_words = (rows + 3) >> 2;
  const std::uint64_t edge_offset = mask_offset + mask_words;
  std::set<std::uint32_t> pages;
  for (const SpineEdgeRecord& edge : edges) {
    pages.insert(edge.src / config_.page_vertices);
  }

  FixedAxiPort& graph = *ports_.graph[family];
  for (const std::uint32_t page : pages) {
    enqueue_task(graph, MemoryOperation::kWrite,
                 page * 4 * kGraphWordBytes, 4 * kGraphWordBytes,
                 TaskClass::kGraph);
    enqueue_task(graph, MemoryOperation::kWrite,
                 (bitmap_words + (page >> 1)) * kGraphWordBytes,
                 kGraphWordBytes, TaskClass::kGraph);
  }
  enqueue_task(graph, MemoryOperation::kWrite,
               (bitmap_words + (page_count >> 1)) * kGraphWordBytes,
               kGraphWordBytes, TaskClass::kGraph);
  enqueue_task(graph, MemoryOperation::kWrite,
               row_offset * kGraphWordBytes, row_words * kGraphWordBytes,
               TaskClass::kGraph);
  enqueue_task(graph, MemoryOperation::kWrite,
               mask_offset * kGraphWordBytes, mask_words * kGraphWordBytes,
               TaskClass::kGraph);
  enqueue_task(graph, MemoryOperation::kWrite,
               edge_offset * kGraphWordBytes,
               edges.size() * kGraphWordBytes, TaskClass::kGraph);

  counters_.pages_stamped += pages.size();
  enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
               config_.metadata_base + (256 + family * config_.levels) *
                                           kMetadataWordBytes,
               pages.size() * 3 * kMetadataWordBytes,
               TaskClass::kMetadata);
}

void SpineL0Maintenance::advance(const CycleContext& context) {
  switch (phase_) {
    case Phase::kInitialize:
      counters_.start_cycle = context.domain_cycle;
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
      if (scan_index_ + 1 == workload_.edges.size()) {
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
                   config_.partitions * 2 * kMetadataWordBytes,
                   TaskClass::kMetadata);
      family_index_ = 0;
      phase_ = Phase::kPrecountBegin;
      return;
    case Phase::kPrecountBegin:
      begin_sorted_scan(Phase::kPrecountProcess);
      return;
    case Phase::kPrecountProcess:
      if (scan_index_ + 1 == workload_.edges.size()) {
        ++counters_.sorted_edge_visits;
        ++scan_index_;
        ++family_index_;
        if (family_index_ == config_.partitions) {
          build_family_outputs();
          active_family_index_ = 0;
          phase_ = Phase::kWriteSelect;
        } else {
          phase_ = Phase::kPrecountBegin;
        }
      } else {
        process_scan_edge(Phase::kPrecountBegin);
      }
      return;
    case Phase::kWriteSelect:
      if (active_family_index_ == active_families_.size()) {
        phase_ = Phase::kCommitMetadata;
      } else {
        phase_ = Phase::kWriteBegin;
      }
      return;
    case Phase::kWriteBegin:
      begin_sorted_scan(Phase::kWriteProcess);
      return;
    case Phase::kWriteProcess:
      if (scan_index_ + 1 == workload_.edges.size()) {
        ++counters_.sorted_edge_visits;
        ++scan_index_;
        const std::size_t family = active_families_[active_family_index_];
        state_.cold_levels[family][0] = family_outputs_[family];
        counters_.persisted_edges += family_outputs_[family].size();
        counters_.persisted_rows += counters_.family_rows[family];
        enqueue_family_writes(family);
        phase_ = Phase::kWriteAdvance;
      } else {
        process_scan_edge(Phase::kWriteAdvance);
      }
      return;
    case Phase::kWriteAdvance:
      ++active_family_index_;
      phase_ = Phase::kWriteSelect;
      return;
    case Phase::kCommitMetadata:
      for (std::size_t family = 0; family < config_.partitions; ++family) {
        enqueue_task(*ports_.metadata, MemoryOperation::kWrite,
                     config_.metadata_base +
                         family * config_.levels * 8 * kMetadataWordBytes,
                     8 * kMetadataWordBytes, TaskClass::kMetadata);
      }
      phase_ = Phase::kWriteResult;
      return;
    case Phase::kWriteResult:
      enqueue_task(*ports_.metadata, MemoryOperation::kRead,
                   config_.metadata_base,
                   config_.partitions * kMetadataWordBytes,
                   TaskClass::kMetadata);
      enqueue_task(*ports_.result, MemoryOperation::kWrite,
                   config_.result_base, kResultWords * 4,
                   TaskClass::kResult);
      phase_ = Phase::kFinish;
      return;
    case Phase::kFinish:
      counters_.end_cycle = context.domain_cycle;
      done_ = true;
      return;
  }
}

}  // namespace spine::sim
