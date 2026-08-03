#include "spine_sim/spine_system.hpp"

#include <algorithm>
#include <deque>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace spine::sim {

namespace {

std::vector<std::uint8_t> encode_active_output_record(std::uint32_t value,
                                                      std::uint32_t source) {
  return {
      static_cast<std::uint8_t>(value & 0xffU),
      static_cast<std::uint8_t>((value >> 8) & 0xffU),
      static_cast<std::uint8_t>((value >> 16) & 0xffU),
      static_cast<std::uint8_t>((value >> 24) & 0xffU),
      static_cast<std::uint8_t>(source & 0xffU),
      static_cast<std::uint8_t>((source >> 8) & 0xffU),
      static_cast<std::uint8_t>((source >> 16) & 0xffU),
      static_cast<std::uint8_t>((source >> 24) & 0xffU),
  };
}

std::vector<std::uint8_t> encode_u32_word(std::uint32_t value) {
  return {
      static_cast<std::uint8_t>(value & 0xffU),
      static_cast<std::uint8_t>((value >> 8) & 0xffU),
      static_cast<std::uint8_t>((value >> 16) & 0xffU),
      static_cast<std::uint8_t>((value >> 24) & 0xffU),
  };
}

std::vector<std::uint8_t>
encode_u32_words(const std::vector<std::uint32_t> &values) {
  std::vector<std::uint8_t> payload;
  payload.reserve(values.size() * sizeof(std::uint32_t));
  for (const std::uint32_t value : values) {
    const std::vector<std::uint8_t> encoded = encode_u32_word(value);
    payload.insert(payload.end(), encoded.begin(), encoded.end());
  }
  return payload;
}

std::uint32_t decode_u32_word(const std::vector<std::uint8_t> &payload) {
  if (payload.size() != sizeof(std::uint32_t)) {
    throw std::logic_error("device seeder received a malformed word");
  }
  return static_cast<std::uint32_t>(payload[0]) |
         (static_cast<std::uint32_t>(payload[1]) << 8) |
         (static_cast<std::uint32_t>(payload[2]) << 16) |
         (static_cast<std::uint32_t>(payload[3]) << 24);
}

class SpineInitialActiveOutputWriter final : public Component {
 public:
  SpineInitialActiveOutputWriter(
      std::string name, ClockId clock_id, FixedAxiPort &port,
      const SpineL0Maintenance &maintenance,
      std::vector<std::pair<std::uint32_t, std::uint32_t>> records,
      SpineInitialActiveOutputCounters &counters, bool &ready, bool &failed,
      std::string &failure)
      : Component(std::move(name), clock_id),
        port_(port),
        maintenance_(maintenance),
        records_(std::move(records)),
        counters_(counters),
        ready_(ready),
        failed_(failed),
        failure_(failure) {
    counters_.enabled = true;
    counters_.active_vertices = records_.size();
    ready_ = false;
  }

  void evaluate(const CycleContext &) override {
    staged_issue_ = false;
    staged_done_ = false;
    staged_response_.reset();
    if (ready_ || failed_) {
      return;
    }
    if (!maintenance_.done()) {
      return;
    }
    if (maintenance_.failed()) {
      failed_ = true;
      failure_ = "initial active-output writer blocked by failed maintenance";
      return;
    }
    const AxiResponse *response = port_.responses().front();
    if (response != nullptr) {
      AxiResponse staged;
      if (port_.responses().try_pop(staged)) {
        staged_response_ = std::move(staged);
      }
      return;
    }
    if (next_record_ < records_.size()) {
      if (inflight_.size() >= kMaxInflight) {
        return;
      }
      const auto [source, value] = records_[next_record_];
      if (port_.requests().try_push(AxiRequest{
              .transaction_id = next_transaction_,
              .operation = MemoryOperation::kWrite,
              .address = next_record_ * kActiveOutputBytes,
              .bytes = kActiveOutputBytes,
              .write_data = encode_active_output_record(value, source),
          })) {
        staged_issue_ = true;
      } else {
        ++counters_.memory_request_fifo_stall_cycles;
      }
      return;
    }
    if (inflight_.empty()) {
      staged_done_ = true;
    }
  }

  void commit(const CycleContext &context) override {
    if (ready_ || failed_) {
      return;
    }
    if (counters_.start_cycle == 0 && maintenance_.done()) {
      counters_.start_cycle = context.domain_cycle;
    }
    if (staged_response_.has_value()) {
      const auto found = inflight_.find(staged_response_->transaction_id);
      if (found == inflight_.end() || !staged_response_->success ||
          staged_response_->operation != MemoryOperation::kWrite ||
          !staged_response_->read_data.empty()) {
        failed_ = true;
        failure_ = "initial active-output writer received an invalid response";
        return;
      }
      inflight_.erase(found);
      ++counters_.memory_requests_completed;
    }
    if (staged_issue_) {
      inflight_.emplace(next_transaction_, next_record_);
      ++next_transaction_;
      ++next_record_;
      ++counters_.memory_requests_issued;
      counters_.write_bytes += kActiveOutputBytes;
      counters_.max_memory_requests_inflight =
          std::max(counters_.max_memory_requests_inflight, inflight_.size());
    }
    if (staged_done_) {
      counters_.end_cycle = context.domain_cycle;
      counters_.request_ledger_closed =
          counters_.memory_requests_issued ==
          counters_.memory_requests_completed;
      ready_ = true;
    }
  }

 private:
  static constexpr std::uint64_t kActiveOutputBytes = 8;
  static constexpr std::size_t kMaxInflight = 16;

  FixedAxiPort &port_;
  const SpineL0Maintenance &maintenance_;
  std::vector<std::pair<std::uint32_t, std::uint32_t>> records_;
  SpineInitialActiveOutputCounters &counters_;
  bool &ready_;
  bool &failed_;
  std::string &failure_;
  std::size_t next_record_{};
  std::uint64_t next_transaction_{};
  std::unordered_map<std::uint64_t, std::size_t> inflight_;
  bool staged_issue_{};
  bool staged_done_{};
  std::optional<AxiResponse> staged_response_;
};

class SpineResidualCorrectionSeeder final : public Component {
 public:
  SpineResidualCorrectionSeeder(
      std::string name, ClockId clock_id,
      std::array<FixedAxiPort *, 16> graph_ports, FixedAxiPort &vertex_state,
      FixedAxiPort &active_out, const SpineL0Maintenance &maintenance,
      const SpineL0State &state, SpineL0Config config,
      SpineResidualCorrectionPlan plan, std::uint64_t primary_base,
      std::uint64_t auxiliary_base, std::uint64_t degree_base,
      SpineInitialActiveOutputCounters &counters, bool &ready, bool &failed,
      std::string &failure)
      : Component(std::move(name), clock_id),
        graph_ports_(graph_ports),
        vertex_state_(vertex_state),
        active_out_(active_out),
        maintenance_(maintenance),
        state_(state),
        config_(std::move(config)),
        plan_(std::move(plan)),
        primary_base_(primary_base),
        auxiliary_base_(auxiliary_base),
        degree_base_(degree_base),
        counters_(counters),
        ready_(ready),
        failed_(failed),
        failure_(failure) {
    counters_.enabled = true;
    counters_.residual_correction_timed = true;
    counters_.touched_sources = plan_.touched_sources.size();
    counters_.active_vertices = plan_.active_vertices.size();
    ready_ = false;
    build_static_tasks();
  }

  void evaluate(const CycleContext &) override {
    staged_initialize_ = false;
    staged_issue_ = false;
    staged_advance_ = false;
    staged_response_.reset();
    if (ready_ || failed_) {
      return;
    }
    if (!maintenance_.done()) {
      return;
    }
    if (maintenance_.failed()) {
      failed_ = true;
      failure_ = "residual correction blocked by failed maintenance";
      return;
    }
    if (!initialized_) {
      staged_initialize_ = true;
      return;
    }
    if (stage_response(vertex_state_) || stage_response(active_out_)) {
      return;
    }
    for (FixedAxiPort *port : graph_ports_) {
      if (stage_response(*port)) {
        return;
      }
    }
    const std::vector<Task> &tasks = phase_tasks();
    if (next_task_ < tasks.size()) {
      if (inflight_.size() >= kMaxInflight) {
        return;
      }
      const Task &task = tasks[next_task_];
      if (task.port->requests().try_push(AxiRequest{
              .transaction_id = next_transaction_,
              .operation = task.operation,
              .address = task.address,
              .bytes = task.bytes,
              .write_data = task.write_data,
          })) {
        staged_issue_ = true;
      } else {
        ++counters_.memory_request_fifo_stall_cycles;
      }
      return;
    }
    if (inflight_.empty()) {
      staged_advance_ = true;
    }
  }

  void commit(const CycleContext &context) override {
    if (ready_ || failed_) {
      return;
    }
    if (staged_initialize_) {
      build_graph_tasks();
      initialized_ = true;
      phase_ = Phase::kSourceReads;
      counters_.start_cycle = context.domain_cycle;
      return;
    }
    if (staged_response_.has_value()) {
      consume_response(*staged_response_);
      if (failed_) {
        return;
      }
    }
    if (staged_issue_) {
      const Task &task = phase_tasks().at(next_task_);
      inflight_.emplace(next_transaction_, task);
      ++next_transaction_;
      ++next_task_;
      ++counters_.memory_requests_issued;
      counters_.max_memory_requests_inflight =
          std::max(counters_.max_memory_requests_inflight, inflight_.size());
    }
    if (staged_advance_) {
      next_task_ = 0;
      if (phase_ == Phase::kActiveWrites) {
        counters_.end_cycle = context.domain_cycle;
        counters_.request_ledger_closed =
            counters_.memory_requests_issued ==
            counters_.memory_requests_completed;
        if (!counters_.request_ledger_closed) {
          failed_ = true;
          failure_ = "residual correction request ledger did not close";
          return;
        }
        phase_ = Phase::kDone;
        ready_ = true;
      } else {
        phase_ = static_cast<Phase>(static_cast<int>(phase_) + 1);
      }
    }
  }

 private:
  static constexpr std::size_t kMaxInflight = 16;
  static constexpr std::uint64_t kGraphWordBytes = 8;
  static constexpr std::uint64_t kStateWordBytes = 4;
  static constexpr std::uint64_t kActiveOutputBytes = 8;

  enum class Phase {
    kWait,
    kSourceReads,
    kGraphReads,
    kResidualReads,
    kStateWrites,
    kActiveWrites,
    kDone,
  };

  enum class TaskKind {
    kRankRead,
    kDegreeRead,
    kGraphRead,
    kResidualRead,
    kDegreeWrite,
    kResidualWrite,
    kActiveWrite,
  };

  struct Task {
    FixedAxiPort *port{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint64_t address{};
    std::uint64_t bytes{};
    std::vector<std::uint8_t> write_data;
    TaskKind kind{TaskKind::kRankRead};
    std::optional<std::uint32_t> expected_word;
  };

  bool stage_response(FixedAxiPort &port) {
    const AxiResponse *response = port.responses().front();
    if (response == nullptr) {
      return false;
    }
    AxiResponse staged;
    if (port.responses().try_pop(staged)) {
      staged_response_ = std::move(staged);
    }
    return true;
  }

  static std::uint64_t row_count(const std::vector<SpineEdgeRecord> &edges) {
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

  void build_static_tasks() {
    std::unordered_set<std::uint32_t> touched;
    for (const std::uint32_t source : plan_.touched_sources) {
      if (!touched.insert(source).second) {
        throw std::invalid_argument(
            "residual correction touched-source list contains duplicates");
      }
      source_reads_.push_back(Task{
          .port = &vertex_state_,
          .operation = MemoryOperation::kRead,
          .address = primary_base_ + source * kStateWordBytes,
          .bytes = kStateWordBytes,
          .write_data = {},
          .kind = TaskKind::kRankRead,
          .expected_word = plan_.old_rank_words.at(source),
      });
      source_reads_.push_back(Task{
          .port = &vertex_state_,
          .operation = MemoryOperation::kRead,
          .address = degree_base_ + source * kStateWordBytes,
          .bytes = kStateWordBytes,
          .write_data = {},
          .kind = TaskKind::kDegreeRead,
          .expected_word = plan_.old_out_degrees.at(source),
      });
      state_writes_.push_back(Task{
          .port = &vertex_state_,
          .operation = MemoryOperation::kWrite,
          .address = degree_base_ + source * kStateWordBytes,
          .bytes = kStateWordBytes,
          .write_data = encode_u32_word(plan_.new_out_degrees.at(source)),
          .kind = TaskKind::kDegreeWrite,
          .expected_word = std::nullopt,
      });
    }
    for (std::size_t vertex = 0; vertex < plan_.seed_words.size(); ++vertex) {
      const std::uint32_t seed = plan_.seed_words[vertex];
      if ((seed & 0x7fffffffU) == 0) {
        continue;
      }
      residual_reads_.push_back(Task{
          .port = &vertex_state_,
          .operation = MemoryOperation::kRead,
          .address = auxiliary_base_ + vertex * kStateWordBytes,
          .bytes = kStateWordBytes,
          .write_data = {},
          .kind = TaskKind::kResidualRead,
          .expected_word = 0U,
      });
      state_writes_.push_back(Task{
          .port = &vertex_state_,
          .operation = MemoryOperation::kWrite,
          .address = auxiliary_base_ + vertex * kStateWordBytes,
          .bytes = kStateWordBytes,
          .write_data = encode_u32_word(seed),
          .kind = TaskKind::kResidualWrite,
          .expected_word = std::nullopt,
      });
      ++counters_.seeded_vertices;
    }
    for (std::size_t index = 0; index < plan_.active_vertices.size(); ++index) {
      const std::uint32_t vertex = plan_.active_vertices[index];
      active_writes_.push_back(Task{
          .port = &active_out_,
          .operation = MemoryOperation::kWrite,
          .address = index * kActiveOutputBytes,
          .bytes = kActiveOutputBytes,
          .write_data = encode_active_output_record(plan_.seed_words.at(vertex),
                                                    vertex),
          .kind = TaskKind::kActiveWrite,
          .expected_word = std::nullopt,
      });
    }
    counters_.rank_read_bytes =
        plan_.touched_sources.size() * kStateWordBytes;
    counters_.degree_read_bytes =
        plan_.touched_sources.size() * kStateWordBytes;
    counters_.degree_write_bytes =
        plan_.touched_sources.size() * kStateWordBytes;
    counters_.residual_read_bytes =
        counters_.seeded_vertices * kStateWordBytes;
    counters_.residual_write_bytes =
        counters_.seeded_vertices * kStateWordBytes;
    counters_.write_bytes = plan_.active_vertices.size() * kActiveOutputBytes;
  }

  void build_graph_tasks() {
    const std::unordered_set<std::uint32_t> touched(
        plan_.touched_sources.begin(), plan_.touched_sources.end());
    const auto add_levels = [&](const auto &families, bool hot) {
      for (std::size_t family = 0; family < config_.partitions; ++family) {
        for (std::size_t level = 0; level < config_.levels; ++level) {
          const auto &edges = families[family][level];
          if (edges.empty()) {
            continue;
          }
          const SpineLevelLayout layout =
              spine_slice_layout(config_, hot, level, row_count(edges));
          for (std::size_t index = 0; index < edges.size(); ++index) {
            if (!touched.contains(edges[index].src)) {
              continue;
            }
            graph_reads_.push_back(Task{
                .port = graph_ports_.at(family),
                .operation = MemoryOperation::kRead,
                .address = (layout.edge_offset_words + index) * kGraphWordBytes,
                .bytes = kGraphWordBytes,
                .write_data = {},
                .kind = TaskKind::kGraphRead,
                .expected_word = std::nullopt,
            });
          }
        }
      }
    };
    add_levels(state_.cold_levels, false);
    if (state_.hot_enabled) {
      add_levels(state_.hot_levels, true);
    }
    counters_.physical_edge_records = graph_reads_.size();
    counters_.graph_read_bytes = graph_reads_.size() * kGraphWordBytes;
    counters_.arithmetic_operations = graph_reads_.size();
  }

  const std::vector<Task> &phase_tasks() const {
    switch (phase_) {
    case Phase::kSourceReads:
      return source_reads_;
    case Phase::kGraphReads:
      return graph_reads_;
    case Phase::kResidualReads:
      return residual_reads_;
    case Phase::kStateWrites:
      return state_writes_;
    case Phase::kActiveWrites:
      return active_writes_;
    case Phase::kWait:
    case Phase::kDone:
      break;
    }
    throw std::logic_error("residual correction has no tasks in this phase");
  }

  void consume_response(const AxiResponse &response) {
    const auto found = inflight_.find(response.transaction_id);
    if (found == inflight_.end() || !response.success ||
        response.operation != found->second.operation) {
      failed_ = true;
      failure_ = "residual correction received an invalid AXI response";
      return;
    }
    const Task task = found->second;
    inflight_.erase(found);
    if (task.operation == MemoryOperation::kRead) {
      if (response.read_data.size() != task.bytes) {
        failed_ = true;
        failure_ = "residual correction read response has the wrong size";
        return;
      }
      if (task.expected_word.has_value() &&
          decode_u32_word(response.read_data) != *task.expected_word) {
        const std::uint32_t actual = decode_u32_word(response.read_data);
        failed_ = true;
        failure_ =
            "residual correction observed stale resident state kind=" +
            std::to_string(static_cast<int>(task.kind)) +
            " address=" + std::to_string(task.address) +
            " expected=" + std::to_string(*task.expected_word) +
            " actual=" + std::to_string(actual);
        return;
      }
    } else if (!response.read_data.empty()) {
      failed_ = true;
      failure_ = "residual correction write returned read payload";
      return;
    }
    ++counters_.memory_requests_completed;
  }

  std::array<FixedAxiPort *, 16> graph_ports_;
  FixedAxiPort &vertex_state_;
  FixedAxiPort &active_out_;
  const SpineL0Maintenance &maintenance_;
  const SpineL0State &state_;
  SpineL0Config config_;
  SpineResidualCorrectionPlan plan_;
  std::uint64_t primary_base_{};
  std::uint64_t auxiliary_base_{};
  std::uint64_t degree_base_{};
  SpineInitialActiveOutputCounters &counters_;
  bool &ready_;
  bool &failed_;
  std::string &failure_;
  std::vector<Task> source_reads_;
  std::vector<Task> graph_reads_;
  std::vector<Task> residual_reads_;
  std::vector<Task> state_writes_;
  std::vector<Task> active_writes_;
  std::unordered_map<std::uint64_t, Task> inflight_;
  Phase phase_{Phase::kWait};
  std::size_t next_task_{};
  std::uint64_t next_transaction_{};
  bool initialized_{};
  bool staged_initialize_{};
  bool staged_issue_{};
  bool staged_advance_{};
  std::optional<AxiResponse> staged_response_;
};

}  // namespace

SpineActiveBins build_spine_host_active_bins(
    const SpineL0State &state, const SpineL0Config &config,
    const std::vector<std::uint32_t> &sources,
    const std::vector<std::uint32_t> &values) {
  struct ActiveRoute {
    std::array<std::uint16_t, kSpineLevelCount> level_masks{};
    std::array<std::uint16_t, 16> hot_by_partition{};
  };

  std::unordered_map<std::uint32_t, std::size_t> route_indices;
  route_indices.reserve(sources.size());
  std::vector<ActiveRoute> routes;
  routes.reserve(sources.size());
  for (const std::uint32_t source : sources) {
    if (source >= values.size()) {
      throw std::logic_error("host active source has no vertex-state value");
    }
    if (route_indices.contains(source)) {
      continue;
    }
    route_indices.emplace(source, routes.size());
    routes.emplace_back();
  }

  for (std::size_t level = 0; level < config.levels; ++level) {
    for (std::size_t family = 0; family < config.partitions; ++family) {
      for (const SpineEdgeRecord &edge : state.cold_levels[family][level]) {
        const auto route = route_indices.find(edge.src);
        if (route == route_indices.end()) {
          continue;
        }
        const std::size_t partition = std::min<std::size_t>(
            edge.dst / config.vertex_partition_size, config.partitions - 1);
        routes[route->second].level_masks[level] |=
            static_cast<std::uint16_t>(1U << partition);
      }
      if (!state.hot_enabled) {
        continue;
      }
      for (const SpineEdgeRecord &edge : state.hot_levels[family][level]) {
        const auto route = route_indices.find(edge.src);
        if (route == route_indices.end()) {
          continue;
        }
        const std::size_t partition = std::min<std::size_t>(
            edge.dst / config.vertex_partition_size, config.partitions - 1);
        routes[route->second].hot_by_partition[partition] |=
            static_cast<std::uint16_t>(1U << family);
      }
    }
  }

  SpineActiveBins result;
  for (const std::uint32_t source : sources) {
    const ActiveRoute &route = routes[route_indices.at(source)];
    SpineActiveRecord base{
        .source = source,
        .source_value = values[source],
        .level_masks = route.level_masks,
    };
    std::uint16_t any_partition = 0;
    for (std::size_t level = 0; level < config.levels; ++level) {
      any_partition |= route.level_masks[level];
    }
    for (std::size_t partition = 0; partition < config.partitions;
         ++partition) {
      if (route.hot_by_partition[partition] != 0) {
        any_partition |= static_cast<std::uint16_t>(1U << partition);
      }
      if (((any_partition >> partition) & 1U) == 0) {
        continue;
      }
      SpineActiveRecord record = base;
      record.hot_shard_mask = route.hot_by_partition[partition];
      result.bins[partition].push_back(record);
    }
  }
  return result;
}

namespace {

struct PageRankHostInput {
  SpineActiveBins bins;
  std::vector<std::uint32_t> sources;
  std::vector<std::uint32_t> out_degrees;
  std::optional<SpineDirtyIdentity> coverage;
};

PageRankHostInput build_pagerank_host_input(const SpineEdgeSlice &workload,
                                             const SpineL0Config &config) {
  if (workload.vertices == 0 ||
      workload.vertices > std::numeric_limits<std::uint32_t>::max() ||
      config.partitions != 16 || config.levels > kSpineLevelCount) {
    throw std::invalid_argument("unsupported Spine PageRank graph shape");
  }
  PageRankHostInput result;
  result.sources.resize(workload.vertices);
  std::iota(result.sources.begin(), result.sources.end(), 0U);
  result.out_degrees.assign(workload.vertices, 0);
  struct SourcePartitionUse {
    bool cold{};
    std::uint16_t hot_shards{};
  };
  std::vector<std::array<SourcePartitionUse, 16>> source_partitions(
      workload.vertices);
  const std::unordered_set<std::uint32_t> hot_vertices(
      config.hot_vertices.begin(), config.hot_vertices.end());
  std::vector<std::uint32_t> dirty_sources;
  std::unordered_set<std::uint32_t> dirty_seen;
  for (const SpineEdgeRecord &edge : workload.edges) {
    if (edge.src >= workload.vertices || edge.dst >= workload.vertices ||
        edge.diff != 1 ||
        result.out_degrees[edge.src] ==
            std::numeric_limits<std::uint32_t>::max()) {
      throw std::invalid_argument(
          "initial PageRank vertical slice requires in-range insertion edges");
    }
    ++result.out_degrees[edge.src];
    const std::size_t partition = std::min<std::size_t>(
        edge.dst / config.vertex_partition_size, config.partitions - 1);
    SourcePartitionUse &use = source_partitions[edge.src][partition];
    if (hot_vertices.contains(edge.dst)) {
      use.hot_shards |=
          static_cast<std::uint16_t>(1U << spine_hot_shard(edge.dst));
    } else {
      use.cold = true;
    }
    if (dirty_seen.insert(edge.src).second) {
      dirty_sources.push_back(edge.src);
    }
  }
  std::sort(dirty_sources.begin(), dirty_sources.end());
  if (!dirty_sources.empty()) {
    result.coverage = spine_dirty_identity(1, dirty_sources);
  }
  for (std::uint32_t source = 0; source < workload.vertices; ++source) {
    for (std::size_t partition = 0; partition < config.partitions;
         ++partition) {
      const SourcePartitionUse &use = source_partitions[source][partition];
      if (!use.cold && use.hot_shards == 0) {
        continue;
      }
      SpineActiveRecord record{
          .source = source,
          .source_value = 0,
          .hot_shard_mask = use.hot_shards,
      };
      if (use.cold) {
        for (std::size_t level = 0; level < config.levels; ++level) {
          record.level_masks[level] =
              static_cast<std::uint16_t>(1U << partition);
        }
      }
      result.bins.bins[partition].push_back(record);
    }
  }
  return result;
}

}  // namespace

SpineAxiInterfaceProfile SpineAxiInterfaceProfile::legacy_uniform64() {
  return SpineAxiInterfaceProfile{
      .profile_id = "legacy_uniform64",
      .max_burst_beats = 16,
      .readwrite_max_pending_requests = 32,
      .writeonly_max_pending_requests = 32,
      .maintenance_readwrite_max_pending_requests = 0,
      .maintenance_writeonly_max_pending_requests = 0,
      .max_outstanding_bursts = 32,
      .response_beats_per_cycle = 4,
      .read_reorder_capacity = 32,
      .read_address_pipeline_cycles = 0,
      .read_data_pipeline_cycles = 0,
      .write_buffer_pipeline_cycles = 0,
      .serialize_write_bursts = false,
      .write_ingress_fifo_depth = 0,
      .write_throttle_fifo_depth = 0,
      .write_ingress_pipeline_cycles = 0,
      .write_address_after_full_burst_cycles = 0,
      .maintenance_read_reorder_capacity = 0,
      .maintenance_read_address_pipeline_cycles = 0,
      .maintenance_read_data_pipeline_cycles = 0,
      .maintenance_write_buffer_pipeline_cycles = 0,
      .maintenance_serialize_write_bursts = false,
      .maintenance_write_ingress_fifo_depth = 0,
      .maintenance_write_throttle_fifo_depth = 0,
      .maintenance_write_ingress_pipeline_cycles = 0,
      .maintenance_write_address_after_full_burst_cycles = 0,
      .burst_trace_limit = 0,
      .graph_bytes = 64,
      .sorted_edge_bytes = 64,
      .active_bin_bytes = 64,
      .metadata_bytes = 64,
      .result_bytes = 64,
      .maintenance_result_bytes = 0,
      .vertex_state_bytes = 64,
      .active_out_bytes = 64,
      .active_bitmap_bytes = 64,
  };
}

SpineAxiInterfaceProfile SpineAxiInterfaceProfile::candidate10_1e61fc0() {
  SpineAxiInterfaceProfile profile;
  profile.profile_id = "candidate10_gmem_1e61fc0";
  profile.maintenance_readwrite_max_pending_requests = 70;
  profile.maintenance_writeonly_max_pending_requests = 67;
  profile.maintenance_read_reorder_capacity = 256;
  profile.maintenance_read_address_pipeline_cycles = 7;
  profile.maintenance_read_data_pipeline_cycles = 1;
  profile.maintenance_write_buffer_pipeline_cycles = 0;
  profile.maintenance_serialize_write_bursts = true;
  profile.maintenance_write_ingress_fifo_depth = 16;
  profile.maintenance_write_throttle_fifo_depth = 16;
  profile.maintenance_write_ingress_pipeline_cycles = 8;
  profile.maintenance_write_address_after_full_burst_cycles = 2;
  profile.maintenance_result_bytes = 8;
  return profile;
}

FixedAxiPortConfig SpineAxiInterfaceProfile::port_config(
    SpineAxiPortKind kind, std::size_t memory_channels, std::size_t channel,
    std::uint32_t initiator_id) const {
  std::uint32_t width = 0;
  bool write_only = false;
  bool maintenance_port = true;
  switch (kind) {
  case SpineAxiPortKind::kGraph:
    width = graph_bytes;
    break;
  case SpineAxiPortKind::kSortedEdges:
    width = sorted_edge_bytes;
    break;
  case SpineAxiPortKind::kActiveBins:
    width = active_bin_bytes;
    break;
  case SpineAxiPortKind::kMetadata:
    width = metadata_bytes;
    break;
  case SpineAxiPortKind::kMaintenanceResult:
    width = maintenance_result_bytes == 0 ? result_bytes
                                          : maintenance_result_bytes;
    write_only = true;
    break;
  case SpineAxiPortKind::kVertexState:
    width = vertex_state_bytes;
    maintenance_port = false;
    break;
  case SpineAxiPortKind::kActiveOut:
    width = active_out_bytes;
    write_only = true;
    maintenance_port = false;
    break;
  case SpineAxiPortKind::kActiveBitmap:
    width = active_bitmap_bytes;
    maintenance_port = false;
    break;
  case SpineAxiPortKind::kComputeResult:
    width = result_bytes;
    write_only = true;
    maintenance_port = false;
    break;
  }
  if (profile_id.empty() || width == 0 || max_burst_beats == 0 ||
      readwrite_max_pending_requests == 0 ||
      writeonly_max_pending_requests == 0 || max_outstanding_bursts == 0 ||
      response_beats_per_cycle == 0) {
    throw std::invalid_argument("invalid Spine AXI interface profile");
  }
  std::size_t max_pending = write_only ? writeonly_max_pending_requests
                                       : readwrite_max_pending_requests;
  if (maintenance_port) {
    const std::size_t override =
        write_only ? maintenance_writeonly_max_pending_requests
                   : maintenance_readwrite_max_pending_requests;
    if (override != 0) {
      max_pending = override;
    }
  }
  const std::size_t port_read_reorder_capacity =
      maintenance_port && maintenance_read_reorder_capacity != 0
          ? maintenance_read_reorder_capacity
          : read_reorder_capacity;
  const std::uint64_t port_read_address_pipeline_cycles =
      maintenance_port && maintenance_read_address_pipeline_cycles != 0
          ? maintenance_read_address_pipeline_cycles
          : read_address_pipeline_cycles;
  const std::uint64_t port_read_data_pipeline_cycles =
      maintenance_port && maintenance_read_data_pipeline_cycles != 0
          ? maintenance_read_data_pipeline_cycles
          : read_data_pipeline_cycles;
  const std::uint64_t port_write_buffer_pipeline_cycles =
      maintenance_port && maintenance_write_buffer_pipeline_cycles != 0
          ? maintenance_write_buffer_pipeline_cycles
          : write_buffer_pipeline_cycles;
  const bool port_serialize_write_bursts =
      maintenance_port && maintenance_serialize_write_bursts
          ? true
          : serialize_write_bursts;
  const std::size_t port_write_ingress_fifo_depth =
      maintenance_port && maintenance_write_ingress_fifo_depth != 0
          ? maintenance_write_ingress_fifo_depth
          : write_ingress_fifo_depth;
  const std::size_t port_write_throttle_fifo_depth =
      maintenance_port && maintenance_write_throttle_fifo_depth != 0
          ? maintenance_write_throttle_fifo_depth
          : write_throttle_fifo_depth;
  const std::uint64_t port_write_ingress_pipeline_cycles =
      maintenance_port && maintenance_write_ingress_fifo_depth != 0
          ? maintenance_write_ingress_pipeline_cycles
          : write_ingress_pipeline_cycles;
  const std::uint64_t port_write_address_after_full_burst_cycles =
      maintenance_port && maintenance_write_ingress_fifo_depth != 0
          ? maintenance_write_address_after_full_burst_cycles
          : write_address_after_full_burst_cycles;
  return FixedAxiPortConfig{
      .memory_channels = memory_channels,
      .channel = channel,
      .initiator_id = initiator_id,
      .data_width_bytes = width,
      .max_burst_beats = max_burst_beats,
      .read_reorder_capacity = port_read_reorder_capacity,
      .stream_read_beats =
          (kind == SpineAxiPortKind::kSortedEdges &&
           sorted_edge_bytes == kSpineSortWordBytes) ||
          kind == SpineAxiPortKind::kVertexState,
      .max_pending_requests = max_pending,
      .max_outstanding_bursts = max_outstanding_bursts,
      .response_beats_per_cycle = response_beats_per_cycle,
      .read_address_pipeline_cycles = port_read_address_pipeline_cycles,
      .read_data_pipeline_cycles = port_read_data_pipeline_cycles,
      .write_buffer_pipeline_cycles = port_write_buffer_pipeline_cycles,
      .serialize_write_bursts = port_serialize_write_bursts,
      .write_ingress_fifo_depth = port_write_ingress_fifo_depth,
      .write_throttle_fifo_depth = port_write_throttle_fifo_depth,
      .write_ingress_pipeline_cycles = port_write_ingress_pipeline_cycles,
      .write_address_after_full_burst_cycles =
          port_write_address_after_full_burst_cycles,
      .burst_trace_limit = burst_trace_limit,
  };
}

SpineVerticalSliceSystem::SpineVerticalSliceSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    SpineEdgeSlice workload, std::uint32_t source, std::size_t tiny_threshold,
    SpineL0Config maintenance_config, SpineL0State initial_state,
    SpineAxiInterfaceProfile axi_profile,
    std::size_t compute_memory_request_window,
    std::size_t compute_writeonly_request_window,
    SpineOnChipMemoryProfile on_chip_profile, bool initial_host_active,
    std::optional<AlgorithmInitialState> algorithm_initial_state,
    std::optional<SpineOwnerSchedulerConfig> owner_scheduler_config,
    std::optional<SpineVertexLifecycleConfig> vertex_lifecycle_config)
    : scheduler_(scheduler), clock_id_(clock_id), backend_(backend),
      axi_profile_(std::move(axi_profile)),
      source_(source),
      edge_stream_("edge-axis", clock_id, 32),
      value_stream_("value-axis", clock_id, 32),
      state_(std::move(initial_state)),
      current_frontier_(algorithm_initial_state.has_value()
                            ? algorithm_initial_state->active_vertices
                            : std::vector<std::uint32_t>{source}),
      resident_bootstrap_pending_(initial_host_active) {
  if (source >= workload.vertices) {
    throw std::invalid_argument("Spine vertical-slice source is out of range");
  }
  for (std::size_t family = 0; family < graph_ports_.size(); ++family) {
    graph_ports_[family] = make_port("graph" + std::to_string(family),
                                     static_cast<std::uint32_t>(family), family,
                                     SpineAxiPortKind::kGraph);
  }
  sorted_ = make_port("sorted-edges", 16, 16, SpineAxiPortKind::kSortedEdges);
  active_bins_ =
      make_port("active-bins", 18, 18, SpineAxiPortKind::kActiveBins);
  metadata_ = make_port("metadata", 20, 20, SpineAxiPortKind::kMetadata);
  maintenance_result_ = make_port("maintenance-result", 21, 21,
                                  SpineAxiPortKind::kMaintenanceResult);

  // Compute is a separate CU, so initiator IDs differ even when a pseudo-
  // channel is shared with the fused read-maintenance CU.
  vertex_state_ =
      make_port("vertex-state", 117, 17, SpineAxiPortKind::kVertexState);
  active_out_ = make_port("active-out", 119, 19, SpineAxiPortKind::kActiveOut);
  active_out_reader_ =
      make_port("active-out-reader", 118, 19, SpineAxiPortKind::kActiveOut);
  compute_result_ =
      make_port("compute-result", 121, 21, SpineAxiPortKind::kComputeResult);
  active_bitmap_ =
      make_port("active-bitmap", 122, 22, SpineAxiPortKind::kActiveBitmap);
  if (vertex_lifecycle_config.has_value()) {
    if (vertex_lifecycle_config->max_vertices != workload.vertices ||
        vertex_lifecycle_config->initial_valid_vertices > workload.vertices ||
        vertex_lifecycle_config->bitmap_base < 8 ||
        vertex_lifecycle_config->bitmap_base % sizeof(std::uint64_t) != 0) {
      throw std::invalid_argument(
          "Spine vertex lifecycle must cover the fixed graph domain in a "
          "non-overlapping aligned bitmap region");
    }
    vertex_validity_ = make_port("vertex-validity", 123, 22,
                                 SpineAxiPortKind::kActiveBitmap);
    vertex_lifecycle_ = std::make_unique<SpineVertexLifecycle>(
        "spine-vertex-lifecycle", clock_id_, *vertex_lifecycle_config,
        *vertex_validity_);
    if (std::any_of(workload.edges.begin(), workload.edges.end(),
                    [this](const SpineEdgeRecord &edge) {
                      return !vertex_lifecycle_->valid(edge.src) ||
                             !vertex_lifecycle_->valid(edge.dst);
                    })) {
      throw std::invalid_argument(
          "Spine initial graph references an invalid vertex");
    }
  }

  SpineL0Ports maintenance_ports;
  SpineReaderPorts reader_ports;
  for (std::size_t family = 0; family < graph_ports_.size(); ++family) {
    maintenance_ports.graph[family] = graph_ports_[family].get();
    reader_ports.graph[family] = graph_ports_[family].get();
  }
  maintenance_ports.sorted_edges = sorted_.get();
  maintenance_ports.metadata = metadata_.get();
  maintenance_ports.result = maintenance_result_.get();
  reader_ports.task_scratch = sorted_.get();
  reader_ports.active_bins = active_bins_.get();
  reader_ports.active_out = active_out_reader_.get();
  reader_ports.metadata = metadata_.get();
  reader_ports.result = maintenance_result_.get();

  const std::size_t vertices = workload.vertices;
  if (owner_scheduler_config.has_value()) {
    if (owner_scheduler_config->max_vertices < vertices) {
      throw std::invalid_argument(
          "Spine owner scheduler does not cover the graph vertex domain");
    }
    owner_scheduler_ = std::make_unique<SpineOwnerScheduler>(
        "spine-device-owner", clock_id_, *owner_scheduler_config);
  }
  const auto algorithm_policy = std::make_shared<const GraphAlgorithmPolicy>(
      AlgorithmPolicyConfig{
          .kind = GraphAlgorithmKind::kWeightedSssp,
          .vertices = vertices,
          .source = source,
      });
  maintenance_ = std::make_unique<SpineL0Maintenance>(
      "spine-l0-maintenance", clock_id_, std::move(maintenance_config),
      std::move(workload), maintenance_ports, state_);
  reader_ = std::make_unique<SpineSplitReader>(
      "spine-split-reader", clock_id_, *maintenance_, reader_ports,
      current_frontier_, edge_stream_, value_stream_,
      initial_host_active ? SpineReaderMode::kHostActive
                          : SpineReaderMode::kDeviceDirty,
      algorithm_policy);
  compute_ = std::make_unique<SpineSplitSsspCompute>(
      "spine-split-compute", clock_id_, vertices, source, tiny_threshold,
      SpineComputePorts{
          .vertex_state = vertex_state_.get(),
          .active_out = active_out_.get(),
          .active_bitmap = active_bitmap_.get(),
          .result = compute_result_.get(),
      },
      edge_stream_, value_stream_, compute_memory_request_window,
      compute_writeonly_request_window, on_chip_profile, algorithm_policy,
      std::move(algorithm_initial_state), owner_scheduler_.get());
  if (initial_host_active) {
    SpineActiveBins bins = build_spine_host_active_bins(
        state_, maintenance_->config(), current_frontier_, compute_->values());
    reader_->configure_initial_host_round(std::move(bins), std::nullopt, {});
  }
  dirty_ack_ = std::make_unique<SpineDirtyAck>(
      "spine-dirty-ack", clock_id_, maintenance_->config(),
      SpineDirtyAckPorts{
          .task_scratch = sorted_.get(),
          .metadata = metadata_.get(),
          .result = maintenance_result_.get(),
      });
}

std::unique_ptr<FixedAxiPort> SpineVerticalSliceSystem::make_port(
    const std::string &name, std::uint32_t initiator_id, std::size_t channel,
    SpineAxiPortKind kind) {
  return std::make_unique<FixedAxiPort>(
      name, clock_id_,
      axi_profile_.port_config(kind, 32, channel, initiator_id), backend_);
}

void SpineVerticalSliceSystem::register_components() {
  if (registered_) {
    throw std::logic_error(
        "Spine vertical-slice components already registered");
  }
  registered_ = true;
  scheduler_.add_component(*maintenance_);
  scheduler_.add_component(*reader_);
  scheduler_.add_component(*compute_);
  if (owner_scheduler_ != nullptr) {
    scheduler_.add_component(*owner_scheduler_);
  }
  if (vertex_lifecycle_ != nullptr) {
    scheduler_.add_component(*vertex_lifecycle_);
  }
  scheduler_.add_component(*dirty_ack_);
  scheduler_.add_component(edge_stream_);
  scheduler_.add_component(value_stream_);
  for (auto &port : graph_ports_) {
    port->register_components(scheduler_);
  }
  sorted_->register_components(scheduler_);
  active_bins_->register_components(scheduler_);
  metadata_->register_components(scheduler_);
  maintenance_result_->register_components(scheduler_);
  vertex_state_->register_components(scheduler_);
  active_out_->register_components(scheduler_);
  active_out_reader_->register_components(scheduler_);
  compute_result_->register_components(scheduler_);
  active_bitmap_->register_components(scheduler_);
  if (vertex_validity_ != nullptr) {
    vertex_validity_->register_components(scheduler_);
  }
}

void SpineVerticalSliceSystem::advance_owner_control_cycle(
    std::uint64_t max_events) {
  const std::uint64_t before = scheduler_.clock(clock_id_).completed_cycles;
  scheduler_.run_until(
      [this, before] {
        return scheduler_.clock(clock_id_).completed_cycles > before;
      },
      max_events);
  owner_control_cycles_ +=
      scheduler_.clock(clock_id_).completed_cycles - before;
}

std::vector<std::uint32_t> SpineVerticalSliceSystem::owner_admit_and_dispatch(
    const std::vector<std::uint32_t> &frontier, bool admit,
    std::uint64_t max_events) {
  if (owner_scheduler_ == nullptr || frontier.empty()) {
    return frontier;
  }
  if (vertex_lifecycle_ != nullptr &&
      std::any_of(frontier.begin(), frontier.end(), [this](std::uint32_t key) {
        return !vertex_lifecycle_->valid(key);
      })) {
    throw std::logic_error(
        "Spine owner cannot admit an invalid vertex into the frontier");
  }
  const std::uint64_t start_events = scheduler_.event_count();
  const auto check_budget = [this, start_events, max_events] {
    if (scheduler_.event_count() - start_events >= max_events) {
      throw std::runtime_error(
          "Spine owner dispatch exceeded the round event budget");
    }
  };
  if (admit) {
    for (const std::uint32_t key : frontier) {
      while (!owner_scheduler_->try_activate(key)) {
        check_budget();
        advance_owner_control_cycle(max_events);
      }
      check_budget();
      advance_owner_control_cycle(max_events);
    }
  }

  std::vector<std::uint32_t> dispatched;
  dispatched.reserve(frontier.size());
  while (dispatched.size() < frontier.size()) {
    check_budget();
    bool staged = false;
    for (std::size_t partition = 0;
         partition < owner_scheduler_->config().partitions &&
         dispatched.size() < frontier.size();
         ++partition) {
      std::uint32_t key = 0;
      if (owner_scheduler_->try_dispatch(partition, key)) {
        dispatched.push_back(key);
        staged = true;
      }
    }
    advance_owner_control_cycle(max_events);
    if (!staged && owner_scheduler_->work_credits() == 0) {
      throw std::logic_error(
          "Spine owner lost frontier work before device dispatch");
    }
  }

  std::vector<std::uint32_t> expected = frontier;
  std::vector<std::uint32_t> actual = dispatched;
  std::sort(expected.begin(), expected.end());
  std::sort(actual.begin(), actual.end());
  if (expected != actual) {
    throw std::logic_error(
        "Spine owner dispatch does not match device-generated frontier");
  }
  return dispatched;
}

void SpineVerticalSliceSystem::owner_complete_frontier(
    const std::vector<std::uint32_t> &frontier,
    std::uint64_t max_events) {
  if (owner_scheduler_ == nullptr || frontier.empty()) {
    return;
  }
  const std::uint64_t start_events = scheduler_.event_count();
  std::vector<std::deque<std::uint32_t>> pending(
      owner_scheduler_->config().partitions);
  for (const std::uint32_t key : frontier) {
    pending.at(owner_scheduler_->partition_for(key)).push_back(key);
  }
  std::size_t remaining = frontier.size();
  while (remaining != 0) {
    if (scheduler_.event_count() - start_events >= max_events) {
      throw std::runtime_error(
          "Spine owner completion exceeded the round event budget");
    }
    bool staged = false;
    for (std::size_t partition = 0; partition < pending.size(); ++partition) {
      if (pending[partition].empty()) {
        continue;
      }
      const std::uint32_t key = pending[partition].front();
      if (owner_scheduler_->try_complete(key)) {
        pending[partition].pop_front();
        --remaining;
        staged = true;
      }
    }
    if (!staged) {
      throw std::logic_error(
          "Spine owner could not retire an in-flight frontier");
    }
    advance_owner_control_cycle(max_events);
  }
}

void SpineVerticalSliceSystem::restart_device_active_compute(
    std::vector<std::uint32_t> active_sources) {
  if (!registered_ || !done() || !idle() || failed() ||
      active_sources.empty()) {
    throw std::logic_error(
        "Spine device-active restart requires a successful drained round");
  }
  edge_stream_.reset_stats();
  value_stream_.reset_stats();
  reader_->reset_active_list_round(active_sources.size());
  compute_->reset_round();
  current_frontier_ = std::move(active_sources);
}

void SpineVerticalSliceSystem::restart_read_compute(
    std::vector<std::uint32_t> active_sources,
    std::optional<SpineDirtyIdentity> host_coverage) {
  if (!registered_ || !done() || !idle() || failed() ||
      active_sources.empty()) {
    throw std::logic_error(
        "Spine read/compute restart requires a successful drained round");
  }
  const SpineActiveBins bins = build_spine_host_active_bins(
      state_, maintenance_->config(), active_sources, compute_->values());
  restart_read_compute_bins(bins, host_coverage);
  current_frontier_ = std::move(active_sources);
}

void SpineVerticalSliceSystem::restart_read_compute_bins(
    const SpineActiveBins &active_bins,
    std::optional<SpineDirtyIdentity> host_coverage,
    std::vector<std::uint32_t> source_refresh) {
  const bool recovering = recoverable_host_handoff();
  if (!registered_ || !done() || !idle() || (failed() && !recovering)) {
    throw std::logic_error(
        "Spine host-bin restart requires a successful drained round");
  }
  edge_stream_.reset_stats();
  value_stream_.reset_stats();
  reader_->reset_host_round(active_bins, host_coverage, source_refresh);
  if (recovering) {
    compute_->reset_after_host_handoff();
  } else {
    compute_->reset_round();
  }
  current_frontier_.clear();
  std::unordered_set<std::uint32_t> seen;
  for (const std::uint32_t source : source_refresh) {
    if (seen.insert(source).second) {
      current_frontier_.push_back(source);
    }
  }
  for (const auto &bin : active_bins.bins) {
    for (const SpineActiveRecord &record : bin) {
      if (seen.insert(record.source).second) {
        current_frontier_.push_back(record.source);
      }
    }
  }
}

void SpineVerticalSliceSystem::restart_incremental_update(
    SpineEdgeSlice workload) {
  const bool resident_bootstrap =
      resident_bootstrap_pending_ && !dirty_ack_->started();
  if (!registered_ || !done() || failed() || !idle() ||
      (!resident_bootstrap && !dirty_ack_->done()) || dirty_ack_->failed() ||
      workload.vertices != maintenance_->vertices() ||
      workload.edges.empty() ||
      std::any_of(workload.edges.begin(), workload.edges.end(),
                  [](const SpineEdgeRecord &edge) { return edge.diff <= 0; })) {
    throw std::logic_error(
        "Spine incremental update requires a positive drained batch");
  }
  if (vertex_lifecycle_ != nullptr &&
      std::any_of(workload.edges.begin(), workload.edges.end(),
                  [this](const SpineEdgeRecord &edge) {
                    return !vertex_lifecycle_->valid(edge.src) ||
                           !vertex_lifecycle_->valid(edge.dst);
                  })) {
    throw std::logic_error(
        "Spine incremental update references an invalid vertex");
  }
  std::vector<std::uint32_t> changed_sources;
  changed_sources.reserve(workload.edges.size());
  for (const SpineEdgeRecord &edge : workload.edges) {
    changed_sources.push_back(edge.src);
  }
  std::sort(changed_sources.begin(), changed_sources.end());
  changed_sources.erase(
      std::unique(changed_sources.begin(), changed_sources.end()),
      changed_sources.end());

  edge_stream_.reset_stats();
  value_stream_.reset_stats();
  if (!resident_bootstrap) {
    dirty_ack_->reset();
  }
  reader_->reset_round(changed_sources);
  compute_->reset_round();
  maintenance_->reset_batch(std::move(workload));
  current_frontier_ = std::move(changed_sources);
  resident_bootstrap_pending_ = false;
  convergence_run_started_ = false;
}

void SpineVerticalSliceSystem::restart_full_rebuild(SpineEdgeSlice snapshot) {
  const bool resident_bootstrap =
      resident_bootstrap_pending_ && !dirty_ack_->started();
  if (!registered_ || !done() || failed() || !idle() ||
      (!resident_bootstrap && !dirty_ack_->done()) || dirty_ack_->failed() ||
      snapshot.vertices != maintenance_->vertices() || snapshot.edges.empty() ||
      std::any_of(snapshot.edges.begin(), snapshot.edges.end(),
                  [](const SpineEdgeRecord &edge) { return edge.diff <= 0; })) {
    throw std::logic_error(
        "Spine full rebuild requires a positive drained graph snapshot");
  }
  if (vertex_lifecycle_ != nullptr &&
      std::any_of(snapshot.edges.begin(), snapshot.edges.end(),
                  [this](const SpineEdgeRecord &edge) {
                    return !vertex_lifecycle_->valid(edge.src) ||
                           !vertex_lifecycle_->valid(edge.dst);
                  })) {
    throw std::logic_error(
        "Spine full rebuild references an invalid vertex");
  }

  edge_stream_.reset_stats();
  value_stream_.reset_stats();
  if (!resident_bootstrap) {
    dirty_ack_->reset();
  }
  reader_->reset_round({source_});
  compute_->reset_for_full_recompute();
  maintenance_->reset_full_rebuild(std::move(snapshot));
  current_frontier_ = {source_};
  resident_bootstrap_pending_ = false;
  convergence_run_started_ = false;
}

bool SpineVerticalSliceSystem::recoverable_host_handoff() const noexcept {
  return registered_ && maintenance_->done() && !maintenance_->failed() &&
         reader_->recoverable_host_handoff() &&
         compute_->recoverable_host_handoff() && idle();
}

std::vector<std::uint32_t>
SpineVerticalSliceSystem::restart_device_dirty_host_fallback() {
  if (!recoverable_host_handoff()) {
    throw std::logic_error(
        "device-dirty host fallback requires a drained REQUIRES_HOST result");
  }
  const SpineReaderCounters &reader = reader_->counters();
  const std::size_t count = reader.dirty_count;
  const std::size_t bytes = ((count + 3) / 4) * kSpineSortWordBytes;
  const std::vector<std::uint8_t> payload = backend_.inspect_payload(
      sorted_->channel(), maintenance_->config().persistent_dirty_list_base,
      bytes);
  std::vector<std::uint32_t> sources(count, 0);
  for (std::size_t index = 0; index < count; ++index) {
    const std::size_t offset = index * sizeof(std::uint32_t);
    sources[index] = static_cast<std::uint32_t>(payload[offset]) |
                     (static_cast<std::uint32_t>(payload[offset + 1]) << 8) |
                     (static_cast<std::uint32_t>(payload[offset + 2]) << 16) |
                     (static_cast<std::uint32_t>(payload[offset + 3]) << 24);
  }
  const SpineDirtyIdentity coverage =
      spine_dirty_identity(reader.dirty_generation, sources);
  if (coverage.count != reader.dirty_count ||
      coverage.hash_sum != reader.dirty_hash_sum ||
      coverage.hash_xor != reader.dirty_hash_xor) {
    throw std::logic_error(
        "host handoff list does not match the captured dirty identity");
  }
  const SpineActiveBins bins = build_spine_host_active_bins(
      state_, maintenance_->config(), sources, compute_->values());
  restart_read_compute_bins(bins, coverage);
  current_frontier_ = sources;
  return sources;
}

void SpineVerticalSliceSystem::start_dirty_ack() {
  if (!registered_ || !maintenance_->done() || !reader_->done() ||
      !compute_->done() || !idle() || dirty_ack_->started()) {
    throw std::logic_error(
        "dirty ACK requires a drained successful convergence round");
  }
  const auto &reader = reader_->counters();
  const auto &compute = compute_->counters();
  const bool can_ack =
      !failed() &&
      reader.dirty_status ==
          static_cast<std::uint32_t>(SpineDirtyStatus::kOk) &&
      reader.acknowledgement_eligible && !compute.done_overflow &&
      compute.range_task_error == 0 && compute.source_protocol_status == 0 &&
      compute.dirty_generation == reader.dirty_generation &&
      compute.dirty_count == reader.dirty_count;
  if (!can_ack) {
    throw std::logic_error(
        "failed convergence result cannot publish a dirty ACK candidate");
  }
  dirty_ack_->start(
      compute.dirty_generation,
      SpineDirtyIdentity{
          .generation = compute.dirty_generation,
          .count = compute.dirty_count,
          .hash_sum = reader.dirty_hash_sum,
          .hash_xor = reader.dirty_hash_xor,
      });
}

bool SpineVerticalSliceSystem::dirty_ack_started() const noexcept {
  return dirty_ack_->started();
}

bool SpineVerticalSliceSystem::dirty_ack_done() const noexcept {
  return dirty_ack_->done();
}

bool SpineVerticalSliceSystem::resident_bootstrap_pending() const noexcept {
  return resident_bootstrap_pending_;
}

SpineSsspRunResult SpineVerticalSliceSystem::run_sssp_to_convergence(
    std::size_t max_rounds, std::uint64_t max_events_per_round) {
  if (!registered_ || convergence_run_started_ || done() || max_rounds == 0 ||
      max_events_per_round == 0) {
    throw std::logic_error("invalid Spine convergence-run state or limits");
  }
  if (vertex_lifecycle_ != nullptr &&
      std::any_of(current_frontier_.begin(), current_frontier_.end(),
                  [this](std::uint32_t vertex) {
                    return !vertex_lifecycle_->valid(vertex);
                  })) {
    throw std::logic_error(
        "Spine convergence frontier contains an invalid vertex");
  }
  convergence_run_started_ = true;
  SpineSsspRunResult result;
  result.start_cycle = scheduler_.clock(clock_id_).completed_cycles;
  owner_control_cycles_ = 0;
  if (owner_scheduler_ != nullptr) {
    if (!owner_scheduler_->quiescent() || !owner_scheduler_->ledger_closed()) {
      throw std::logic_error(
          "Spine convergence run started with an open owner ledger");
    }
    current_frontier_ = owner_admit_and_dispatch(
        current_frontier_, true, max_events_per_round);
  }
  for (std::size_t round = 0; round < max_rounds; ++round) {
    const std::uint64_t start_cycle =
        scheduler_.clock(clock_id_).completed_cycles;
    const std::vector<std::uint32_t> attempted_active_in = current_frontier_;
    scheduler_.run_until([this] { return done() && idle(); },
                         max_events_per_round);
    if (recoverable_host_handoff()) {
      const std::uint64_t device_end_cycle =
          scheduler_.clock(clock_id_).completed_cycles;
      SpineSsspRoundEvidence device_attempt{
          .round = round,
          .active_in = attempted_active_in,
          .reader_sources = reader_->active_source_ids(),
          .active_out = compute_->next_active(),
          .reader = reader_->counters(),
          .compute = compute_->counters(),
          .edge_axis = edge_stream_.stats(),
          .value_axis = value_stream_.stats(),
          .start_cycle = start_cycle,
          .end_cycle = device_end_cycle,
      };
      const std::uint32_t fallback_reason =
          reader_->counters().range_task_fallback_reason;
      const std::vector<std::uint32_t> sources =
          restart_device_dirty_host_fallback();
      result.host_handoffs.push_back(SpineHostHandoffEvidence{
          .logical_round = round,
          .fallback_reason = fallback_reason,
          .source_count = sources.size(),
          .host_list_read_bytes =
              ((sources.size() + 3) / 4) * kSpineSortWordBytes,
          .host_control_cycles = 0,
          .host_control_timed = false,
          .device_attempt = std::move(device_attempt),
      });
      scheduler_.run_until([this] { return done() && idle(); },
                           max_events_per_round);
    }
    const std::uint64_t end_cycle =
        scheduler_.clock(clock_id_).completed_cycles;
    const std::vector<std::uint32_t> active_out = compute_->next_active();
    result.rounds.push_back(SpineSsspRoundEvidence{
        .round = round,
        .active_in = attempted_active_in,
        .reader_sources = reader_->active_source_ids(),
        .active_out = active_out,
        .reader = reader_->counters(),
        .compute = compute_->counters(),
        .edge_axis = edge_stream_.stats(),
        .value_axis = value_stream_.stats(),
        .start_cycle = start_cycle,
        .end_cycle = end_cycle,
    });
    if (failed()) {
      result.failed = true;
      break;
    }
    owner_complete_frontier(attempted_active_in, max_events_per_round);
    if (round == 0 && !resident_bootstrap_pending_) {
      start_dirty_ack();
      scheduler_.run_until(
          [this] { return dirty_ack_->done() && idle(); },
          max_events_per_round);
      result.dirty_ack = dirty_ack_->counters();
      if (dirty_ack_->failed()) {
        result.failed = true;
        break;
      }
    }
    if (active_out.empty()) {
      result.converged = owner_scheduler_ == nullptr ||
                         (owner_scheduler_->quiescent() &&
                          owner_scheduler_->ledger_closed());
      break;
    }
    if (round + 1 < max_rounds) {
      const std::vector<std::uint32_t> dispatched =
          owner_admit_and_dispatch(active_out, false, max_events_per_round);
      restart_device_active_compute(dispatched);
    }
  }
  result.end_cycle = scheduler_.clock(clock_id_).completed_cycles;
  if (owner_scheduler_ != nullptr) {
    result.owner_scheduler = owner_scheduler_->stats();
    result.owner_ledger_closed = owner_scheduler_->ledger_closed();
    result.owner_quiescent = owner_scheduler_->quiescent();
    result.owner_control_cycles = owner_control_cycles_;
    if (result.converged &&
        (!result.owner_ledger_closed || !result.owner_quiescent)) {
      result.converged = false;
      result.failed = true;
    }
  }
  return result;
}

bool SpineVerticalSliceSystem::try_activate_vertex(std::uint32_t vertex) {
  if (!registered_ || vertex_lifecycle_ == nullptr || !done() || !idle() ||
      failed() ||
      (owner_scheduler_ != nullptr && !owner_scheduler_->quiescent())) {
    throw std::logic_error(
        "Spine vertex activation requires a drained graph transaction");
  }
  return vertex_lifecycle_->try_activate(vertex);
}

bool SpineVerticalSliceSystem::try_deactivate_vertex(
    std::uint32_t vertex, bool incident_edges_retired_or_masked) {
  if (!registered_ || vertex_lifecycle_ == nullptr || !done() || !idle() ||
      failed() ||
      (owner_scheduler_ != nullptr && !owner_scheduler_->quiescent())) {
    throw std::logic_error(
        "Spine vertex deactivation requires a drained graph transaction");
  }
  return vertex_lifecycle_->try_deactivate(
      vertex, incident_edges_retired_or_masked);
}

SpineVertexLifecycleResult
SpineVerticalSliceSystem::run_vertex_lifecycle_to_completion(
    std::uint64_t max_events) {
  if (!registered_ || vertex_lifecycle_ == nullptr ||
      !vertex_lifecycle_->busy() || max_events == 0) {
    throw std::logic_error("invalid Spine vertex lifecycle run state");
  }
  scheduler_.run_until(
      [this] {
        return !vertex_lifecycle_->busy() && vertex_validity_->idle();
      },
      max_events);
  if (vertex_lifecycle_->failed() ||
      !vertex_lifecycle_->last_result().has_value() ||
      !vertex_lifecycle_->request_ledger_closed()) {
    throw std::logic_error(
        vertex_lifecycle_->failed()
            ? vertex_lifecycle_->failure()
            : "Spine vertex lifecycle completed without closed evidence");
  }
  return *vertex_lifecycle_->last_result();
}

bool SpineVerticalSliceSystem::done() const noexcept {
  return maintenance_->done() && reader_->done() && compute_->done() &&
         (!dirty_ack_->started() || dirty_ack_->done()) &&
         (vertex_lifecycle_ == nullptr || !vertex_lifecycle_->busy());
}

bool SpineVerticalSliceSystem::failed() const noexcept {
  return maintenance_->failed() || reader_->failed() || compute_->failed() ||
         (dirty_ack_->started() && dirty_ack_->failed()) ||
         (vertex_lifecycle_ != nullptr && vertex_lifecycle_->failed());
}

bool SpineVerticalSliceSystem::idle() const noexcept {
  for (const auto &port : graph_ports_) {
    if (!port->idle()) {
      return false;
    }
  }
  return sorted_->idle() && active_bins_->idle() && metadata_->idle() &&
         maintenance_result_->idle() && vertex_state_->idle() &&
         active_out_->idle() && active_out_reader_->idle() &&
         compute_result_->idle() &&
         active_bitmap_->idle() && edge_stream_.empty() &&
         value_stream_.empty() &&
         (vertex_validity_ == nullptr || vertex_validity_->idle());
}

const SpineL0Counters &SpineVerticalSliceSystem::maintenance_counters()
    const noexcept {
  return maintenance_->counters();
}

const SpineReaderCounters &SpineVerticalSliceSystem::reader_counters()
    const noexcept {
  return reader_->counters();
}

std::vector<std::uint32_t> SpineVerticalSliceSystem::reader_source_ids() const {
  return reader_->active_source_ids();
}

const SpineComputeCounters &SpineVerticalSliceSystem::compute_counters()
    const noexcept {
  return compute_->counters();
}

const SpineDirtyAckCounters &SpineVerticalSliceSystem::dirty_ack_counters()
    const noexcept {
  return dirty_ack_->counters();
}

const SpineSplitSsspCompute &SpineVerticalSliceSystem::compute()
    const noexcept {
  return *compute_;
}

const SpineL0State &SpineVerticalSliceSystem::level_state() const noexcept {
  return state_;
}

const FifoStats &SpineVerticalSliceSystem::edge_stream_stats() const noexcept {
  return edge_stream_.stats();
}

const FifoStats &SpineVerticalSliceSystem::value_stream_stats() const noexcept {
  return value_stream_.stats();
}

const AxiConfig &
SpineVerticalSliceSystem::axi_config(SpineAxiPortKind kind) const {
  switch (kind) {
  case SpineAxiPortKind::kGraph:
    return graph_ports_[0]->master().config();
  case SpineAxiPortKind::kSortedEdges:
    return sorted_->master().config();
  case SpineAxiPortKind::kActiveBins:
    return active_bins_->master().config();
  case SpineAxiPortKind::kMetadata:
    return metadata_->master().config();
  case SpineAxiPortKind::kMaintenanceResult:
    return maintenance_result_->master().config();
  case SpineAxiPortKind::kVertexState:
    return vertex_state_->master().config();
  case SpineAxiPortKind::kActiveOut:
    return active_out_->master().config();
  case SpineAxiPortKind::kActiveBitmap:
    return active_bitmap_->master().config();
  case SpineAxiPortKind::kComputeResult:
    return compute_result_->master().config();
  }
  throw std::logic_error("unknown Spine AXI port kind");
}

const AxiStats &
SpineVerticalSliceSystem::axi_stats(SpineAxiPortKind kind) const {
  switch (kind) {
  case SpineAxiPortKind::kGraph:
    return graph_ports_[0]->master().stats();
  case SpineAxiPortKind::kSortedEdges:
    return sorted_->master().stats();
  case SpineAxiPortKind::kActiveBins:
    return active_bins_->master().stats();
  case SpineAxiPortKind::kMetadata:
    return metadata_->master().stats();
  case SpineAxiPortKind::kMaintenanceResult:
    return maintenance_result_->master().stats();
  case SpineAxiPortKind::kVertexState:
    return vertex_state_->master().stats();
  case SpineAxiPortKind::kActiveOut:
    return active_out_->master().stats();
  case SpineAxiPortKind::kActiveBitmap:
    return active_bitmap_->master().stats();
  case SpineAxiPortKind::kComputeResult:
    return compute_result_->master().stats();
  }
  throw std::logic_error("unknown Spine AXI port kind");
}

AxiStats SpineVerticalSliceSystem::maintenance_axi_stats() const noexcept {
  AxiStats total;
  for (const auto &port : graph_ports_) {
    accumulate_axi_stats(total, port->master().stats());
  }
  accumulate_axi_stats(total, sorted_->master().stats());
  accumulate_axi_stats(total, metadata_->master().stats());
  accumulate_axi_stats(total, maintenance_result_->master().stats());
  return total;
}

SpinePageRankVerticalSliceSystem::SpinePageRankVerticalSliceSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    SpineEdgeSlice workload, float damping,
    SpineL0Config maintenance_config, SpineAxiInterfaceProfile axi_profile,
    AlgorithmPipelineConfig pipeline_config,
    std::size_t compute_memory_request_window, SpineL0State initial_state,
    std::optional<SpineEdgeSlice> execution_graph,
    std::optional<SpineDirtyIdentity> host_coverage,
    std::optional<AlgorithmInitialState> algorithm_initial_state,
    std::optional<SpineResidualCorrectionPlan> device_residual_correction,
    std::optional<SpineOwnerSchedulerConfig> owner_scheduler_config,
    std::optional<SpineVertexLifecycleConfig> vertex_lifecycle_config)
    : SpinePageRankVerticalSliceSystem(
          scheduler, clock_id, backend, workload,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kFullPageRank,
              .vertices = workload.vertices,
              .source = 0,
              .damping = damping,
          }),
          std::move(maintenance_config), std::move(axi_profile),
          std::move(pipeline_config), compute_memory_request_window,
          std::move(initial_state), std::move(execution_graph),
          host_coverage, std::move(algorithm_initial_state),
          std::move(device_residual_correction),
          std::move(owner_scheduler_config),
          std::move(vertex_lifecycle_config)) {}

SpinePageRankVerticalSliceSystem::SpinePageRankVerticalSliceSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    SpineEdgeSlice workload, GraphAlgorithmPolicy policy,
    SpineL0Config maintenance_config, SpineAxiInterfaceProfile axi_profile,
    AlgorithmPipelineConfig pipeline_config,
    std::size_t compute_memory_request_window, SpineL0State initial_state,
    std::optional<SpineEdgeSlice> execution_graph,
    std::optional<SpineDirtyIdentity> host_coverage,
    std::optional<AlgorithmInitialState> algorithm_initial_state,
    std::optional<SpineResidualCorrectionPlan> device_residual_correction,
    std::optional<SpineOwnerSchedulerConfig> owner_scheduler_config,
    std::optional<SpineVertexLifecycleConfig> vertex_lifecycle_config)
    : scheduler_(scheduler),
      clock_id_(clock_id),
      backend_(backend),
      axi_profile_(std::move(axi_profile)),
      maintenance_config_(maintenance_config),
      edge_stream_("pagerank-edge-axis", clock_id, 32),
      value_stream_("pagerank-value-axis", clock_id, 32),
      state_(std::move(initial_state)) {
  const SpineEdgeSlice &logical_graph =
      execution_graph.has_value() ? *execution_graph : workload;
  if (logical_graph.vertices != workload.vertices ||
      policy.config().vertices != logical_graph.vertices ||
      (policy.config().kind != GraphAlgorithmKind::kFullPageRank &&
       policy.config().kind != GraphAlgorithmKind::kResidualPageRank &&
       policy.config().kind != GraphAlgorithmKind::kConnectedComponents)) {
    throw std::invalid_argument("invalid Spine PageRank system policy");
  }
  PageRankHostInput host =
      build_pagerank_host_input(logical_graph, maintenance_config);
  if (algorithm_initial_state.has_value()) {
    const std::unordered_set<std::uint32_t> active(
        algorithm_initial_state->active_vertices.begin(),
        algorithm_initial_state->active_vertices.end());
    const bool residual_warm_start =
        policy.config().kind == GraphAlgorithmKind::kResidualPageRank;
    if (algorithm_initial_state->primary.size() != logical_graph.vertices ||
        (residual_warm_start &&
         algorithm_initial_state->auxiliary.size() != logical_graph.vertices) ||
        active.size() != algorithm_initial_state->active_vertices.size() ||
        std::any_of(active.begin(), active.end(),
                    [&logical_graph](std::uint32_t vertex) {
                      return vertex >= logical_graph.vertices;
                    })) {
      throw std::invalid_argument("invalid Spine algorithm warm-start frontier");
    }
    host.sources = algorithm_initial_state->active_vertices;
    for (auto &bin : host.bins.bins) {
      bin.erase(std::remove_if(bin.begin(), bin.end(),
                               [&active](const SpineActiveRecord &record) {
                                 return !active.contains(record.source);
                               }),
                bin.end());
      for (SpineActiveRecord &record : bin) {
        record.source_value =
            residual_warm_start ? algorithm_initial_state->auxiliary[record.source]
                                : algorithm_initial_state->primary[record.source];
      }
    }
  }
  if (host_coverage.has_value()) {
    host.coverage = host_coverage;
  }
  if (device_residual_correction.has_value()) {
    const SpineResidualCorrectionPlan &plan = *device_residual_correction;
    const bool valid_sizes =
        plan.old_rank_words.size() == logical_graph.vertices &&
        plan.old_out_degrees.size() == logical_graph.vertices &&
        plan.new_out_degrees.size() == logical_graph.vertices &&
        plan.seed_words.size() == logical_graph.vertices;
    const bool matches_initial_state =
        algorithm_initial_state.has_value() &&
        plan.old_rank_words == algorithm_initial_state->primary &&
        plan.seed_words == algorithm_initial_state->auxiliary &&
        plan.active_vertices == algorithm_initial_state->active_vertices;
    if (policy.config().kind != GraphAlgorithmKind::kResidualPageRank ||
        !valid_sizes || !matches_initial_state ||
        plan.new_out_degrees != host.out_degrees ||
        std::any_of(plan.touched_sources.begin(), plan.touched_sources.end(),
                    [&logical_graph](std::uint32_t source) {
                      return source >= logical_graph.vertices;
                    })) {
      throw std::invalid_argument("invalid Spine device residual correction plan");
    }
  }
  active_bins_payload_ = host.bins;
  source_refresh_ = host.sources;
  host_coverage_ = host.coverage;
  for (std::size_t family = 0; family < graph_ports_.size(); ++family) {
    graph_ports_[family] = make_port(
        "pagerank-graph" + std::to_string(family),
        static_cast<std::uint32_t>(family), family, SpineAxiPortKind::kGraph);
  }
  sorted_ = make_port("pagerank-sorted-edges", 16, 16,
                      SpineAxiPortKind::kSortedEdges);
  active_bins_ =
      make_port("pagerank-active-bins", 18, 18,
                SpineAxiPortKind::kActiveBins);
  metadata_ =
      make_port("pagerank-metadata", 20, 20, SpineAxiPortKind::kMetadata);
  maintenance_result_ = make_port("pagerank-maintenance-result", 21, 21,
                                  SpineAxiPortKind::kMaintenanceResult);
  vertex_state_ = make_port("pagerank-vertex-state", 117, 17,
                            SpineAxiPortKind::kVertexState);
  active_seed_out_ = make_port("pagerank-active-seed-out", 120, 19,
                               SpineAxiPortKind::kActiveOut);
  active_out_ = make_port("pagerank-active-out", 119, 19,
                          SpineAxiPortKind::kActiveOut);
  active_out_reader_ = make_port("pagerank-active-out-reader", 118, 19,
                                 SpineAxiPortKind::kActiveOut);
  if (owner_scheduler_config.has_value()) {
    if (owner_scheduler_config->max_vertices < logical_graph.vertices) {
      throw std::invalid_argument(
          "PageRank owner domain is smaller than the graph domain");
    }
    owner_state_ = make_port("pagerank-owner-state", 122, 22,
                             SpineAxiPortKind::kActiveBitmap);
    owner_scheduler_ = std::make_unique<SpineOwnerScheduler>(
        "pagerank-owner", clock_id_, *owner_scheduler_config);
  }
  if (vertex_lifecycle_config.has_value()) {
    if (vertex_lifecycle_config->max_vertices != logical_graph.vertices) {
      throw std::invalid_argument(
          "PageRank lifecycle domain must match the graph domain");
    }
    vertex_validity_ = make_port("pagerank-vertex-validity", 123, 22,
                                 SpineAxiPortKind::kActiveBitmap);
    vertex_lifecycle_ = std::make_unique<SpineVertexLifecycle>(
        "pagerank-vertex-lifecycle", clock_id_, *vertex_lifecycle_config,
        *vertex_validity_);
    const auto invalid_edge = std::find_if(
        logical_graph.edges.begin(), logical_graph.edges.end(),
        [this](const SpineEdgeRecord &edge) {
          return !vertex_lifecycle_->valid(edge.src) ||
                 !vertex_lifecycle_->valid(edge.dst);
        });
    if (invalid_edge != logical_graph.edges.end()) {
      throw std::invalid_argument(
          "PageRank graph contains an invalid lifecycle endpoint");
    }
  }

  SpineL0Ports maintenance_ports;
  SpineReaderPorts reader_ports;
  for (std::size_t family = 0; family < graph_ports_.size(); ++family) {
    maintenance_ports.graph[family] = graph_ports_[family].get();
    reader_ports.graph[family] = graph_ports_[family].get();
  }
  maintenance_ports.sorted_edges = sorted_.get();
  maintenance_ports.metadata = metadata_.get();
  maintenance_ports.result = maintenance_result_.get();
  reader_ports.task_scratch = sorted_.get();
  reader_ports.active_bins = active_bins_.get();
  reader_ports.active_out = active_out_reader_.get();
  reader_ports.metadata = metadata_.get();
  reader_ports.result = maintenance_result_.get();

  algorithm_policy_ =
      std::make_shared<const GraphAlgorithmPolicy>(std::move(policy));
  maintenance_ = std::make_unique<SpineL0Maintenance>(
      "pagerank-maintenance", clock_id_, std::move(maintenance_config),
      std::move(workload), maintenance_ports, state_);
  const bool full_domain =
      algorithm_policy_->config().kind == GraphAlgorithmKind::kFullPageRank;
  reader_ = std::make_unique<SpineSplitReader>(
      "pagerank-reader", clock_id_, *maintenance_, reader_ports,
      full_domain ? std::vector<std::uint32_t>{} : host.sources, edge_stream_,
      value_stream_, full_domain ? SpineReaderMode::kFullDomain
                                 : SpineReaderMode::kHostActive,
      algorithm_policy_);
  const bool initial_device_active =
      algorithm_initial_state.has_value() &&
      (algorithm_policy_->config().kind == GraphAlgorithmKind::kResidualPageRank ||
       algorithm_policy_->config().kind == GraphAlgorithmKind::kConnectedComponents);
  if (initial_device_active) {
    std::vector<std::pair<std::uint32_t, std::uint32_t>> records;
    records.reserve(algorithm_initial_state->active_vertices.size());
    for (const std::uint32_t source : algorithm_initial_state->active_vertices) {
      const std::uint32_t value =
          algorithm_policy_->config().kind == GraphAlgorithmKind::kResidualPageRank
              ? algorithm_initial_state->auxiliary.at(source)
              : algorithm_initial_state->primary.at(source);
      records.emplace_back(source, value);
    }
    initial_active_ready_ = device_residual_correction.has_value()
                                ? false
                                : records.empty();
    reader_->configure_initial_active_list_round(records.size(),
                                                 &initial_active_ready_);
    if (!device_residual_correction.has_value() && !records.empty()) {
      initial_active_writer_ = std::make_unique<SpineInitialActiveOutputWriter>(
          "pagerank-initial-active-out", clock_id_, *active_seed_out_,
          *maintenance_, std::move(records), initial_active_counters_,
          initial_active_ready_, initial_active_failed_,
          initial_active_failure_);
    }
  } else if (!full_domain) {
    // The current PageRank/CC policy shell still performs device-side source
    // preparation from rank/residual/degree state.  Unlike refactor31 SSSP,
    // its active-record payload is not yet authoritative for that operation.
    reader_->configure_initial_host_round(host.bins, host.coverage, host.sources);
  }
  compute_ = std::make_unique<SpineSplitPageRankCompute>(
      "pagerank-compute", clock_id_, *algorithm_policy_,
      algorithm_policy_->storage_profile().degree_arrays != 0
          ? std::move(host.out_degrees)
          : std::vector<std::uint32_t>{},
      *vertex_state_, active_out_.get(), edge_stream_, value_stream_,
      pipeline_config,
      compute_memory_request_window,
      SpineSplitPageRankCompute::kDefaultTileVertices,
      std::move(algorithm_initial_state), owner_scheduler_.get());
  if (device_residual_correction.has_value()) {
    const AlgorithmStateLayout &layout = compute_->state_layout();
    if (!layout.auxiliary.has_value() || !layout.degree.has_value()) {
      throw std::logic_error(
          "device residual correction requires auxiliary and degree state");
    }
    vertex_state_->initialize_payload(
        layout.auxiliary->base,
        encode_u32_words(std::vector<std::uint32_t>(logical_graph.vertices, 0)));
    vertex_state_->initialize_payload(
        layout.degree->base,
        encode_u32_words(device_residual_correction->old_out_degrees));
    std::array<FixedAxiPort *, 16> correction_graph_ports{};
    for (std::size_t family = 0; family < graph_ports_.size(); ++family) {
      correction_graph_ports[family] = graph_ports_[family].get();
    }
    initial_active_writer_ = std::make_unique<SpineResidualCorrectionSeeder>(
        "pagerank-device-residual-correction", clock_id_,
        correction_graph_ports, *vertex_state_, *active_seed_out_,
        *maintenance_, state_, maintenance_config_,
        std::move(*device_residual_correction), compute_->primary_read_base(),
        layout.auxiliary->base, layout.degree->base, initial_active_counters_,
        initial_active_ready_, initial_active_failed_, initial_active_failure_);
    compute_->configure_initial_start_gate(&initial_active_ready_);
  }
  if (owner_scheduler_ != nullptr) {
    if (vertex_lifecycle_ != nullptr &&
        std::any_of(source_refresh_.begin(), source_refresh_.end(),
                    [this](std::uint32_t vertex) {
                      return !vertex_lifecycle_->valid(vertex);
                    })) {
      throw std::invalid_argument(
          "PageRank initial frontier contains an invalid vertex");
    }
    owner_frontier_ = std::make_unique<SpineOwnerFrontierController>(
        "pagerank-owner-frontier", clock_id_, *owner_scheduler_,
        source_refresh_, &initial_active_ready_);
    reader_->configure_start_gate(owner_frontier_->ready_gate());
    compute_->configure_initial_start_gate(owner_frontier_->ready_gate());
  }
}

std::unique_ptr<FixedAxiPort> SpinePageRankVerticalSliceSystem::make_port(
    const std::string &name, std::uint32_t initiator_id, std::size_t channel,
    SpineAxiPortKind kind) {
  return std::make_unique<FixedAxiPort>(
      name, clock_id_,
      axi_profile_.port_config(kind, 32, channel, initiator_id), backend_);
}

void SpinePageRankVerticalSliceSystem::register_components() {
  if (registered_) {
    throw std::logic_error("Spine PageRank system already registered");
  }
  registered_ = true;
  scheduler_.add_component(*maintenance_);
  if (initial_active_writer_ != nullptr) {
    scheduler_.add_component(*initial_active_writer_);
  }
  if (owner_scheduler_ != nullptr) {
    scheduler_.add_component(*owner_scheduler_);
    scheduler_.add_component(*owner_frontier_);
  }
  if (vertex_lifecycle_ != nullptr) {
    scheduler_.add_component(*vertex_lifecycle_);
  }
  scheduler_.add_component(*reader_);
  compute_->register_components(scheduler_);
  scheduler_.add_component(edge_stream_);
  scheduler_.add_component(value_stream_);
  for (auto &port : graph_ports_) {
    port->register_components(scheduler_);
  }
  sorted_->register_components(scheduler_);
  active_bins_->register_components(scheduler_);
  metadata_->register_components(scheduler_);
  maintenance_result_->register_components(scheduler_);
  vertex_state_->register_components(scheduler_);
  active_seed_out_->register_components(scheduler_);
  active_out_->register_components(scheduler_);
  active_out_reader_->register_components(scheduler_);
  if (owner_state_ != nullptr) {
    owner_state_->register_components(scheduler_);
  }
  if (vertex_validity_ != nullptr) {
    vertex_validity_->register_components(scheduler_);
  }
}

void SpinePageRankVerticalSliceSystem::restart_iteration() {
  if (!registered_ || !done() || failed() || !idle()) {
    throw std::logic_error(
        "PageRank iteration restart requires a successful system drain");
  }
  edge_stream_.reset_stats();
  value_stream_.reset_stats();
  const std::vector<std::uint32_t> completed_frontier = source_refresh_;
  const bool dense_frontier =
      algorithm_policy_->config().kind == GraphAlgorithmKind::kFullPageRank;
  if (algorithm_policy_->config().kind ==
          GraphAlgorithmKind::kResidualPageRank ||
      algorithm_policy_->config().kind ==
          GraphAlgorithmKind::kConnectedComponents) {
    source_refresh_ = compute_->next_active();
    if (source_refresh_.empty()) {
      throw std::logic_error("converged frontier algorithm cannot restart");
    }
    reader_->reset_active_list_round(source_refresh_.size());
  } else {
    reader_->reset_full_domain_round();
  }
  if (owner_frontier_ != nullptr) {
    if (vertex_lifecycle_ != nullptr &&
        std::any_of(source_refresh_.begin(), source_refresh_.end(),
                    [this](std::uint32_t vertex) {
                      return !vertex_lifecycle_->valid(vertex);
                    })) {
      throw std::logic_error(
          "PageRank next frontier contains an invalid vertex");
    }
    owner_frontier_->restart(completed_frontier, source_refresh_,
                             dense_frontier);
  }
  compute_->reset_iteration();
}

SpineFrontierRunResult
SpinePageRankVerticalSliceSystem::run_frontier_to_convergence(
    std::size_t max_rounds, std::uint64_t max_events_per_round) {
  if (!registered_ || convergence_run_started_ || max_rounds == 0 ||
      max_events_per_round == 0 || owner_scheduler_ == nullptr ||
      owner_frontier_ == nullptr) {
    throw std::logic_error(
        "invalid Spine frontier convergence-run state or limits");
  }
  convergence_run_started_ = true;
  SpineFrontierRunResult result;
  result.algorithm = algorithm_policy_->config().kind;
  result.start_cycle = scheduler_.clock(clock_id_).completed_cycles;
  for (std::size_t round = 0; round < max_rounds; ++round) {
    const std::vector<std::uint32_t> active_in = source_refresh_;
    const std::uint64_t start_cycle =
        scheduler_.clock(clock_id_).completed_cycles;
    scheduler_.run_until(
        [this] { return failed() || (done() && idle()); },
        max_events_per_round);
    const std::uint64_t end_cycle =
        scheduler_.clock(clock_id_).completed_cycles;
    const std::vector<std::uint32_t> active_out = compute_->next_active();
    result.rounds.push_back(SpineFrontierRoundEvidence{
        .round = round,
        .active_in = active_in,
        .active_out = active_out,
        .reader = reader_->counters(),
        .compute = compute_->counters(),
        .start_cycle = start_cycle,
        .end_cycle = end_cycle,
    });
    if (failed()) {
      result.failed = true;
      break;
    }
    const bool dense =
        result.algorithm == GraphAlgorithmKind::kFullPageRank;
    const bool converged = dense
                               ? compute_->iteration_error() <=
                                     algorithm_policy_->config().epsilon
                               : active_out.empty();
    if (converged) {
      owner_frontier_->restart(active_in, {}, false);
      scheduler_.run_until(
          [this] {
            return owner_frontier_->failed() ||
                   (owner_frontier_->ready() && owner_scheduler_->quiescent() &&
                    owner_scheduler_->ledger_closed() && idle());
          },
          max_events_per_round);
      result.converged = !failed() && owner_scheduler_->quiescent() &&
                         owner_scheduler_->ledger_closed();
      result.failed = !result.converged;
      break;
    }
    if (round + 1 >= max_rounds) {
      result.failed = true;
      break;
    }
    restart_iteration();
  }
  result.end_cycle = scheduler_.clock(clock_id_).completed_cycles;
  result.owner_scheduler = owner_scheduler_->stats();
  result.owner_frontier = owner_frontier_->stats();
  result.owner_ledger_closed = owner_scheduler_->ledger_closed();
  result.owner_quiescent = owner_scheduler_->quiescent();
  return result;
}

bool SpinePageRankVerticalSliceSystem::try_activate_vertex(
    std::uint32_t vertex) {
  if (!registered_ || vertex_lifecycle_ == nullptr || !done() || !idle() ||
      failed() ||
      (owner_scheduler_ != nullptr && !owner_scheduler_->quiescent())) {
    throw std::logic_error(
        "PageRank vertex activation requires a drained graph transaction");
  }
  return vertex_lifecycle_->try_activate(vertex);
}

bool SpinePageRankVerticalSliceSystem::try_deactivate_vertex(
    std::uint32_t vertex, bool incident_edges_retired_or_masked) {
  if (!registered_ || vertex_lifecycle_ == nullptr || !done() || !idle() ||
      failed() ||
      (owner_scheduler_ != nullptr && !owner_scheduler_->quiescent())) {
    throw std::logic_error(
        "PageRank vertex deactivation requires a drained graph transaction");
  }
  return vertex_lifecycle_->try_deactivate(
      vertex, incident_edges_retired_or_masked);
}

SpineVertexLifecycleResult
SpinePageRankVerticalSliceSystem::run_vertex_lifecycle_to_completion(
    std::uint64_t max_events) {
  if (!registered_ || vertex_lifecycle_ == nullptr ||
      !vertex_lifecycle_->busy() || max_events == 0) {
    throw std::logic_error("invalid PageRank vertex lifecycle run state");
  }
  scheduler_.run_until(
      [this] {
        return !vertex_lifecycle_->busy() && vertex_validity_->idle();
      },
      max_events);
  if (vertex_lifecycle_->failed() ||
      !vertex_lifecycle_->last_result().has_value() ||
      !vertex_lifecycle_->request_ledger_closed()) {
    throw std::logic_error(
        vertex_lifecycle_->failed()
            ? vertex_lifecycle_->failure()
            : "PageRank vertex lifecycle completed without closed evidence");
  }
  return *vertex_lifecycle_->last_result();
}

bool SpinePageRankVerticalSliceSystem::maintenance_done() const noexcept {
  return maintenance_->done();
}

bool SpinePageRankVerticalSliceSystem::done() const noexcept {
  return maintenance_->done() && reader_->done() && compute_->done() &&
         (owner_frontier_ == nullptr || owner_frontier_->ready()) &&
         (vertex_lifecycle_ == nullptr || !vertex_lifecycle_->busy());
}

bool SpinePageRankVerticalSliceSystem::failed() const noexcept {
  return maintenance_->failed() || initial_active_failed_ || reader_->failed() ||
         compute_->failed() ||
         (owner_frontier_ != nullptr && owner_frontier_->failed()) ||
         (vertex_lifecycle_ != nullptr && vertex_lifecycle_->failed());
}

std::string SpinePageRankVerticalSliceSystem::failure() const {
  if (maintenance_->failed()) {
    return "maintenance: " + maintenance_->failure();
  }
  if (initial_active_failed_) {
    return "initial active output: " + initial_active_failure_;
  }
  if (reader_->failed()) {
    return "reader: " + reader_->failure();
  }
  if (compute_->failed()) {
    return "compute: protocol or memory failure";
  }
  if (owner_frontier_ != nullptr && owner_frontier_->failed()) {
    return "owner frontier: " + owner_frontier_->failure();
  }
  if (vertex_lifecycle_ != nullptr && vertex_lifecycle_->failed()) {
    return "vertex lifecycle: " + vertex_lifecycle_->failure();
  }
  return {};
}

bool SpinePageRankVerticalSliceSystem::idle() const noexcept {
  for (const auto &port : graph_ports_) {
    if (!port->idle()) {
      return false;
    }
  }
  return sorted_->idle() && active_bins_->idle() && active_seed_out_->idle() &&
         active_out_->idle() && active_out_reader_->idle() && metadata_->idle() &&
         maintenance_result_->idle() &&
         vertex_state_->idle() &&
         (owner_state_ == nullptr || owner_state_->idle()) &&
         (vertex_validity_ == nullptr || vertex_validity_->idle()) &&
         edge_stream_.empty() && value_stream_.empty() &&
         (initial_active_writer_ == nullptr || initial_active_ready_);
}

const SpineL0Counters &
SpinePageRankVerticalSliceSystem::maintenance_counters() const noexcept {
  return maintenance_->counters();
}

const SpineReaderCounters &
SpinePageRankVerticalSliceSystem::reader_counters() const noexcept {
  return reader_->counters();
}

const SpinePageRankCounters &
SpinePageRankVerticalSliceSystem::compute_counters() const noexcept {
  return compute_->counters();
}

const SpineInitialActiveOutputCounters &
SpinePageRankVerticalSliceSystem::initial_active_counters() const noexcept {
  return initial_active_counters_;
}

const SpineSplitPageRankCompute &
SpinePageRankVerticalSliceSystem::compute() const noexcept {
  return *compute_;
}

const SpineL0State &
SpinePageRankVerticalSliceSystem::level_state() const noexcept {
  return state_;
}

const FifoStats &
SpinePageRankVerticalSliceSystem::edge_stream_stats() const noexcept {
  return edge_stream_.stats();
}

const FifoStats &
SpinePageRankVerticalSliceSystem::value_stream_stats() const noexcept {
  return value_stream_.stats();
}

} // namespace spine::sim
