#include "spine_sim/grasu_regraph.hpp"

#include "spine_sim/grasu_native.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <deque>
#include <limits>
#include <optional>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <utility>

#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"

namespace spine::sim {

namespace {

constexpr std::array<std::pair<std::size_t, std::size_t>, 4>
    kU55cLaneChannelRanges{{{0, 6}, {6, 12}, {12, 18}, {18, 23}}};

std::size_t align_runtime_bytes(std::size_t value) {
  constexpr std::size_t alignment = kGraSuReGraphRuntimeAlignmentBytes;
  if (value > std::numeric_limits<std::size_t>::max() - (alignment - 1)) {
    throw std::overflow_error("GraSU-ReGraph runtime region size overflow");
  }
  return (value + alignment - 1) & ~(alignment - 1);
}

} // namespace

GraSuReGraphRuntimePlan build_grasu_regraph_runtime_plan(
    const GraSuPartitionedPmaLayout &layout,
    const std::vector<std::size_t> &physical_updates_per_shard,
    std::size_t max_cache_segments, std::size_t channels,
    std::size_t channel_capacity_bytes) {
  if (layout.vertices == 0 || layout.partitions.empty() ||
      physical_updates_per_shard.size() != layout.partitions.size() ||
      max_cache_segments == 0 || channels != kGraSuReGraphU55cGraphChannels ||
      channel_capacity_bytes == 0) {
    throw std::invalid_argument("invalid GraSU-ReGraph runtime geometry");
  }

  GraSuReGraphRuntimePlan result;
  result.max_cache_segments = max_cache_segments;
  result.channel_capacity_bytes = channel_capacity_bytes;
  result.channel_load_bytes.assign(channels, 0);
  result.shards.reserve(layout.partitions.size());

  const auto add_region = [&](std::size_t shard, std::string name,
                              std::size_t logical_bytes) {
    std::size_t channel_first = 0;
    std::size_t channel_last = channels;
    if (name.rfind("update", 0) == 0 || name.rfind("pma", 0) == 0) {
      const char lane_character = name.back();
      if (lane_character < '0' || lane_character > '3') {
        throw std::logic_error("GraSU-ReGraph lane role is malformed");
      }
      const std::size_t lane = static_cast<std::size_t>(lane_character - '0');
      channel_first = kU55cLaneChannelRanges[lane].first;
      channel_last = kU55cLaneChannelRanges[lane].second;
    }
    result.regions.push_back({
        .shard = shard,
        .name = std::move(name),
        .logical_bytes = logical_bytes,
        .allocated_bytes =
            align_runtime_bytes(std::max<std::size_t>(logical_bytes, 1)),
        .channel_first = channel_first,
        .channel_last = channel_last,
    });
  };

  for (std::size_t shard = 0; shard < layout.partitions.size(); ++shard) {
    const GraSuPmaLayout &partition = layout.partitions[shard];
    const std::size_t segments = partition.segments.size();
    if (segments == 0 || partition.row_slot_bounds.size() != layout.vertices ||
        partition.binary_heads.size() != segments) {
      throw std::invalid_argument("invalid GraSU-ReGraph PMA shard buffers");
    }
    const std::size_t even_segments = (segments + 1) / 2;
    const std::size_t odd_segments = segments / 2;
    GraSuReGraphShardRuntimePlan shard_plan;
    shard_plan.destination_base = partition.destination_base;
    shard_plan.destination_vertices = partition.destination_vertices;
    shard_plan.pma_slot_count = segments * kGraSuSegmentSlots;
    shard_plan.pma_words = {
        max_cache_segments * kGraSuSegmentSlots,
        std::max<std::size_t>(
            even_segments > max_cache_segments ? even_segments : 1, 1) *
            kGraSuSegmentSlots,
        max_cache_segments * kGraSuSegmentSlots,
        std::max<std::size_t>(
            odd_segments > max_cache_segments ? odd_segments : 1, 1) *
            kGraSuSegmentSlots,
    };
    for (std::size_t lane = 0; lane < 4; ++lane) {
      shard_plan.update_counts[lane] =
          physical_updates_per_shard[shard] / 4 +
          (lane < physical_updates_per_shard[shard] % 4 ? 1 : 0);
      shard_plan.update_alloc_counts[lane] =
          std::max<std::size_t>(shard_plan.update_counts[lane], 1);
      add_region(shard, "update" + std::to_string(lane),
                 shard_plan.update_alloc_counts[lane] * sizeof(std::uint64_t));
      add_region(shard, "pma" + std::to_string(lane),
                 shard_plan.pma_words[lane] * sizeof(std::uint32_t));
    }
    // The routed HLS ABI stores a sentinel row at index |V|.
    shard_plan.row_words = layout.vertices + 1;
    shard_plan.binary_words = std::max<std::size_t>(segments, 1);
    add_region(shard, "row", shard_plan.row_words * sizeof(std::uint64_t));
    add_region(shard, "binary",
               shard_plan.binary_words * sizeof(std::uint64_t));
    result.shards.push_back(shard_plan);
  }

  std::vector<std::size_t> order(result.regions.size());
  for (std::size_t index = 0; index < order.size(); ++index) {
    order[index] = index;
  }
  std::sort(order.begin(), order.end(),
            [&](std::size_t left, std::size_t right) {
              const auto &a = result.regions[left];
              const auto &b = result.regions[right];
              if (a.allocated_bytes != b.allocated_bytes) {
                return a.allocated_bytes > b.allocated_bytes;
              }
              return std::pair(a.shard, a.name) < std::pair(b.shard, b.name);
            });

  for (const std::size_t region_index : order) {
    GraSuReGraphBufferRegion &region = result.regions[region_index];
    std::size_t selected = channels;
    for (std::size_t channel = region.channel_first;
         channel < region.channel_last; ++channel) {
      if (region.allocated_bytes > channel_capacity_bytes ||
          result.channel_load_bytes[channel] >
              channel_capacity_bytes - region.allocated_bytes) {
        continue;
      }
      if (selected == channels || result.channel_load_bytes[channel] <
                                      result.channel_load_bytes[selected]) {
        selected = channel;
      }
    }
    if (selected == channels) {
      throw std::overflow_error(
          "GraSU-ReGraph runtime buffers exceed HBM pseudo-channel capacity");
    }
    region.channel = selected;
    region.channel_offset_bytes = result.channel_load_bytes[selected];
    result.channel_load_bytes[selected] += region.allocated_bytes;
    result.total_allocated_bytes += region.allocated_bytes;
  }
  return result;
}

const GraSuReGraphBufferRegion &
find_grasu_regraph_runtime_region(const GraSuReGraphRuntimePlan &plan,
                                  std::size_t shard, const std::string &name) {
  const auto found =
      std::find_if(plan.regions.begin(), plan.regions.end(),
                   [&](const GraSuReGraphBufferRegion &region) {
                     return region.shard == shard && region.name == name;
                   });
  if (found == plan.regions.end()) {
    throw std::out_of_range("GraSU-ReGraph runtime region is missing");
  }
  return *found;
}

namespace {

constexpr std::uint32_t kReGraphActive = 0x8000'0000U;
constexpr std::uint32_t kReGraphValueMask = 0x7fff'ffffU;
constexpr std::uint32_t kReGraphInfinity = 0x7fff'fffeU;
constexpr std::size_t kStateWordsPerBurst = 16;

std::uint32_t decode_u32(const std::vector<std::uint8_t> &bytes,
                         std::size_t offset = 0) {
  if (offset + 4 > bytes.size()) {
    throw std::invalid_argument("ReGraph 32-bit payload has invalid size");
  }
  std::uint32_t value = 0;
  for (std::size_t index = 0; index < 4; ++index) {
    value |= static_cast<std::uint32_t>(bytes[offset + index]) << (index * 8);
  }
  return value;
}

std::uint64_t decode_u64(const std::vector<std::uint8_t> &bytes) {
  if (bytes.size() != 8) {
    throw std::invalid_argument("ReGraph 64-bit payload has invalid size");
  }
  std::uint64_t value = 0;
  for (std::size_t index = 0; index < 8; ++index) {
    value |= static_cast<std::uint64_t>(bytes[index]) << (index * 8);
  }
  return value;
}

std::vector<std::uint8_t>
encode_words(const std::array<std::uint32_t, kStateWordsPerBurst> &words) {
  std::vector<std::uint8_t> bytes(kStateWordsPerBurst * 4);
  for (std::size_t word = 0; word < words.size(); ++word) {
    for (std::size_t byte = 0; byte < 4; ++byte) {
      bytes[word * 4 + byte] =
          static_cast<std::uint8_t>(words[word] >> (byte * 8));
    }
  }
  return bytes;
}

std::uint32_t policy_distance(std::uint32_t encoded) {
  const std::uint32_t value = encoded & kReGraphValueMask;
  return value == kReGraphInfinity ? GraphAlgorithmPolicy::kSsspInfinity
                                   : value;
}

std::uint32_t encode_distance(std::uint32_t distance, bool active) {
  const std::uint32_t value = distance == GraphAlgorithmPolicy::kSsspInfinity
                                  ? kReGraphInfinity
                                  : std::min(distance, kReGraphInfinity - 1);
  return value | (active ? kReGraphActive : 0U);
}

std::uint32_t decode_policy_value(const GraphAlgorithmPolicy &policy,
                                  std::uint32_t encoded) {
  if (policy.config().kind == GraphAlgorithmKind::kWeightedSssp) {
    return policy_distance(encoded);
  }
  if (policy.config().kind == GraphAlgorithmKind::kFullPageRank ||
      policy.config().kind == GraphAlgorithmKind::kConnectedComponents) {
    return encoded & kReGraphValueMask;
  }
  return encoded;
}

std::uint32_t encode_policy_value(const GraphAlgorithmPolicy &policy,
                                  std::uint32_t value, bool active) {
  if (policy.config().kind == GraphAlgorithmKind::kWeightedSssp) {
    return encode_distance(value, active);
  }
  if (policy.config().kind == GraphAlgorithmKind::kConnectedComponents) {
    return (value & kReGraphValueMask) | (active ? kReGraphActive : 0U);
  }
  if (policy.config().kind == GraphAlgorithmKind::kResidualPageRank) {
    return value;
  }
  (void)active;
  return value;
}

bool uses_auxiliary_state(const GraphAlgorithmPolicy &policy) {
  return policy.config().kind == GraphAlgorithmKind::kResidualPageRank;
}

std::size_t state_bytes_per_vertex(const GraphAlgorithmPolicy &policy) {
  return uses_auxiliary_state(policy) ? 8 : 4;
}

std::size_t state_vertices_per_beat(const GraphAlgorithmPolicy &policy) {
  return 64 / state_bytes_per_vertex(policy);
}

std::vector<std::uint8_t> encode_state_words(
    const GraphAlgorithmPolicy &policy,
    const std::array<std::uint32_t, kStateWordsPerBurst> &primary,
    const std::array<std::uint32_t, kStateWordsPerBurst> &auxiliary) {
  if (!uses_auxiliary_state(policy)) {
    return encode_words(primary);
  }
  std::vector<std::uint8_t> bytes(kStateWordsPerBurst * 8);
  for (std::size_t word = 0; word < primary.size(); ++word) {
    for (std::size_t byte = 0; byte < 4; ++byte) {
      bytes[word * 8 + byte] =
          static_cast<std::uint8_t>(primary[word] >> (byte * 8));
      bytes[word * 8 + 4 + byte] =
          static_cast<std::uint8_t>(auxiliary[word] >> (byte * 8));
    }
  }
  return bytes;
}

FixedAxiPortConfig port_config(const GraSuReGraphConfig &config,
                               std::size_t channel, std::uint32_t initiator_id,
                               std::uint32_t width) {
  return FixedAxiPortConfig{
      .memory_channels = config.memory_channels,
      .channel = channel,
      .initiator_id = initiator_id,
      .data_width_bytes = width,
      .max_burst_beats = 16,
      .request_fifo_depth = config.max_pending_requests,
      .response_fifo_depth = config.max_pending_requests,
      .read_beat_fifo_depth = config.max_pending_requests,
      .read_reorder_capacity = config.max_outstanding_bursts,
      .stream_read_beats = false,
      .max_pending_requests = config.max_pending_requests,
      .max_outstanding_bursts = config.max_outstanding_bursts,
      .address_accepts_per_cycle = 1,
      .beat_issues_per_cycle = 1,
      .response_beats_per_cycle = config.response_beats_per_cycle,
  };
}

struct PmaEdgeBatch {
  std::uint32_t source{};
  std::uint32_t source_payload{};
  bool source_active{};
  bool per_lane_source{};
  std::size_t lanes{};
  std::array<std::uint32_t, 8> source_payloads{};
  std::array<bool, 8> source_actives{};
  std::array<std::uint32_t, 8> destinations{};
  std::array<std::uint16_t, 8> weights{};
  std::array<bool, 8> valid{};
};

class ReGraphDoneSignal {
public:
  using Notifier = void (*)(void *) noexcept;

  void bind(void *owner, Notifier notifier) {
    if (notifier == nullptr) {
      throw std::invalid_argument("ReGraph done notifier is null");
    }
    if (notifier_ != nullptr && (owner_ != owner || notifier_ != notifier)) {
      throw std::logic_error("ReGraph done notifier is already bound");
    }
    owner_ = owner;
    notifier_ = notifier;
  }

  void unbind(void *owner) noexcept {
    if (owner_ == owner) {
      owner_ = nullptr;
      notifier_ = nullptr;
    }
  }

  void notify() const noexcept {
    if (notifier_ != nullptr) {
      notifier_(owner_);
    }
  }

private:
  void *owner_{};
  Notifier notifier_{};
};

class ReGraphReaderContext {
public:
  using DoneNotifier = void (*)(void *) noexcept;

  virtual ~ReGraphReaderContext() = default;
  [[nodiscard]] virtual bool done() const noexcept = 0;
  [[nodiscard]] virtual AlgorithmIterationContext
  iteration_context() const noexcept = 0;

  void bind_done_notifier(void *owner, DoneNotifier notifier) {
    if (notifier == nullptr) {
      throw std::invalid_argument("ReGraph reader done notifier is null");
    }
    const auto duplicate =
        std::find_if(done_notifiers_.begin(), done_notifiers_.end(),
                     [owner](const DoneNotifierBinding &binding) {
                       return binding.owner == owner;
                     });
    if (duplicate != done_notifiers_.end()) {
      if (duplicate->notifier != notifier) {
        throw std::logic_error(
            "ReGraph reader done notifier owner is already bound");
      }
      return;
    }
    done_notifiers_.push_back({.owner = owner, .notifier = notifier});
    if (done()) {
      notifier(owner);
    }
  }

  void unbind_done_notifier(void *owner) noexcept {
    std::erase_if(done_notifiers_, [owner](const DoneNotifierBinding &binding) {
      return binding.owner == owner;
    });
  }

protected:
  void notify_done() noexcept {
    for (const DoneNotifierBinding &binding : done_notifiers_) {
      binding.notifier(binding.owner);
    }
  }

private:
  struct DoneNotifierBinding {
    void *owner{};
    DoneNotifier notifier{};
  };

  std::vector<DoneNotifierBinding> done_notifiers_;
};

struct ReGraphSourceCacheRequest {
  std::size_t source_round{};
  bool end{};
};

struct ReGraphSourceCacheResponse {
  std::size_t source_round{};
  std::size_t line{};
  std::array<std::uint32_t, kStateWordsPerBurst> words{};
  std::array<std::uint32_t, kStateWordsPerBurst> auxiliary_words{};
  std::size_t vertices{};
  bool end{};
};

struct ReGraphGatherRow {
  std::size_t row{};
  std::array<std::optional<std::uint32_t>, 2> candidates{};
};

struct ReGraphMergedBurst {
  std::size_t offset{};
  std::array<std::optional<std::uint32_t>, kStateWordsPerBurst> candidates{};
};

struct ReGraphAppliedBurst {
  std::size_t offset{};
  std::vector<std::uint8_t> data;
  std::vector<std::uint8_t> source_data;
};

struct ReGraphPartitionPlan {
  std::size_t destination_base{};
  std::size_t destination_vertices{};
  std::uint64_t row_base{};
  std::size_t row_channel{};
  std::array<std::uint64_t, 4> pma_base{};
  std::array<std::size_t, 4> pma_channel{};
};

class ReGraphIterationContext final : public ReGraphReaderContext {
public:
  explicit ReGraphIterationContext(GraphAlgorithmPolicy policy)
      : policy_(std::move(policy)) {}

  [[nodiscard]] bool done() const noexcept override { return true; }
  [[nodiscard]] AlgorithmIterationContext
  iteration_context() const noexcept override {
    return context_;
  }

  void set_dangling(float dangling) noexcept {
    context_.base =
        policy_.config().kind == GraphAlgorithmKind::kFullPageRank
            ? policy_.initial_base_word()
            : GraphAlgorithmPolicy::float_to_word(0.0F);
    context_.dangling_share = GraphAlgorithmPolicy::float_to_word(
        policy_.config().damping * dangling /
        static_cast<float>(policy_.config().vertices));
  }

private:
  GraphAlgorithmPolicy policy_;
  AlgorithmIterationContext context_{};
};

class ReGraphPageRankSourcePrepare final : public Component {
public:
  ReGraphPageRankSourcePrepare(
      std::string name, ClockId clock_id, std::size_t vertices,
      GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
      FixedAxiPort &state_read, FixedAxiPort &degree_read,
      FixedAxiPort &primary_write, FixedAxiPort &mirror_write,
      ReGraphIterationContext &iteration_context)
      : Component(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), state_read_(state_read),
        degree_read_(degree_read), writes_{&primary_write, &mirror_write},
        iteration_context_(iteration_context) {}

  void start() {
    if (running_ || done_) {
      throw std::logic_error("PageRank source prepare started twice");
    }
    running_ = true;
    set_latched_evaluate_ready(true);
  }

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] std::uint64_t cycles() const noexcept { return cycles_; }
  [[nodiscard]] std::uint64_t state_reads() const noexcept {
    return state_reads_;
  }
  [[nodiscard]] std::uint64_t degree_reads() const noexcept {
    return degree_reads_;
  }
  void bind_done_notifier(void *owner, ReGraphDoneSignal::Notifier notifier) {
    done_signal_.bind(owner, notifier);
  }
  void unbind_done_notifier(void *owner) noexcept { done_signal_.unbind(owner); }
  [[nodiscard]] std::uint64_t writes() const noexcept { return writes_issued_; }

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    return running_;
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return running_;
  }

  void evaluate(const CycleContext &context) override {
    staged_read_issue_.reset();
    staged_write_issue_.reset();
    staged_state_response_.reset();
    staged_degree_response_.reset();
    for (auto &response : staged_write_responses_) {
      response.reset();
    }
    if (!running_) {
      set_latched_commit_ready(false);
      return;
    }
    if (state_read_.responses().front() != nullptr) {
      AxiResponse response;
      if (state_read_.responses().try_pop(response)) {
        staged_state_response_ = std::move(response);
      }
    }
    if (degree_read_.responses().front() != nullptr) {
      AxiResponse response;
      if (degree_read_.responses().try_pop(response)) {
        staged_degree_response_ = std::move(response);
      }
    }
    for (std::size_t port = 0; port < writes_.size(); ++port) {
      if (writes_[port]->responses().front() != nullptr) {
        AxiResponse response;
        if (writes_[port]->responses().try_pop(response)) {
          staged_write_responses_[port] = std::move(response);
        }
      }
    }
    const auto ready = std::find_if(
        ready_writes_.begin(), ready_writes_.end(),
        [&](const ReadyWrite &write) {
          return write.due_cycle <= context.domain_cycle;
        });
    if (ready != ready_writes_.end() && write_window_available() &&
        write_fifos_available()) {
      const std::size_t index =
          static_cast<std::size_t>(ready - ready_writes_.begin());
      const ReadyWrite &write = ready_writes_[index];
      for (FixedAxiPort *port : writes_) {
        if (!port->requests().try_push(AxiRequest{
                .transaction_id = transaction_id(write.burst),
                .operation = MemoryOperation::kWrite,
                .address = config_.source_state_base + write.burst * 64,
                .bytes = 64,
                .stream_read_beats = false,
                .write_data = write.data,
            })) {
          throw std::logic_error(
              "PageRank source prepare write pair was not atomic");
        }
      }
      staged_write_issue_ = index;
    }
    if (next_read_burst_ < total_bursts() &&
        reads_inflight_.size() < config_.apply_request_window &&
        !state_read_.requests().full() && !degree_read_.requests().full()) {
      const std::size_t burst = next_read_burst_;
      if (!state_read_.requests().try_push(AxiRequest{
              .transaction_id = transaction_id(burst),
              .operation = MemoryOperation::kRead,
              .address = config_.vertex_state_base +
                         burst * kStateWordsPerBurst *
                             state_bytes_per_vertex(policy_),
              .bytes = static_cast<std::uint32_t>(
                  kStateWordsPerBurst * state_bytes_per_vertex(policy_)),
              .stream_read_beats = false,
              .write_data = {},
          }) ||
          !degree_read_.requests().try_push(AxiRequest{
              .transaction_id = transaction_id(burst),
              .operation = MemoryOperation::kRead,
              .address = config_.degree_base + burst * 64,
              .bytes = 64,
              .stream_read_beats = false,
              .write_data = {},
          })) {
        throw std::logic_error(
            "PageRank source prepare read pair was not atomic");
      }
      staged_read_issue_ = burst;
    }
    set_latched_commit_ready(commit_ready());
  }

  void commit(const CycleContext &context) override {
    if (!running_) {
      return;
    }
    ++cycles_;
    if (staged_state_response_.has_value()) {
      consume_read_response(*staged_state_response_, false,
                            context.domain_cycle);
    }
    if (staged_degree_response_.has_value()) {
      consume_read_response(*staged_degree_response_, true,
                            context.domain_cycle);
    }
    for (std::size_t port = 0; port < staged_write_responses_.size(); ++port) {
      if (staged_write_responses_[port].has_value()) {
        consume_write_response(*staged_write_responses_[port], port);
      }
    }
    if (staged_read_issue_.has_value()) {
      const std::size_t burst = *staged_read_issue_;
      if (!reads_inflight_
               .emplace(transaction_id(burst),
                        PendingRead{.burst = burst,
                                    .state_data = std::nullopt,
                                    .degree_data = std::nullopt})
               .second) {
        throw std::logic_error("duplicate PageRank source prepare read");
      }
      ++next_read_burst_;
      ++state_reads_;
      ++degree_reads_;
    }
    if (staged_write_issue_.has_value()) {
      ReadyWrite write = std::move(ready_writes_[*staged_write_issue_]);
      ready_writes_.erase(ready_writes_.begin() + *staged_write_issue_);
      const std::uint64_t id = transaction_id(write.burst);
      for (auto &inflight : writes_inflight_) {
        if (!inflight.emplace(id, write.burst).second) {
          throw std::logic_error("duplicate PageRank source prepare write");
        }
      }
      writes_issued_ += 2;
    }
    if (completed_writes_ == total_bursts() * 2 &&
        reduction_cycles_remaining_ == 0) {
      reduction_cycles_remaining_ = kStateWordsPerBurst * 8;
    } else if (reduction_cycles_remaining_ != 0) {
      --reduction_cycles_remaining_;
      if (reduction_cycles_remaining_ == 0) {
        iteration_context_.set_dangling(dangling_);
        running_ = false;
        done_ = true;
        done_signal_.notify();
      }
    }
    set_latched_commit_ready(false);
    set_latched_evaluate_ready(running_);
  }

private:
  struct PendingRead {
    std::size_t burst{};
    std::optional<std::vector<std::uint8_t>> state_data;
    std::optional<std::vector<std::uint8_t>> degree_data;
  };
  struct ReadyWrite {
    std::size_t burst{};
    std::uint64_t due_cycle{};
    std::vector<std::uint8_t> data;
  };

  [[nodiscard]] std::size_t total_bursts() const noexcept {
    return (vertices_ + kStateWordsPerBurst - 1) / kStateWordsPerBurst;
  }
  [[nodiscard]] std::uint64_t transaction_id(std::size_t burst) const {
    return 0x7400'0000'0000'0000ULL | burst;
  }
  [[nodiscard]] bool write_window_available() const noexcept {
    return std::all_of(writes_inflight_.begin(), writes_inflight_.end(),
                       [&](const auto &inflight) {
                         return inflight.size() < config_.apply_request_window;
                       });
  }
  [[nodiscard]] bool write_fifos_available() const noexcept {
    return std::all_of(writes_.begin(), writes_.end(),
                       [](const auto *port) {
                         return !port->requests().full();
                       });
  }

  void consume_read_response(const AxiResponse &response, bool degree,
                             std::uint64_t cycle) {
    const auto found = reads_inflight_.find(response.transaction_id);
    const std::size_t expected =
        degree ? 64 : kStateWordsPerBurst * state_bytes_per_vertex(policy_);
    if (!response.success || found == reads_inflight_.end() ||
        response.read_data.size() != expected) {
      throw std::runtime_error("malformed PageRank source prepare response");
    }
    if (degree) {
      found->second.degree_data = response.read_data;
    } else {
      found->second.state_data = response.read_data;
    }
    if (!found->second.state_data.has_value() ||
        !found->second.degree_data.has_value()) {
      return;
    }
    PendingRead pending = std::move(found->second);
    reads_inflight_.erase(found);
    std::array<std::uint32_t, kStateWordsPerBurst> payload{};
    for (std::size_t lane = 0; lane < payload.size(); ++lane) {
      const std::size_t vertex =
          pending.burst * kStateWordsPerBurst + lane;
      if (vertex >= vertices_) {
        continue;
      }
      const std::size_t state_offset =
          lane * state_bytes_per_vertex(policy_);
      const std::uint32_t value_word =
          policy_.config().kind == GraphAlgorithmKind::kFullPageRank
              ? decode_u32(*pending.state_data, state_offset)
              : decode_u32(*pending.state_data, state_offset + 4);
      const float value = GraphAlgorithmPolicy::word_to_float(value_word);
      const std::uint32_t out_degree =
          decode_u32(*pending.degree_data, lane * 4);
      const bool active =
          policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
          std::fabs(value) > GraphAlgorithmPolicy::word_to_float(
                                 policy_.activation_threshold_word());
      payload[lane] = GraphAlgorithmPolicy::float_to_word(
          active && out_degree != 0
              ? policy_.config().damping * value /
                    static_cast<float>(out_degree)
              : 0.0F);
      if (active) {
        ++active_vertices_;
        if (out_degree == 0) {
          dangling_ += value;
        }
      }
    }
    ready_writes_.push_back(ReadyWrite{
        .burst = pending.burst,
        .due_cycle = cycle + config_.pagerank_source_map_latency,
        .data = encode_words(payload),
    });
  }

  void consume_write_response(const AxiResponse &response, std::size_t port) {
    auto &inflight = writes_inflight_.at(port);
    const auto found = inflight.find(response.transaction_id);
    if (!response.success || found == inflight.end() ||
        !response.read_data.empty()) {
      throw std::runtime_error(
          "malformed PageRank source prepare write response");
    }
    inflight.erase(found);
    ++completed_writes_;
  }

  std::size_t vertices_{};
  GraphAlgorithmPolicy policy_;
  GraSuReGraphConfig config_;
  FixedAxiPort &state_read_;
  FixedAxiPort &degree_read_;
  std::array<FixedAxiPort *, 2> writes_;
  ReGraphIterationContext &iteration_context_;
  std::unordered_map<std::uint64_t, PendingRead> reads_inflight_;
  std::array<std::unordered_map<std::uint64_t, std::size_t>, 2>
      writes_inflight_;
  std::deque<ReadyWrite> ready_writes_;
  std::optional<std::size_t> staged_read_issue_;
  std::optional<std::size_t> staged_write_issue_;
  std::optional<AxiResponse> staged_state_response_;
  std::optional<AxiResponse> staged_degree_response_;
  std::array<std::optional<AxiResponse>, 2> staged_write_responses_;
  std::size_t next_read_burst_{};
  std::size_t completed_writes_{};
  std::size_t reduction_cycles_remaining_{};
  float dangling_{};
  std::size_t active_vertices_{};
  bool running_{};
  bool done_{};
  std::uint64_t cycles_{};
  std::uint64_t state_reads_{};
  std::uint64_t degree_reads_{};
  std::uint64_t writes_issued_{};
  ReGraphDoneSignal done_signal_;
};

GraSuPartitionedPmaLayout one_partition_layout(GraSuPmaLayout layout,
                                               std::size_t partition_vertices) {
  GraSuPartitionedPmaLayout result;
  result.vertices = layout.vertices;
  result.partition_vertices = partition_vertices;
  result.partitions.push_back(std::move(layout));
  return result;
}

class ReGraphSourceHbmReader final : public Component {
public:
  ReGraphSourceHbmReader(std::string name, ClockId clock_id,
                         const GraSuReGraphConfig &config,
                         GraphAlgorithmPolicy policy,
                         Fifo<ReGraphSourceCacheRequest> &input,
                         Fifo<ReGraphSourceCacheResponse> &output,
                         FixedAxiPort &port)
      : Component(std::move(name), clock_id), config_(config), input_(input),
        output_(output), port_(port), policy_(std::move(policy)) {}

  void start_partition(std::uint64_t round, std::size_t partition) {
    if (round == 0 || (phase_ != Phase::kIdle && phase_ != Phase::kDone)) {
      throw std::logic_error("ReGraph source HBM reader started while busy");
    }
    algorithm_round_ = round;
    partition_ = partition;
    source_state_base_ =
        config_.source_state_base +
        ((round - 1) & 1U) * config_.source_state_buffer_stride;
    active_source_round_ = 0;
    lines_emitted_this_request_ = 0;
    phase_ = Phase::kIdle;
    set_latched_evaluate_ready(true);
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] std::uint64_t requests() const noexcept { return requests_; }
  [[nodiscard]] std::uint64_t request_markers() const noexcept {
    return request_markers_;
  }
  [[nodiscard]] std::uint64_t lines() const noexcept { return lines_; }
  [[nodiscard]] std::uint64_t response_markers() const noexcept {
    return response_markers_;
  }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept {
    return output_stall_cycles_;
  }
  [[nodiscard]] std::uint64_t read_bytes() const noexcept {
    return requests_ * source_round_bytes();
  }

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    return phase_ != Phase::kDone;
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return phase_ != Phase::kDone &&
           (staged_input_.has_value() || staged_axi_issue_ ||
            staged_line_.has_value() || staged_parent_.has_value() ||
            staged_end_response_);
  }

  void evaluate(const CycleContext &) override {
    staged_input_.reset();
    staged_axi_issue_ = false;
    staged_line_.reset();
    staged_parent_.reset();
    staged_end_response_ = false;
    switch (phase_) {
    case Phase::kIdle: {
      ReGraphSourceCacheRequest request;
      if (input_.try_pop(request)) {
        staged_input_ = request;
      }
      break;
    }
    case Phase::kNeedIssue:
      staged_axi_issue_ = port_.requests().try_push(AxiRequest{
          .transaction_id = transaction_id(active_source_round_),
          .operation = MemoryOperation::kRead,
          .address =
              source_state_base_ + active_source_round_ * source_round_bytes(),
          .bytes = source_round_bytes(),
          .stream_read_beats = true,
          .write_data = {},
      });
      break;
    case Phase::kStream: {
      const AxiReadBeatResponse *beat = port_.read_beats().front();
      if (beat == nullptr) {
        break;
      }
      if (output_.full()) {
        ++output_stall_cycles_;
        break;
      }
      validate_beat(*beat);
      ReGraphSourceCacheResponse response{
          .source_round = active_source_round_,
          .line = static_cast<std::size_t>(beat->parent_offset / 64),
          .vertices = source_vertices_per_beat(),
      };
      for (std::size_t word = 0; word < response.vertices; ++word) {
        const std::size_t offset = word * state_bytes_per_vertex(policy_);
        response.words[word] = decode_u32(beat->read_data, offset);
        if (uses_auxiliary_state(policy_) &&
            !config_.pagerank_prepared_source) {
          response.auxiliary_words[word] =
              decode_u32(beat->read_data, offset + 4);
        }
      }
      AxiReadBeatResponse consumed;
      if (!port_.read_beats().try_pop(consumed) ||
          !output_.try_push(response)) {
        throw std::logic_error(
            "ReGraph source cacheline atomic transfer failed");
      }
      staged_line_ = std::move(consumed);
      break;
    }
    case Phase::kWaitParent:
      if (port_.responses().front() != nullptr) {
        AxiResponse response;
        if (port_.responses().try_pop(response)) {
          staged_parent_ = std::move(response);
        }
      }
      break;
    case Phase::kEmitEnd:
      staged_end_response_ =
          output_.try_push(ReGraphSourceCacheResponse{.end = true});
      if (!staged_end_response_) {
        ++output_stall_cycles_;
      }
      break;
    case Phase::kDone:
      break;
    }
    set_latched_commit_ready(commit_ready());
  }

  void commit(const CycleContext &) override {
    if (staged_input_.has_value()) {
      if (staged_input_->end) {
        ++request_markers_;
        phase_ = Phase::kEmitEnd;
      } else {
        active_source_round_ = staged_input_->source_round;
        lines_emitted_this_request_ = 0;
        phase_ = Phase::kNeedIssue;
      }
    }
    if (staged_axi_issue_) {
      ++requests_;
      phase_ = Phase::kStream;
    }
    if (staged_line_.has_value()) {
      ++lines_emitted_this_request_;
      ++lines_;
      if (staged_line_->last) {
        if (lines_emitted_this_request_ != lines_per_round()) {
          throw std::runtime_error(
              "ReGraph source HBM request ended at the wrong cacheline");
        }
        phase_ = Phase::kWaitParent;
      }
    }
    if (staged_parent_.has_value()) {
      if (!staged_parent_->success ||
          staged_parent_->transaction_id !=
              transaction_id(active_source_round_) ||
          staged_parent_->read_data.size() != source_round_bytes()) {
        throw std::runtime_error(
            "ReGraph source HBM reader received malformed parent response");
      }
      phase_ = Phase::kIdle;
    }
    if (staged_end_response_) {
      ++response_markers_;
      phase_ = Phase::kDone;
    }
    set_latched_commit_ready(false);
    set_latched_evaluate_ready(evaluate_ready());
  }

private:
  enum class Phase { kIdle, kNeedIssue, kStream, kWaitParent, kEmitEnd, kDone };

  [[nodiscard]] std::size_t lines_per_round() const noexcept {
    return config_.source_buffer_vertices / state_vertices_per_beat(policy_);
  }
  [[nodiscard]] std::uint64_t source_round_bytes() const noexcept {
    return config_.source_buffer_vertices * source_bytes_per_vertex();
  }
  [[nodiscard]] std::size_t source_bytes_per_vertex() const noexcept {
    return config_.pagerank_prepared_source ? 4
                                            : state_bytes_per_vertex(policy_);
  }
  [[nodiscard]] std::size_t source_vertices_per_beat() const noexcept {
    return 64 / source_bytes_per_vertex();
  }
  [[nodiscard]] std::uint64_t transaction_id(std::size_t source_round) const {
    return (algorithm_round_ << 52) |
           (static_cast<std::uint64_t>(partition_) << 44) | (1ULL << 43) |
           source_round;
  }

  void validate_beat(const AxiReadBeatResponse &beat) const {
    if (!beat.success ||
        beat.transaction_id != transaction_id(active_source_round_) ||
        beat.parent_offset % 64 != 0 || beat.read_data.size() != 64 ||
        beat.parent_offset / 64 != lines_emitted_this_request_ ||
        beat.last != (lines_emitted_this_request_ + 1 == lines_per_round())) {
      throw std::runtime_error(
          "ReGraph source HBM reader received malformed cacheline response");
    }
  }

  GraSuReGraphConfig config_;
  Fifo<ReGraphSourceCacheRequest> &input_;
  Fifo<ReGraphSourceCacheResponse> &output_;
  FixedAxiPort &port_;
  GraphAlgorithmPolicy policy_;
  Phase phase_{Phase::kDone};
  std::uint64_t algorithm_round_{};
  std::size_t partition_{};
  std::uint64_t source_state_base_{};
  std::size_t active_source_round_{};
  std::size_t lines_emitted_this_request_{};
  std::optional<ReGraphSourceCacheRequest> staged_input_;
  bool staged_axi_issue_{};
  std::optional<AxiReadBeatResponse> staged_line_;
  std::optional<AxiResponse> staged_parent_;
  bool staged_end_response_{};
  std::uint64_t requests_{};
  std::uint64_t request_markers_{};
  std::uint64_t lines_{};
  std::uint64_t response_markers_{};
  std::uint64_t output_stall_cycles_{};
};

class PmaNativeReader final : public Component, public ReGraphReaderContext {
public:
  struct Ports {
    FixedAxiPort *rows{};
    FixedAxiPort *degree{};
    std::array<FixedAxiPort *, 4> pma{};
    Fifo<PmaEdgeBatch> *output{};
    Fifo<ReGraphSourceCacheRequest> *source_requests{};
    Fifo<ReGraphSourceCacheResponse> *source_responses{};
  };

  PmaNativeReader(std::string name, ClockId clock_id, std::size_t vertices,
                  GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
                  Ports ports)
      : Component(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), ports_(ports) {
    if (vertices_ == 0 || ports_.rows == nullptr || ports_.output == nullptr ||
        ports_.source_requests == nullptr ||
        ports_.source_responses == nullptr ||
        std::any_of(ports_.pma.begin(), ports_.pma.end(),
                    [](const auto *port) { return port == nullptr; })) {
      throw std::invalid_argument("invalid PMA-native reader ports");
    }
    if (uses_degree() && ports_.degree == nullptr) {
      throw std::invalid_argument("PageRank PMA reader requires a degree port");
    }
  }

  void start_partition(std::uint64_t round, const ReGraphPartitionPlan &plan,
                       bool accumulate_dangling) {
    if (phase_ != Phase::kIdle && phase_ != Phase::kDone) {
      throw std::logic_error("PMA reader round started while busy");
    }
    if (round == 0) {
      throw std::invalid_argument("PMA reader round is one-based");
    }
    round_ = round;
    row_base_ = plan.row_base;
    row_channel_ = plan.row_channel;
    pma_base_ = plan.pma_base;
    pma_channel_ = plan.pma_channel;
    accumulate_dangling_ = accumulate_dangling;
    source_ = 0;
    begin_segment_ = 0;
    end_segment_ = 0;
    next_segment_ = 0;
    outstanding_segments_ = 0;
    pending_batches_.clear();
    pp_read_round_ = 0;
    pp_write_round_ = 0;
    pp_request_round_ = 0;
    source_end_sent_ = false;
    source_degree_ = 0;
    source_map_cycles_remaining_ = 0;
    if (config_.pagerank_prepared_source && uses_page_rank()) {
      dangling_mass_.reset();
    } else if (accumulate_dangling_) {
      dangling_mass_.reset();
    } else if (uses_degree() && !dangling_mass_.has_value()) {
      throw std::logic_error(
          "PMA reader partition started before dangling context was computed");
    }
    for (auto &slot : source_cache_) {
      slot.round = std::numeric_limits<std::size_t>::max();
      slot.lines_received = 0;
      slot.words.assign(config_.source_buffer_vertices, 0);
      slot.auxiliary_words.assign(config_.source_buffer_vertices, 0);
    }
    phase_ = Phase::kNeedRow;
    set_latched_evaluate_ready(true);
  }

  [[nodiscard]] bool done() const noexcept override {
    return phase_ == Phase::kDone;
  }
  [[nodiscard]] std::uint64_t row_reads() const noexcept { return row_reads_; }
  [[nodiscard]] std::uint64_t source_requests() const noexcept {
    return source_requests_;
  }
  [[nodiscard]] std::uint64_t source_request_markers() const noexcept {
    return source_request_markers_;
  }
  [[nodiscard]] std::uint64_t source_lines() const noexcept {
    return source_lines_;
  }
  [[nodiscard]] std::uint64_t source_lane_writes() const noexcept {
    return source_lane_writes_;
  }
  [[nodiscard]] std::uint64_t source_response_markers() const noexcept {
    return source_response_markers_;
  }
  [[nodiscard]] std::uint64_t source_wait_cycles() const noexcept {
    return source_wait_cycles_;
  }
  [[nodiscard]] std::uint64_t segment_reads() const noexcept {
    return segment_reads_;
  }
  [[nodiscard]] std::uint64_t degree_reads() const noexcept {
    return degree_reads_;
  }
  [[nodiscard]] std::uint64_t source_map_cycles() const noexcept {
    return source_map_cycles_;
  }
  [[nodiscard]] AlgorithmIterationContext
  iteration_context() const noexcept override {
    if (!uses_degree()) {
      return {};
    }
    const float dangling = GraphAlgorithmPolicy::word_to_float(
        dangling_mass_.value_or(GraphAlgorithmPolicy::float_to_word(0.0F)));
    return {
        .base = policy_.config().kind == GraphAlgorithmKind::kFullPageRank
                    ? policy_.initial_base_word()
                    : GraphAlgorithmPolicy::float_to_word(0.0F),
        .dangling_share = GraphAlgorithmPolicy::float_to_word(
            policy_.config().damping * dangling /
            static_cast<float>(policy_.config().vertices)),
    };
  }

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    return phase_ != Phase::kIdle && phase_ != Phase::kDone;
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    if (phase_ == Phase::kIdle || phase_ == Phase::kDone) {
      return false;
    }
    return staged_tick_ || staged_request_ != RequestKind::kNone ||
           staged_response_.has_value() ||
           staged_degree_response_.has_value() ||
           !staged_pma_responses_.empty() ||
           staged_source_response_.has_value() ||
           staged_source_request_.has_value() || staged_output_ ||
           staged_advance_ || staged_cache_ready_ || staged_source_end_ ||
           phase_ == Phase::kNeedSourceCache;
  }

  void evaluate(const CycleContext &) override {
    staged_tick_ = false;
    staged_request_ = RequestKind::kNone;
    staged_response_.reset();
    staged_degree_response_.reset();
    staged_pma_responses_.clear();
    staged_source_response_.reset();
    staged_source_request_.reset();
    staged_output_ = false;
    staged_advance_ = false;
    staged_cache_ready_ = false;
    staged_source_end_ = false;
    if (phase_ == Phase::kIdle || phase_ == Phase::kDone) {
      set_latched_commit_ready(false);
      return;
    }
    stage_source_response();
    stage_source_request();
    if (!pending_batches_.empty()) {
      staged_output_ = ports_.output->try_push(pending_batches_.front());
    }
    switch (phase_) {
    case Phase::kNeedSourceCache:
      if (source_cache_ready(pp_read_round_)) {
        staged_cache_ready_ = true;
      }
      break;
    case Phase::kNeedDegree:
      if (ports_.degree->requests().try_push(AxiRequest{
              .transaction_id = next_transaction_id_,
              .operation = MemoryOperation::kRead,
              .address = config_.degree_base + source_ * 4,
              .bytes = 4,
              .stream_read_beats = false,
              .write_data = {},
          })) {
        staged_request_ = RequestKind::kDegree;
      }
      break;
    case Phase::kWaitDegree:
      if (ports_.degree->responses().front() != nullptr) {
        AxiResponse response;
        if (ports_.degree->responses().try_pop(response)) {
          staged_degree_response_ = std::move(response);
        }
      }
      break;
    case Phase::kSourceMapDelay:
      staged_tick_ = true;
      break;
    case Phase::kNeedRow:
      if (ports_.rows->requests().try_push(AxiRequest{
              .transaction_id = next_transaction_id_,
              .operation = MemoryOperation::kRead,
              .address = row_base_ + source_ * 8,
              .bytes = 8,
              .stream_read_beats = false,
              .target_channel = row_channel_,
              .write_data = {},
          })) {
        staged_request_ = RequestKind::kRow;
      }
      break;
    case Phase::kWaitRow:
      stage_scalar_response(*ports_.rows);
      break;
    case Phase::kScan:
      stage_pma_responses();
      stage_pma_request();
      if (next_segment_ == end_segment_ && outstanding_segments_ == 0 &&
          pending_batches_.empty()) {
        staged_advance_ = true;
      }
      break;
    case Phase::kSendEnd:
      staged_source_end_ = ports_.source_requests->try_push(
          ReGraphSourceCacheRequest{.end = true});
      break;
    case Phase::kWaitEnd:
      break;
    case Phase::kIdle:
    case Phase::kDone:
      break;
    }
    set_latched_commit_ready(commit_ready());
  }

  void commit(const CycleContext &) override {
    if (staged_source_response_.has_value()) {
      consume_source_response(*staged_source_response_);
    }
    if (staged_source_request_.has_value()) {
      pp_request_round_ = *staged_source_request_ + 1;
      ++source_requests_;
    }
    if (staged_output_) {
      pending_batches_.pop_front();
    }
    if (staged_response_.has_value()) {
      consume_scalar_response(*staged_response_);
      staged_response_.reset();
    }
    if (staged_degree_response_.has_value()) {
      consume_degree_response(*staged_degree_response_);
      staged_degree_response_.reset();
    }
    for (const AxiResponse &response : staged_pma_responses_) {
      consume_pma_response(response);
    }
    if (staged_request_ == RequestKind::kRow) {
      ++row_reads_;
      phase_ = Phase::kWaitRow;
    } else if (staged_request_ == RequestKind::kPma) {
      ++next_segment_;
      ++outstanding_segments_;
      ++segment_reads_;
    } else if (staged_request_ == RequestKind::kDegree) {
      ++degree_reads_;
      phase_ = Phase::kWaitDegree;
    }
    if (staged_request_ != RequestKind::kNone) {
      ++next_transaction_id_;
    }
    if (staged_advance_) {
      advance_source();
    }
    if (staged_cache_ready_) {
      select_source_state();
    } else if (phase_ == Phase::kNeedSourceCache) {
      ++source_wait_cycles_;
    }
    if (staged_source_end_) {
      source_end_sent_ = true;
      ++source_request_markers_;
      phase_ = Phase::kWaitEnd;
    }
    if (phase_ == Phase::kSourceMapDelay && staged_tick_) {
      if (source_map_cycles_remaining_ == 0) {
        throw std::logic_error("ReGraph source-map delay underflow");
      }
      --source_map_cycles_remaining_;
      ++source_map_cycles_;
      if (source_map_cycles_remaining_ == 0) {
        phase_ = Phase::kScan;
      }
    }
    set_latched_commit_ready(false);
    set_latched_evaluate_ready(evaluate_ready());
  }

private:
  enum class Phase {
    kIdle,
    kNeedRow,
    kWaitRow,
    kNeedSourceCache,
    kNeedDegree,
    kWaitDegree,
    kSourceMapDelay,
    kScan,
    kSendEnd,
    kWaitEnd,
    kDone,
  };
  enum class RequestKind { kNone, kRow, kPma, kDegree };

  struct SourceCacheSlot {
    std::size_t round{std::numeric_limits<std::size_t>::max()};
    std::size_t lines_received{};
    std::vector<std::uint32_t> words;
    std::vector<std::uint32_t> auxiliary_words;
  };

  [[nodiscard]] std::size_t pma_port(std::size_t segment) const {
    const std::size_t local = segment >> 1;
    const std::size_t parity = segment & 1U;
    return local < config_.cache_segments_per_half ? parity * 2
                                                   : parity * 2 + 1;
  }

  [[nodiscard]] std::uint64_t pma_address(std::size_t segment) const {
    const std::size_t port = pma_port(segment);
    return pma_base_[port] + (segment >> 1) * kGraSuSegmentBytes;
  }

  void stage_scalar_response(FixedAxiPort &port) {
    if (port.responses().front() == nullptr) {
      return;
    }
    AxiResponse response;
    if (port.responses().try_pop(response)) {
      staged_response_ = std::move(response);
    }
  }

  void stage_source_request() {
    if (phase_ == Phase::kSendEnd || phase_ == Phase::kWaitEnd ||
        source_end_sent_) {
      return;
    }
    const std::size_t request_round =
        std::max(pp_request_round_, pp_read_round_);
    if (request_round - pp_read_round_ > 1) {
      return;
    }
    if (ports_.source_requests->try_push(
            ReGraphSourceCacheRequest{.source_round = request_round})) {
      staged_source_request_ = request_round;
    }
  }

  void stage_source_response() {
    if (ports_.source_responses->front() == nullptr) {
      return;
    }
    ReGraphSourceCacheResponse response;
    if (ports_.source_responses->try_pop(response)) {
      staged_source_response_ = std::move(response);
    }
  }

  [[nodiscard]] std::size_t source_lines_per_round() const noexcept {
    return config_.source_buffer_vertices / state_vertices_per_beat(policy_);
  }

  [[nodiscard]] bool source_cache_ready(std::size_t source_round) const {
    const SourceCacheSlot &slot = source_cache_[source_round & 1U];
    return pp_write_round_ > source_round && slot.round == source_round &&
           slot.lines_received == source_lines_per_round();
  }

  void consume_source_response(const ReGraphSourceCacheResponse &response) {
    if (response.end) {
      if (phase_ != Phase::kWaitEnd) {
        throw std::runtime_error(
            "ReGraph source-cache end response arrived out of phase");
      }
      ++source_response_markers_;
      phase_ = Phase::kDone;
      notify_done();
      return;
    }
    if (response.line >= source_lines_per_round()) {
      throw std::runtime_error("ReGraph source-cache line is out of range");
    }
    SourceCacheSlot &slot = source_cache_[response.source_round & 1U];
    if (response.line == 0) {
      slot.round = response.source_round;
      slot.lines_received = 0;
    }
    if (slot.round != response.source_round ||
        slot.lines_received != response.line) {
      throw std::runtime_error(
          "ReGraph source-cache response order does not match HLS stream");
    }
    const std::size_t expected_vertices =
        config_.pagerank_prepared_source && uses_page_rank()
            ? kStateWordsPerBurst
            : state_vertices_per_beat(policy_);
    if (response.vertices != expected_vertices) {
      throw std::runtime_error(
          "ReGraph source-cache response has the wrong vertex count");
    }
    const std::size_t offset = response.line * response.vertices;
    std::copy_n(response.words.begin(), response.vertices,
                slot.words.begin() + static_cast<std::ptrdiff_t>(offset));
    if (uses_auxiliary_state(policy_)) {
      std::copy_n(response.auxiliary_words.begin(), response.vertices,
                  slot.auxiliary_words.begin() +
                      static_cast<std::ptrdiff_t>(offset));
    }
    ++slot.lines_received;
    pp_write_round_ = response.source_round;
    ++source_lines_;
    source_lane_writes_ += config_.edge_lanes;
  }

  [[nodiscard]] bool uses_degree() const noexcept {
    return uses_page_rank() && !config_.pagerank_prepared_source;
  }

  [[nodiscard]] bool uses_page_rank() const noexcept {
    return policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
           policy_.config().kind == GraphAlgorithmKind::kResidualPageRank;
  }

  void select_source_state() {
    const SourceCacheSlot &slot = source_cache_[pp_read_round_ & 1U];
    const std::size_t offset = source_ % config_.source_buffer_vertices;
    const std::uint32_t encoded = slot.words.at(offset);
    if (config_.pagerank_prepared_source && uses_page_rank()) {
      source_state_ = encoded;
      source_auxiliary_ = 0;
      source_payload_ = encoded;
      source_active_ = encoded != GraphAlgorithmPolicy::float_to_word(0.0F);
      phase_ = Phase::kScan;
      return;
    }
    source_state_ = decode_policy_value(policy_, encoded);
    source_auxiliary_ =
        uses_auxiliary_state(policy_) ? slot.auxiliary_words.at(offset) : 0;
    source_active_ =
        policy_.config().kind == GraphAlgorithmKind::kResidualPageRank
            ? std::fabs(
                  GraphAlgorithmPolicy::word_to_float(source_auxiliary_)) >
                  GraphAlgorithmPolicy::word_to_float(
                      policy_.activation_threshold_word())
            : (encoded & kReGraphActive) != 0;
    if (uses_degree()) {
      phase_ = Phase::kNeedDegree;
    } else {
      prepare_source_payload(0);
    }
  }

  void prepare_source_payload(std::uint32_t out_degree) {
    const AlgorithmSourceResult prepared = policy_.prepare_source(
        AlgorithmVertexState{.primary = source_state_,
                             .auxiliary = source_auxiliary_},
        out_degree);
    source_payload_ = source_active_ ? prepared.edge_payload : 0;
    if (uses_degree()) {
      if (accumulate_dangling_) {
        dangling_mass_ = policy_.reduce(
            dangling_mass_, source_active_
                                ? prepared.dangling_payload
                                : GraphAlgorithmPolicy::float_to_word(0.0F));
      }
      source_map_cycles_remaining_ = config_.pagerank_source_map_latency;
      phase_ = source_map_cycles_remaining_ == 0 ? Phase::kScan
                                                 : Phase::kSourceMapDelay;
    } else {
      phase_ = Phase::kScan;
    }
  }

  void consume_degree_response(const AxiResponse &response) {
    if (phase_ != Phase::kWaitDegree || !response.success ||
        response.read_data.size() != 4) {
      throw std::runtime_error("PMA reader received malformed degree response");
    }
    source_degree_ = decode_u32(response.read_data);
    prepare_source_payload(source_degree_);
  }

  void stage_pma_request() {
    if (next_segment_ >= end_segment_ ||
        pending_batches_.size() +
                staged_pma_responses_.size() * batches_per_segment() +
                batches_per_segment() >
            config_.reader_buffer_batches) {
      return;
    }
    const std::size_t logical_port = pma_port(next_segment_);
    FixedAxiPort &port = *ports_.pma[logical_port];
    if (port.requests().try_push(AxiRequest{
            .transaction_id = next_transaction_id_,
            .operation = MemoryOperation::kRead,
            .address = pma_address(next_segment_),
            .bytes = kGraSuSegmentBytes,
            .stream_read_beats = false,
            .target_channel = pma_channel_[logical_port],
            .write_data = {},
        })) {
      staged_request_ = RequestKind::kPma;
    }
  }

  void stage_pma_responses() {
    for (FixedAxiPort *port : ports_.pma) {
      if (pending_batches_.size() +
              staged_pma_responses_.size() * batches_per_segment() +
              batches_per_segment() >
          config_.reader_buffer_batches) {
        break;
      }
      if (port->responses().front() == nullptr) {
        continue;
      }
      AxiResponse response;
      if (port->responses().try_pop(response)) {
        staged_pma_responses_.push_back(std::move(response));
      }
    }
  }

  void consume_scalar_response(const AxiResponse &response) {
    if (!response.success) {
      throw std::runtime_error("PMA reader received failed AXI response");
    }
    if (phase_ == Phase::kWaitRow) {
      const std::uint64_t bounds = decode_u64(response.read_data);
      begin_segment_ =
          static_cast<std::uint32_t>(bounds >> 32) / kGraSuSegmentSlots;
      end_segment_ = static_cast<std::uint32_t>(bounds) / kGraSuSegmentSlots;
      next_segment_ = begin_segment_;
      if (begin_segment_ == end_segment_ &&
          (!uses_degree() || !accumulate_dangling_)) {
        advance_source();
      } else {
        pp_read_round_ = source_ / config_.source_buffer_vertices;
        phase_ = Phase::kNeedSourceCache;
      }
      return;
    }
    throw std::runtime_error(
        "PMA reader received scalar response out of phase");
  }

  void consume_pma_response(const AxiResponse &response) {
    if (!response.success || response.read_data.size() != kGraSuSegmentBytes ||
        outstanding_segments_ == 0) {
      throw std::runtime_error(
          "PMA reader received malformed segment response");
    }
    --outstanding_segments_;
    for (std::size_t offset = 0; offset < kGraSuSegmentSlots;
         offset += config_.edge_lanes) {
      PmaEdgeBatch batch{
          .source = static_cast<std::uint32_t>(source_),
          .source_payload = source_payload_,
          .source_active = source_active_,
          .lanes = config_.edge_lanes,
      };
      for (std::size_t lane = 0; lane < config_.edge_lanes; ++lane) {
        const std::uint32_t encoded =
            decode_u32(response.read_data, (offset + lane) * 4);
        batch.valid[lane] = !is_grasu_pma_empty(encoded);
        if (batch.valid[lane]) {
          batch.destinations[lane] = decode_grasu_pma_destination(encoded);
          batch.weights[lane] = decode_grasu_pma_weight(encoded);
        }
      }
      pending_batches_.push_back(batch);
    }
  }

  [[nodiscard]] std::size_t batches_per_segment() const noexcept {
    return kGraSuSegmentSlots / config_.edge_lanes;
  }

  void advance_source() {
    ++source_;
    if (source_ == vertices_) {
      phase_ = Phase::kSendEnd;
      return;
    }
    phase_ = Phase::kNeedRow;
  }

  std::size_t vertices_{};
  GraphAlgorithmPolicy policy_;
  GraSuReGraphConfig config_;
  Ports ports_;
  Phase phase_{Phase::kIdle};
  std::uint64_t round_{};
  std::uint64_t row_base_{};
  std::size_t row_channel_{};
  std::array<std::uint64_t, 4> pma_base_{};
  std::array<std::size_t, 4> pma_channel_{};
  bool accumulate_dangling_{};
  std::uint64_t next_transaction_id_{0x7100'0000'0000'0000ULL};
  std::size_t source_{};
  std::size_t begin_segment_{};
  std::size_t end_segment_{};
  std::size_t next_segment_{};
  std::size_t outstanding_segments_{};
  std::array<SourceCacheSlot, 2> source_cache_;
  std::size_t pp_read_round_{};
  std::size_t pp_write_round_{};
  std::size_t pp_request_round_{};
  bool source_active_{};
  std::uint32_t source_state_{};
  std::uint32_t source_auxiliary_{};
  std::uint32_t source_payload_{};
  std::uint32_t source_degree_{};
  std::size_t source_map_cycles_remaining_{};
  std::optional<std::uint32_t> dangling_mass_;
  std::deque<PmaEdgeBatch> pending_batches_;
  RequestKind staged_request_{RequestKind::kNone};
  std::optional<AxiResponse> staged_response_;
  std::optional<AxiResponse> staged_degree_response_;
  std::vector<AxiResponse> staged_pma_responses_;
  std::optional<ReGraphSourceCacheResponse> staged_source_response_;
  std::optional<std::size_t> staged_source_request_;
  bool staged_output_{};
  bool staged_tick_{};
  bool staged_advance_{};
  bool staged_cache_ready_{};
  bool staged_source_end_{};
  bool source_end_sent_{};
  std::uint64_t row_reads_{};
  std::uint64_t source_requests_{};
  std::uint64_t source_request_markers_{};
  std::uint64_t source_lines_{};
  std::uint64_t source_lane_writes_{};
  std::uint64_t source_response_markers_{};
  std::uint64_t source_wait_cycles_{};
  std::uint64_t segment_reads_{};
  std::uint64_t degree_reads_{};
  std::uint64_t source_map_cycles_{};
};

struct NativeEdgeArrayBurst {
  std::uint64_t index{};
  std::array<std::uint32_t, 8> sources{};
  std::array<std::uint32_t, 8> destinations{};
};

class NativeEdgeArrayHbmReader final : public Component {
public:
  NativeEdgeArrayHbmReader(std::string name, ClockId clock_id,
                           std::size_t compact_edge_slots,
                           const GraSuReGraphConfig &config,
                           Fifo<NativeEdgeArrayBurst> &output,
                           FixedAxiPort &port)
      : Component(std::move(name), clock_id),
        compact_edge_slots_(compact_edge_slots), config_(config),
        output_(output), port_(port) {}

  void start_round(std::uint64_t round) {
    if (round == 0 || (phase_ != Phase::kIdle && phase_ != Phase::kDone)) {
      throw std::logic_error("native edge-array reader started while busy");
    }
    round_ = round;
    bursts_emitted_this_round_ = 0;
    phase_ = Phase::kNeedIssue;
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] std::uint64_t requests() const noexcept { return requests_; }
  [[nodiscard]] std::uint64_t bursts() const noexcept { return bursts_; }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept {
    return output_stall_cycles_;
  }

  void evaluate(const CycleContext &) override {
    staged_issue_ = false;
    staged_beat_.reset();
    staged_parent_.reset();
    if (phase_ == Phase::kNeedIssue) {
      staged_issue_ = port_.requests().try_push(AxiRequest{
          .transaction_id = transaction_id(),
          .operation = MemoryOperation::kRead,
          .address = config_.edge_array_base,
          .bytes = static_cast<std::uint32_t>(compact_edge_slots_ * 8),
          .stream_read_beats = true,
          .write_data = {},
      });
    } else if (phase_ == Phase::kStream) {
      const AxiReadBeatResponse *beat = port_.read_beats().front();
      if (beat == nullptr) {
        return;
      }
      if (output_.full()) {
        ++output_stall_cycles_;
        return;
      }
      NativeEdgeArrayBurst burst;
      burst.index = beat->parent_offset / 64;
      validate_beat(*beat, burst.index);
      for (std::size_t lane = 0; lane < 8; ++lane) {
        burst.sources[lane] = decode_u32(beat->read_data, lane * 8);
        burst.destinations[lane] = decode_u32(beat->read_data, lane * 8 + 4);
      }
      AxiReadBeatResponse consumed;
      if (!port_.read_beats().try_pop(consumed) ||
          !output_.try_push(std::move(burst))) {
        throw std::logic_error(
            "native edge-array beat transfer was not atomic");
      }
      staged_beat_ = std::move(consumed);
    } else if (phase_ == Phase::kWaitParent &&
               port_.responses().front() != nullptr) {
      AxiResponse response;
      if (port_.responses().try_pop(response)) {
        staged_parent_ = std::move(response);
      }
    }
  }

  void commit(const CycleContext &) override {
    if (staged_issue_) {
      ++requests_;
      phase_ = Phase::kStream;
    }
    if (staged_beat_.has_value()) {
      ++bursts_emitted_this_round_;
      ++bursts_;
      if (staged_beat_->last) {
        phase_ = Phase::kWaitParent;
      }
    }
    if (staged_parent_.has_value()) {
      if (!staged_parent_->success ||
          staged_parent_->transaction_id != transaction_id() ||
          staged_parent_->read_data.size() != compact_edge_slots_ * 8 ||
          bursts_emitted_this_round_ != compact_edge_slots_ / 8) {
        throw std::runtime_error(
            "native edge-array reader received malformed parent response");
      }
      phase_ = Phase::kDone;
    }
  }

private:
  enum class Phase { kIdle, kNeedIssue, kStream, kWaitParent, kDone };

  [[nodiscard]] std::uint64_t transaction_id() const {
    return 0x7200'0000'0000'0000ULL | round_;
  }

  void validate_beat(const AxiReadBeatResponse &beat,
                     std::uint64_t index) const {
    if (!beat.success || beat.transaction_id != transaction_id() ||
        beat.parent_offset % 64 != 0 || beat.read_data.size() != 64 ||
        index != bursts_emitted_this_round_ ||
        beat.last != (index + 1 == compact_edge_slots_ / 8)) {
      throw std::runtime_error("native edge-array beat is malformed");
    }
  }

  std::size_t compact_edge_slots_{};
  GraSuReGraphConfig config_;
  Fifo<NativeEdgeArrayBurst> &output_;
  FixedAxiPort &port_;
  Phase phase_{Phase::kIdle};
  std::uint64_t round_{};
  std::size_t bursts_emitted_this_round_{};
  bool staged_issue_{};
  std::optional<AxiReadBeatResponse> staged_beat_;
  std::optional<AxiResponse> staged_parent_;
  std::uint64_t requests_{};
  std::uint64_t bursts_{};
  std::uint64_t output_stall_cycles_{};
};

class NativeEdgeArrayScatter final : public Component,
                                     public ReGraphReaderContext {
public:
  NativeEdgeArrayScatter(std::string name, ClockId clock_id,
                         std::size_t vertices, const GraSuReGraphConfig &config,
                         Fifo<NativeEdgeArrayBurst> &input,
                         Fifo<PmaEdgeBatch> &output,
                         Fifo<ReGraphSourceCacheRequest> &source_requests,
                         Fifo<ReGraphSourceCacheResponse> &source_responses,
                         const NativeEdgeArrayHbmReader &edge_reader)
      : Component(std::move(name), clock_id), vertices_(vertices),
        config_(config), input_(input), output_(output),
        source_requests_(source_requests), source_responses_(source_responses),
        edge_reader_(edge_reader) {
    for (auto &slot : source_cache_) {
      slot.words.assign(config_.source_buffer_vertices, 0);
    }
  }

  void start_round(std::uint64_t round) {
    if (round == 0 || (phase_ != Phase::kIdle && phase_ != Phase::kDone)) {
      throw std::logic_error("native edge-array scatter started while busy");
    }
    round_ = round;
    pending_burst_.reset();
    pp_read_round_ = 0;
    pp_write_round_ = 0;
    pp_request_round_ = 0;
    source_end_sent_ = false;
    for (auto &slot : source_cache_) {
      slot.round = std::numeric_limits<std::size_t>::max();
      slot.lines_received = 0;
      std::fill(slot.words.begin(), slot.words.end(), 0);
    }
    phase_ = Phase::kRun;
  }

  [[nodiscard]] bool done() const noexcept override {
    return phase_ == Phase::kDone;
  }
  [[nodiscard]] AlgorithmIterationContext
  iteration_context() const noexcept override {
    return {};
  }
  [[nodiscard]] std::uint64_t source_requests() const noexcept {
    return source_requests_count_;
  }
  [[nodiscard]] std::uint64_t source_request_markers() const noexcept {
    return source_request_markers_;
  }
  [[nodiscard]] std::uint64_t source_lines() const noexcept {
    return source_lines_;
  }
  [[nodiscard]] std::uint64_t source_lane_writes() const noexcept {
    return source_lane_writes_;
  }
  [[nodiscard]] std::uint64_t source_response_markers() const noexcept {
    return source_response_markers_;
  }
  [[nodiscard]] std::uint64_t source_wait_cycles() const noexcept {
    return source_wait_cycles_;
  }
  [[nodiscard]] std::uint64_t cross_source_round_bursts() const noexcept {
    return cross_source_round_bursts_;
  }

  void evaluate(const CycleContext &) override {
    staged_input_.reset();
    staged_source_response_.reset();
    staged_source_request_.reset();
    staged_output_ = false;
    staged_end_ = false;
    if (phase_ == Phase::kIdle || phase_ == Phase::kDone) {
      return;
    }
    stage_source_response();
    stage_source_request();
    if (phase_ == Phase::kWaitEnd) {
      return;
    }
    if (!pending_burst_.has_value() && input_.front() != nullptr) {
      NativeEdgeArrayBurst burst;
      if (input_.try_pop(burst)) {
        staged_input_ = std::move(burst);
      }
      return;
    }
    if (pending_burst_.has_value()) {
      const std::size_t source_round = first_source_round(*pending_burst_);
      pp_read_round_ = source_round;
      if (!source_cache_ready(source_round)) {
        ++source_wait_cycles_;
        return;
      }
      staged_output_ =
          output_.try_push(build_batch(*pending_burst_, source_round));
      return;
    }
    if (edge_reader_.done() && input_.empty() && !source_end_sent_) {
      staged_end_ =
          source_requests_.try_push(ReGraphSourceCacheRequest{.end = true});
    }
  }

  void commit(const CycleContext &) override {
    if (staged_source_response_.has_value()) {
      consume_source_response(*staged_source_response_);
    }
    if (staged_source_request_.has_value()) {
      pp_request_round_ = *staged_source_request_ + 1;
      ++source_requests_count_;
    }
    if (staged_input_.has_value()) {
      pending_burst_ = std::move(staged_input_);
    }
    if (staged_output_) {
      const std::size_t first = first_source_round(*pending_burst_);
      bool crosses_source_round = false;
      for (std::size_t lane = 0; lane < pending_burst_->sources.size();
           ++lane) {
        const std::uint32_t source = pending_burst_->sources[lane];
        const std::uint32_t destination = pending_burst_->destinations[lane];
        if ((source & kReGraphActive) == 0 &&
            (destination & kReGraphActive) == 0 &&
            (source & kReGraphValueMask) / config_.source_buffer_vertices !=
                first) {
          crosses_source_round = true;
          break;
        }
      }
      if (crosses_source_round) {
        ++cross_source_round_bursts_;
      }
      pending_burst_.reset();
    }
    if (staged_end_) {
      source_end_sent_ = true;
      ++source_request_markers_;
      phase_ = Phase::kWaitEnd;
    }
  }

private:
  enum class Phase { kIdle, kRun, kWaitEnd, kDone };
  struct SourceCacheSlot {
    std::size_t round{std::numeric_limits<std::size_t>::max()};
    std::size_t lines_received{};
    std::vector<std::uint32_t> words;
  };

  [[nodiscard]] std::size_t source_lines_per_round() const noexcept {
    return config_.source_buffer_vertices / kStateWordsPerBurst;
  }

  [[nodiscard]] std::size_t
  first_source_round(const NativeEdgeArrayBurst &burst) const {
    return (burst.sources[0] & kReGraphValueMask) /
           config_.source_buffer_vertices;
  }

  [[nodiscard]] bool source_cache_ready(std::size_t source_round) const {
    const SourceCacheSlot &slot = source_cache_[source_round & 1U];
    return pp_write_round_ > source_round && slot.round == source_round &&
           slot.lines_received == source_lines_per_round();
  }

  void stage_source_request() {
    if (phase_ == Phase::kWaitEnd || source_end_sent_) {
      return;
    }
    const std::size_t request_round =
        std::max(pp_request_round_, pp_read_round_);
    if (request_round - pp_read_round_ > 1) {
      return;
    }
    if (source_requests_.try_push(
            ReGraphSourceCacheRequest{.source_round = request_round})) {
      staged_source_request_ = request_round;
    }
  }

  void stage_source_response() {
    if (source_responses_.front() == nullptr) {
      return;
    }
    ReGraphSourceCacheResponse response;
    if (source_responses_.try_pop(response)) {
      staged_source_response_ = std::move(response);
    }
  }

  void consume_source_response(const ReGraphSourceCacheResponse &response) {
    if (response.end) {
      if (phase_ != Phase::kWaitEnd) {
        throw std::runtime_error(
            "native edge scatter received source end out of phase");
      }
      ++source_response_markers_;
      phase_ = Phase::kDone;
      notify_done();
      return;
    }
    if (response.line >= source_lines_per_round() ||
        response.vertices != kStateWordsPerBurst) {
      throw std::runtime_error("native source-cache response is malformed");
    }
    SourceCacheSlot &slot = source_cache_[response.source_round & 1U];
    if (response.line == 0) {
      slot.round = response.source_round;
      slot.lines_received = 0;
    }
    if (slot.round != response.source_round ||
        slot.lines_received != response.line) {
      throw std::runtime_error("native source-cache response is out of order");
    }
    const std::size_t offset = response.line * kStateWordsPerBurst;
    std::copy_n(response.words.begin(), kStateWordsPerBurst,
                slot.words.begin() + static_cast<std::ptrdiff_t>(offset));
    ++slot.lines_received;
    pp_write_round_ = response.source_round;
    ++source_lines_;
    source_lane_writes_ += 8;
  }

  [[nodiscard]] PmaEdgeBatch build_batch(const NativeEdgeArrayBurst &burst,
                                         std::size_t source_round) const {
    PmaEdgeBatch batch{.per_lane_source = true, .lanes = 8};
    const SourceCacheSlot &slot = source_cache_[source_round & 1U];
    for (std::size_t lane = 0; lane < 8; ++lane) {
      const std::uint32_t encoded_source = burst.sources[lane];
      const std::uint32_t encoded_destination = burst.destinations[lane];
      const std::uint32_t source = encoded_source & kReGraphValueMask;
      const std::size_t source_offset = source % config_.source_buffer_vertices;
      const std::uint32_t source_state = slot.words.at(source_offset);
      batch.valid[lane] = (encoded_source & kReGraphActive) == 0 &&
                          (encoded_destination & kReGraphActive) == 0 &&
                          source < vertices_;
      batch.source_payloads[lane] = policy_distance(source_state);
      batch.source_actives[lane] = (source_state & kReGraphActive) != 0;
      batch.destinations[lane] = encoded_destination & kGraSuPmaDestinationMask;
      batch.weights[lane] = static_cast<std::uint16_t>(
          (encoded_destination >> kGraSuPmaWeightShift) & kGraSuPmaWeightMask);
    }
    return batch;
  }

  std::size_t vertices_{};
  GraSuReGraphConfig config_;
  Fifo<NativeEdgeArrayBurst> &input_;
  Fifo<PmaEdgeBatch> &output_;
  Fifo<ReGraphSourceCacheRequest> &source_requests_;
  Fifo<ReGraphSourceCacheResponse> &source_responses_;
  const NativeEdgeArrayHbmReader &edge_reader_;
  Phase phase_{Phase::kIdle};
  std::uint64_t round_{};
  std::array<SourceCacheSlot, 2> source_cache_;
  std::size_t pp_read_round_{};
  std::size_t pp_write_round_{};
  std::size_t pp_request_round_{};
  bool source_end_sent_{};
  std::optional<NativeEdgeArrayBurst> pending_burst_;
  std::optional<NativeEdgeArrayBurst> staged_input_;
  std::optional<ReGraphSourceCacheResponse> staged_source_response_;
  std::optional<std::size_t> staged_source_request_;
  bool staged_output_{};
  bool staged_end_{};
  std::uint64_t source_requests_count_{};
  std::uint64_t source_request_markers_{};
  std::uint64_t source_lines_{};
  std::uint64_t source_lane_writes_{};
  std::uint64_t source_response_markers_{};
  std::uint64_t source_wait_cycles_{};
  std::uint64_t cross_source_round_bursts_{};
};

class ReGraphGather final : public Component {
public:
  ReGraphGather(std::string name, ClockId clock_id, std::size_t vertices,
                GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
                Fifo<PmaEdgeBatch> &input, Fifo<ReGraphGatherRow> &output,
                ReGraphReaderContext &reader)
      : Component(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), input_(input),
        output_(output), reader_(reader), bank_rows_(config.gather_banks),
        bypass_(config.gather_banks,
                std::vector<BypassEntry>(config.gather_bypass_distance + 1)) {
    input_.bind_nonempty_notifier(this, &ReGraphGather::notify_input_nonempty);
    output_.bind_nonfull_notifier(this, &ReGraphGather::notify_output_nonfull);
    reader_.bind_done_notifier(this, &ReGraphGather::notify_reader_done);
    refresh_evaluate_ready();
  }

  ~ReGraphGather() override {
    input_.unbind_nonempty_notifier(this);
    output_.unbind_nonfull_notifier(this);
    reader_.unbind_done_notifier(this);
  }

  void start_partition(std::size_t destination_vertices, bool reset_tmp_prop) {
    if (phase_ != Phase::kIdle && phase_ != Phase::kDone) {
      throw std::logic_error("ReGraph gather round started while busy");
    }
    destination_vertices_ = destination_vertices;
    for (auto &rows : bank_rows_) {
      rows.clear();
    }
    for (auto &entries : bypass_) {
      std::fill(entries.begin(), entries.end(), BypassEntry{});
    }
    pending_physical_writes_.clear();
    if (reset_tmp_prop) {
      remaining_ = divide_ceil(config_.partition_vertices,
                               config_.gather_vertices_per_reset_cycle);
      phase_ = Phase::kReset;
    } else {
      remaining_ = 0;
      phase_ = Phase::kScan;
    }
    drain_cycles_remaining_ = 0;
    next_output_row_ = 0;
    refresh_evaluate_ready();
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] std::uint64_t slots_scanned() const noexcept {
    return slots_scanned_;
  }
  [[nodiscard]] std::uint64_t batches_scanned() const noexcept {
    return batches_scanned_;
  }
  [[nodiscard]] std::uint64_t live_edges() const noexcept {
    return live_edges_;
  }
  [[nodiscard]] std::uint64_t active_edges() const noexcept {
    return active_edges_;
  }
  [[nodiscard]] std::uint64_t reset_cycles() const noexcept {
    return reset_cycles_;
  }
  [[nodiscard]] std::uint64_t merge_cycles() const noexcept {
    return merge_cycles_;
  }
  [[nodiscard]] std::uint64_t pipeline_drain_cycles() const noexcept {
    return pipeline_drain_cycles_;
  }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept {
    return output_stall_cycles_;
  }
  [[nodiscard]] std::uint64_t rows_emitted() const noexcept {
    return rows_emitted_;
  }
  [[nodiscard]] std::uint64_t conflict_cycles() const noexcept { return 0; }
  [[nodiscard]] std::uint64_t bank_updates() const noexcept {
    return bank_updates_;
  }
  [[nodiscard]] std::uint64_t bypass_hits() const noexcept {
    return bypass_hits_;
  }
  [[nodiscard]] std::uint64_t bypass_misses() const noexcept {
    return bypass_misses_;
  }
  [[nodiscard]] std::uint64_t cross_bank_reductions() const noexcept {
    return cross_bank_reductions_;
  }

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    return evaluate_ready_;
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return staged_tick_ || staged_start_drain_ || staged_output_stall_ ||
           staged_row_output_ || staged_batch_.has_value();
  }

  void evaluate(const CycleContext &context) override {
    account_suspended_output_stalls(context.domain_cycle);
    last_evaluate_cycle_ = context.domain_cycle;
    evaluated_once_ = true;
    staged_tick_ = false;
    staged_start_drain_ = false;
    staged_output_stall_ = false;
    staged_row_output_ = false;
    staged_batch_.reset();
    staged_cross_bank_reductions_ = 0;
    switch (phase_) {
    case Phase::kReset:
      staged_tick_ = remaining_ != 0;
      break;
    case Phase::kMerge: {
      ReGraphGatherRow row{.row = next_output_row_};
      for (std::size_t half = 0; half < row.candidates.size(); ++half) {
        const std::size_t vertex = next_output_row_ * 2 + half;
        if (vertex >= destination_vertices_) {
          continue;
        }
        for (const auto &bank : bank_rows_) {
          const auto found = bank.find(next_output_row_);
          if (found == bank.end() || !found->second[half].has_value()) {
            continue;
          }
          if (row.candidates[half].has_value()) {
            ++staged_cross_bank_reductions_;
          }
          row.candidates[half] =
              policy_.reduce(row.candidates[half], *found->second[half]);
        }
      }
      staged_row_output_ = output_.try_push(std::move(row));
      staged_output_stall_ = !staged_row_output_;
      break;
    }
    case Phase::kScan:
      if (input_.front() != nullptr) {
        PmaEdgeBatch batch;
        if (input_.try_pop(batch)) {
          staged_batch_ = batch;
        }
      } else if (reader_.done()) {
        staged_start_drain_ = true;
      }
      break;
    case Phase::kDrain:
      staged_tick_ = true;
      break;
    case Phase::kIdle:
    case Phase::kDone:
      break;
    }
    set_latched_commit_ready(commit_ready());
    refresh_evaluate_ready();
  }

  void commit(const CycleContext &context) override {
    commit_physical_writes(context.domain_cycle);
    if (phase_ == Phase::kReset && staged_tick_) {
      --remaining_;
      ++reset_cycles_;
      if (remaining_ == 0) {
        phase_ = Phase::kScan;
      }
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    if (phase_ == Phase::kMerge) {
      if (staged_output_stall_) {
        ++output_stall_cycles_;
        suspended_output_stall_ = true;
      }
      if (!staged_row_output_) {
        clear_staged();
        refresh_evaluate_ready();
        return;
      }
      cross_bank_reductions_ += staged_cross_bank_reductions_;
      for (auto &bank : bank_rows_) {
        bank.erase(next_output_row_);
      }
      ++next_output_row_;
      ++rows_emitted_;
      ++merge_cycles_;
      if (next_output_row_ ==
          divide_ceil(config_.partition_vertices,
                      config_.gather_vertices_per_merge_cycle)) {
        phase_ = Phase::kDone;
      }
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    if (phase_ == Phase::kDrain && staged_tick_) {
      if (drain_cycles_remaining_ != 0) {
        --drain_cycles_remaining_;
        ++pipeline_drain_cycles_;
      }
      if (drain_cycles_remaining_ == 0) {
        if (!pending_physical_writes_.empty()) {
          throw std::logic_error(
              "ReGraph gather pipeline drained before URAM writes committed");
        }
        next_output_row_ = 0;
        phase_ = Phase::kMerge;
      }
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    if (phase_ != Phase::kScan) {
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    if (staged_batch_.has_value()) {
      consume_batch(*staged_batch_, context.domain_cycle);
      staged_batch_.reset();
    }
    if (staged_start_drain_) {
      drain_cycles_remaining_ = config_.gather_pipeline_latency - 1;
      if (drain_cycles_remaining_ == 0) {
        next_output_row_ = 0;
        phase_ = Phase::kMerge;
      } else {
        phase_ = Phase::kDrain;
      }
    }
    clear_staged();
    refresh_evaluate_ready();
  }

private:
  enum class Phase { kIdle, kReset, kScan, kDrain, kMerge, kDone };

  using GatherRow = std::array<std::optional<std::uint32_t>, 2>;

  struct BypassEntry {
    std::size_t row{};
    GatherRow value{};
    bool valid{};
  };

  struct PendingPhysicalWrite {
    std::size_t bank{};
    std::size_t row{};
    GatherRow value{};
    std::uint64_t due_cycle{};
  };

  static std::size_t divide_ceil(std::size_t value, std::size_t divisor) {
    return (value + divisor - 1) / divisor;
  }

  static void notify_input_nonempty(void *owner) noexcept {
    auto *gather = static_cast<ReGraphGather *>(owner);
    if (gather->phase_ == Phase::kScan) {
      gather->evaluate_ready_ = true;
      gather->set_latched_evaluate_ready(true);
    }
  }

  static void notify_reader_done(void *owner) noexcept {
    auto *gather = static_cast<ReGraphGather *>(owner);
    if (gather->phase_ == Phase::kScan) {
      gather->evaluate_ready_ = true;
      gather->set_latched_evaluate_ready(true);
    }
  }

  static void notify_output_nonfull(void *owner) noexcept {
    auto *gather = static_cast<ReGraphGather *>(owner);
    if (gather->phase_ == Phase::kMerge) {
      gather->evaluate_ready_ = true;
      gather->set_latched_evaluate_ready(true);
    }
  }

  void account_suspended_output_stalls(std::uint64_t cycle) {
    if (!suspended_output_stall_) {
      return;
    }
    if (!evaluated_once_ || cycle <= last_evaluate_cycle_) {
      throw std::logic_error(
          "ReGraph gather suspended-cycle accounting moved backwards");
    }
    const std::uint64_t skipped = cycle - last_evaluate_cycle_ - 1;
    output_stall_cycles_ += skipped;
    output_.account_push_stalls(skipped);
    suspended_output_stall_ = false;
  }

  void refresh_evaluate_ready() noexcept {
    switch (phase_) {
    case Phase::kReset:
    case Phase::kDrain:
      evaluate_ready_ = true;
      break;
    case Phase::kMerge:
      evaluate_ready_ = !suspended_output_stall_ || !output_.full();
      break;
    case Phase::kScan:
      evaluate_ready_ = input_.front() != nullptr || reader_.done();
      break;
    case Phase::kIdle:
    case Phase::kDone:
      evaluate_ready_ = false;
      break;
    }
    set_latched_evaluate_ready(evaluate_ready_);
  }

  void clear_staged() noexcept {
    staged_tick_ = false;
    staged_start_drain_ = false;
    staged_output_stall_ = false;
    staged_row_output_ = false;
    staged_batch_.reset();
    staged_cross_bank_reductions_ = 0;
    set_latched_commit_ready(false);
  }

  void commit_physical_writes(std::uint64_t cycle) {
    while (!pending_physical_writes_.empty() &&
           pending_physical_writes_.front().due_cycle <= cycle) {
      const PendingPhysicalWrite &write = pending_physical_writes_.front();
      bank_rows_[write.bank][write.row] = write.value;
      pending_physical_writes_.pop_front();
    }
  }

  void consume_batch(const PmaEdgeBatch &batch, std::uint64_t cycle) {
    ++batches_scanned_;
    slots_scanned_ += batch.lanes;
    for (std::size_t lane = 0; lane < batch.lanes; ++lane) {
      if (!batch.valid[lane]) {
        continue;
      }
      ++live_edges_;
      const std::uint32_t destination = batch.destinations[lane];
      if (destination >= destination_vertices_) {
        throw std::runtime_error("PMA edge exceeds ReGraph vertex range");
      }
      const bool source_active = batch.per_lane_source
                                     ? batch.source_actives[lane]
                                     : batch.source_active;
      if (!source_active) {
        continue;
      }
      ++active_edges_;
      const std::size_t bank = lane;
      const std::size_t row = destination >> 1;
      const std::size_t half = destination & 1U;
      GatherRow updated{};
      const auto physical = bank_rows_[bank].find(row);
      if (physical != bank_rows_[bank].end()) {
        updated = physical->second;
      }
      bool forwarded = false;
      for (const BypassEntry &entry : bypass_[bank]) {
        if (entry.valid && entry.row == row) {
          updated = entry.value;
          forwarded = true;
        }
      }
      if (forwarded) {
        ++bypass_hits_;
      } else {
        ++bypass_misses_;
      }
      const std::uint32_t source_payload = batch.per_lane_source
                                               ? batch.source_payloads[lane]
                                               : batch.source_payload;
      const std::uint32_t candidate =
          policy_.map_edge(source_payload, batch.weights[lane]);
      updated[half] = policy_.reduce(updated[half], candidate);
      auto &entries = bypass_[bank];
      std::move(entries.begin() + 1, entries.end(), entries.begin());
      entries.back() = BypassEntry{.row = row, .value = updated, .valid = true};
      pending_physical_writes_.push_back(PendingPhysicalWrite{
          .bank = bank,
          .row = row,
          .value = updated,
          .due_cycle = cycle + config_.gather_bypass_distance,
      });
      ++bank_updates_;
    }
  }

  std::size_t vertices_{};
  std::size_t destination_vertices_{};
  GraphAlgorithmPolicy policy_;
  GraSuReGraphConfig config_;
  Fifo<PmaEdgeBatch> &input_;
  Fifo<ReGraphGatherRow> &output_;
  ReGraphReaderContext &reader_;
  std::vector<std::unordered_map<std::size_t, GatherRow>> bank_rows_;
  std::vector<std::vector<BypassEntry>> bypass_;
  std::deque<PendingPhysicalWrite> pending_physical_writes_;
  Phase phase_{Phase::kIdle};
  std::size_t remaining_{};
  std::size_t drain_cycles_remaining_{};
  std::size_t next_output_row_{};
  bool staged_tick_{};
  bool staged_start_drain_{};
  bool staged_output_stall_{};
  bool staged_row_output_{};
  std::optional<PmaEdgeBatch> staged_batch_;
  std::uint64_t staged_cross_bank_reductions_{};
  std::uint64_t batches_scanned_{};
  std::uint64_t slots_scanned_{};
  std::uint64_t live_edges_{};
  std::uint64_t active_edges_{};
  std::uint64_t reset_cycles_{};
  std::uint64_t merge_cycles_{};
  std::uint64_t pipeline_drain_cycles_{};
  std::uint64_t output_stall_cycles_{};
  std::uint64_t rows_emitted_{};
  std::uint64_t bank_updates_{};
  std::uint64_t bypass_hits_{};
  std::uint64_t bypass_misses_{};
  std::uint64_t cross_bank_reductions_{};
  bool evaluate_ready_{};
  bool evaluated_once_{};
  bool suspended_output_stall_{};
  std::uint64_t last_evaluate_cycle_{};
};

class ReGraphMerger final : public Component {
public:
  ReGraphMerger(std::string name, ClockId clock_id,
                const GraSuReGraphConfig &config, Fifo<ReGraphGatherRow> &input,
                Fifo<ReGraphMergedBurst> &output)
      : Component(std::move(name), clock_id), config_(config), input_(input),
        output_(output) {
    input_.bind_nonempty_notifier(this, &ReGraphMerger::notify_input_nonempty);
    output_.bind_nonfull_notifier(this, &ReGraphMerger::notify_output_nonfull);
    refresh_evaluate_ready();
  }

  ~ReGraphMerger() override {
    input_.unbind_nonempty_notifier(this);
    output_.unbind_nonfull_notifier(this);
  }

  void start_round() {
    if (running_ || pending_output_.has_value() || packed_rows_ != 0) {
      throw std::logic_error("ReGraph merger round started while busy");
    }
    consumed_rows_this_round_ = 0;
    done_ = false;
    running_ = true;
    refresh_evaluate_ready();
  }

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] std::uint64_t rows_consumed() const noexcept {
    return rows_consumed_;
  }
  [[nodiscard]] std::uint64_t bursts_emitted() const noexcept {
    return bursts_emitted_;
  }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept {
    return output_stall_cycles_;
  }

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    return evaluate_ready_;
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return running_ && (staged_input_.has_value() || staged_output_ ||
                        staged_output_stall_);
  }

  void evaluate(const CycleContext &context) override {
    account_suspended_output_stalls(context.domain_cycle);
    last_evaluate_cycle_ = context.domain_cycle;
    evaluated_once_ = true;
    staged_input_.reset();
    staged_output_ = false;
    staged_output_stall_ = false;
    if (!running_) {
      refresh_evaluate_ready();
      set_latched_commit_ready(false);
      return;
    }
    if (pending_output_.has_value()) {
      staged_output_ = output_.try_push(*pending_output_);
      if (!staged_output_) {
        staged_output_stall_ = true;
        set_latched_commit_ready(true);
        return;
      }
    }
    if (consumed_rows_this_round_ == rows_per_round() ||
        input_.front() == nullptr) {
      refresh_evaluate_ready();
      set_latched_commit_ready(commit_ready());
      return;
    }
    ReGraphGatherRow row;
    if (input_.try_pop(row)) {
      staged_input_ = std::move(row);
    }
    set_latched_commit_ready(commit_ready());
  }

  void commit(const CycleContext &) override {
    if (!running_) {
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    if (staged_output_stall_) {
      ++output_stall_cycles_;
      suspended_output_stall_ = true;
    }
    if (staged_output_) {
      pending_output_.reset();
      ++bursts_emitted_;
    }
    if (staged_input_.has_value()) {
      if (staged_input_->row != consumed_rows_this_round_) {
        throw std::runtime_error("ReGraph merger received a row out of order");
      }
      const std::size_t base = packed_rows_ * 2;
      packed_candidates_[base] = staged_input_->candidates[0];
      packed_candidates_[base + 1] = staged_input_->candidates[1];
      ++packed_rows_;
      ++consumed_rows_this_round_;
      ++rows_consumed_;
      if (packed_rows_ == kRowsPerBurst) {
        pending_output_ = ReGraphMergedBurst{
            .offset = (consumed_rows_this_round_ - kRowsPerBurst) * 2,
            .candidates = packed_candidates_,
        };
        packed_candidates_.fill(std::nullopt);
        packed_rows_ = 0;
      }
    }
    if (consumed_rows_this_round_ == rows_per_round() &&
        !pending_output_.has_value()) {
      running_ = false;
      done_ = true;
    }
    clear_staged();
    refresh_evaluate_ready();
  }

private:
  static constexpr std::size_t kRowsPerBurst = kStateWordsPerBurst / 2;

  static void notify_input_nonempty(void *owner) noexcept {
    auto *merger = static_cast<ReGraphMerger *>(owner);
    merger->refresh_evaluate_ready();
  }

  static void notify_output_nonfull(void *owner) noexcept {
    auto *merger = static_cast<ReGraphMerger *>(owner);
    merger->refresh_evaluate_ready();
  }

  void account_suspended_output_stalls(std::uint64_t cycle) {
    if (!suspended_output_stall_) {
      return;
    }
    if (!evaluated_once_ || cycle <= last_evaluate_cycle_) {
      throw std::logic_error(
          "ReGraph merger suspended-cycle accounting moved backwards");
    }
    const std::uint64_t skipped = cycle - last_evaluate_cycle_ - 1;
    output_stall_cycles_ += skipped;
    output_.account_push_stalls(skipped);
    suspended_output_stall_ = false;
  }

  void refresh_evaluate_ready() noexcept {
    if (!running_) {
      evaluate_ready_ = false;
    } else if (pending_output_.has_value()) {
      evaluate_ready_ = !suspended_output_stall_ || !output_.full();
    } else {
      evaluate_ready_ = consumed_rows_this_round_ != rows_per_round() &&
                        input_.front() != nullptr;
    }
    set_latched_evaluate_ready(evaluate_ready_);
  }

  void clear_staged() noexcept {
    staged_input_.reset();
    staged_output_ = false;
    staged_output_stall_ = false;
    set_latched_commit_ready(false);
  }

  [[nodiscard]] std::size_t rows_per_round() const noexcept {
    return config_.partition_vertices / 2;
  }

  GraSuReGraphConfig config_;
  Fifo<ReGraphGatherRow> &input_;
  Fifo<ReGraphMergedBurst> &output_;
  std::array<std::optional<std::uint32_t>, kStateWordsPerBurst>
      packed_candidates_{};
  std::optional<ReGraphGatherRow> staged_input_;
  std::optional<ReGraphMergedBurst> pending_output_;
  std::size_t consumed_rows_this_round_{};
  std::size_t packed_rows_{};
  bool staged_output_{};
  bool staged_output_stall_{};
  bool running_{};
  bool done_{};
  bool evaluate_ready_{};
  bool evaluated_once_{};
  bool suspended_output_stall_{};
  std::uint64_t last_evaluate_cycle_{};
  std::uint64_t rows_consumed_{};
  std::uint64_t bursts_emitted_{};
  std::uint64_t output_stall_cycles_{};
};

class ReGraphApply final : public Component {
public:
  ReGraphApply(std::string name, ClockId clock_id, std::size_t vertices,
               GraphAlgorithmPolicy policy, const GraSuReGraphConfig &config,
               Fifo<ReGraphMergedBurst> &input,
               Fifo<ReGraphAppliedBurst> &output, FixedAxiPort &read_port,
               FixedAxiPort &write_port, FixedAxiPort *degree_port,
               const ReGraphReaderContext &iteration_context)
      : Component(std::move(name), clock_id), vertices_(vertices),
        policy_(std::move(policy)), config_(config), input_(input),
        output_(output), read_port_(read_port), write_port_(write_port),
        degree_port_(degree_port), iteration_context_(iteration_context) {
    if (uses_page_rank() && degree_port_ == nullptr) {
      throw std::invalid_argument("PageRank apply requires a degree AXI port");
    }
    input_.bind_nonempty_notifier(this, &ReGraphApply::notify_work_available);
    read_port_.responses().bind_nonempty_notifier(
        this, &ReGraphApply::notify_work_available);
    write_port_.responses().bind_nonempty_notifier(
        this, &ReGraphApply::notify_work_available);
    if (degree_port_ != nullptr) {
      degree_port_->responses().bind_nonempty_notifier(
          this, &ReGraphApply::notify_work_available);
    }
    refresh_evaluate_ready();
  }

  ~ReGraphApply() override {
    input_.unbind_nonempty_notifier(this);
    read_port_.responses().unbind_nonempty_notifier(this);
    write_port_.responses().unbind_nonempty_notifier(this);
    if (degree_port_ != nullptr) {
      degree_port_->responses().unbind_nonempty_notifier(this);
    }
  }

  void start_partition(std::uint64_t round, std::size_t destination_base,
                       std::size_t destination_vertices,
                       bool reset_iteration_totals) {
    if (round == 0 || running_ || !read_inflight_.empty() ||
        !write_inflight_.empty() || !ready_writes_.empty()) {
      throw std::logic_error("ReGraph apply round started while busy");
    }
    completed_writes_ = 0;
    input_bursts_this_round_ = 0;
    next_write_offset_ = 0;
    destination_base_ = destination_base;
    destination_vertices_ = destination_vertices;
    if (reset_iteration_totals) {
      active_vertices_ = 0;
      iteration_error_ = 0.0F;
      next_dangling_ = 0.0F;
    }
    done_ = false;
    running_ = true;
    refresh_evaluate_ready();
  }

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] std::size_t active_vertices() const noexcept {
    return active_vertices_;
  }
  [[nodiscard]] std::uint64_t reads() const noexcept { return reads_; }
  [[nodiscard]] std::uint64_t writes() const noexcept { return writes_; }
  [[nodiscard]] std::uint64_t input_bursts() const noexcept {
    return input_bursts_;
  }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept {
    return output_stall_cycles_;
  }
  [[nodiscard]] std::uint64_t total_activated() const noexcept {
    return total_activated_;
  }
  [[nodiscard]] std::uint64_t read_window_stalls() const noexcept {
    return read_window_stalls_;
  }
  [[nodiscard]] std::uint64_t pipeline_capacity_stalls() const noexcept {
    return pipeline_capacity_stalls_;
  }
  [[nodiscard]] std::uint64_t write_window_stalls() const noexcept {
    return write_window_stalls_;
  }
  [[nodiscard]] std::size_t max_reads_inflight() const noexcept {
    return max_reads_inflight_;
  }
  [[nodiscard]] std::size_t max_pipeline_occupancy() const noexcept {
    return max_pipeline_occupancy_;
  }
  [[nodiscard]] std::size_t max_writes_inflight() const noexcept {
    return max_writes_inflight_;
  }
  void bind_done_notifier(void *owner, ReGraphDoneSignal::Notifier notifier) {
    done_signal_.bind(owner, notifier);
  }
  void unbind_done_notifier(void *owner) noexcept { done_signal_.unbind(owner); }
  [[nodiscard]] float iteration_error() const noexcept {
    return iteration_error_;
  }
  [[nodiscard]] float next_dangling() const noexcept { return next_dangling_; }
  [[nodiscard]] std::uint64_t degree_reads() const noexcept {
    return degree_reads_;
  }

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    return evaluate_ready_;
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return running_ &&
           (staged_read_issue_.has_value() ||
            staged_write_issue_.has_value() ||
            staged_read_response_.has_value() ||
            staged_degree_response_.has_value() ||
            staged_write_response_.has_value() || staged_output_stall_);
  }

  void evaluate(const CycleContext &context) override {
    account_suspended_read_window(context.domain_cycle);
    last_evaluate_cycle_ = context.domain_cycle;
    evaluated_once_ = true;
    staged_read_issue_.reset();
    staged_write_issue_.reset();
    staged_read_response_.reset();
    staged_degree_response_.reset();
    staged_write_response_.reset();
    staged_output_stall_ = false;
    if (!running_) {
      refresh_evaluate_ready();
      set_latched_commit_ready(false);
      return;
    }
    if (read_port_.responses().front() != nullptr) {
      AxiResponse response;
      if (read_port_.responses().try_pop(response)) {
        staged_read_response_ = std::move(response);
      }
    }
    if (write_port_.responses().front() != nullptr) {
      AxiResponse response;
      if (write_port_.responses().try_pop(response)) {
        staged_write_response_ = std::move(response);
      }
    }
    if (degree_port_ != nullptr && degree_port_->responses().front() != nullptr) {
      AxiResponse response;
      if (degree_port_->responses().try_pop(response)) {
        staged_degree_response_ = std::move(response);
      }
    }

    const auto ready =
        std::find_if(ready_writes_.begin(), ready_writes_.end(),
                     [&](const ReadyWrite &item) {
                       return item.offset == next_write_offset_ &&
                              item.due_cycle <= context.domain_cycle;
                     });
    if (ready != ready_writes_.end()) {
      if (write_inflight_.size() >= config_.apply_request_window) {
        ++write_window_stalls_;
      } else {
        const std::size_t index =
            static_cast<std::size_t>(ready - ready_writes_.begin());
        const ReadyWrite &item = ready_writes_[index];
        if (!write_port_.requests().full() && !output_.full()) {
          if (!write_port_.requests().try_push(AxiRequest{
                  .transaction_id = transaction_id(item.offset),
                  .operation = MemoryOperation::kWrite,
                  .address = config_.vertex_state_base +
                             global_offset(item.offset) *
                                 state_bytes_per_vertex(policy_),
                  .bytes = static_cast<std::uint32_t>(item.data.size()),
                  .stream_read_beats = false,
                  .write_data = item.data,
              }) ||
              !output_.try_push(ReGraphAppliedBurst{
                  .offset = item.offset,
                  .data = item.data,
                  .source_data = item.source_data,
              })) {
            throw std::logic_error(
                "ReGraph apply atomic output staging failed");
          }
          staged_write_issue_ = index;
        } else {
          staged_output_stall_ = true;
        }
      }
    }

    if (input_bursts_this_round_ >= total_bursts() ||
        input_.front() == nullptr) {
      refresh_evaluate_ready();
      set_latched_commit_ready(commit_ready());
      return;
    }
    if (read_inflight_.size() >= config_.apply_request_window) {
      ++read_window_stalls_;
      refresh_evaluate_ready();
      set_latched_commit_ready(commit_ready());
      return;
    }
    if (pipeline_occupancy() >= config_.apply_pipeline_capacity) {
      ++pipeline_capacity_stalls_;
      refresh_evaluate_ready();
      set_latched_commit_ready(commit_ready());
      return;
    }
    const ReGraphMergedBurst &next = *input_.front();
    const bool degree_ready =
        degree_port_ == nullptr || !degree_port_->requests().full();
    if (degree_ready && !read_port_.requests().full() &&
        read_port_.requests().try_push(AxiRequest{
            .transaction_id = transaction_id(next.offset),
            .operation = MemoryOperation::kRead,
            .address =
                config_.vertex_state_base +
                global_offset(next.offset) * state_bytes_per_vertex(policy_),
            .bytes = static_cast<std::uint32_t>(
                kStateWordsPerBurst * state_bytes_per_vertex(policy_)),
            .stream_read_beats = false,
            .write_data = {},
        })) {
      if (degree_port_ != nullptr &&
          !degree_port_->requests().try_push(AxiRequest{
              .transaction_id = transaction_id(next.offset),
              .operation = MemoryOperation::kRead,
              .address = config_.degree_base + global_offset(next.offset) * 4,
              .bytes = static_cast<std::uint32_t>(kStateWordsPerBurst * 4),
              .stream_read_beats = false,
              .write_data = {},
          })) {
        throw std::logic_error("ReGraph apply degree request was not atomic");
      }
      ReGraphMergedBurst consumed;
      if (!input_.try_pop(consumed)) {
        throw std::logic_error("ReGraph apply input staging failed");
      }
      staged_read_issue_ = std::move(consumed);
    }
    refresh_evaluate_ready();
    set_latched_commit_ready(commit_ready());
  }

  void commit(const CycleContext &context) override {
    if (!running_) {
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    if (staged_read_response_.has_value()) {
      consume_read_response(*staged_read_response_, context.domain_cycle,
                            false);
      staged_read_response_.reset();
    }
    if (staged_degree_response_.has_value()) {
      consume_read_response(*staged_degree_response_, context.domain_cycle,
                            true);
      staged_degree_response_.reset();
    }
    if (staged_write_response_.has_value()) {
      consume_write_response(*staged_write_response_);
      staged_write_response_.reset();
    }
    if (staged_output_stall_) {
      ++output_stall_cycles_;
    }
    if (staged_read_issue_.has_value()) {
      const std::uint64_t id = transaction_id(staged_read_issue_->offset);
      if (!read_inflight_
               .emplace(id, PendingRead{.burst =
                                            std::move(*staged_read_issue_),
                                        .state_data = std::nullopt,
                                        .degree_data = std::nullopt})
               .second) {
        throw std::logic_error("duplicate ReGraph apply read transaction");
      }
      ++input_bursts_this_round_;
      ++input_bursts_;
      ++reads_;
      degree_reads_ += degree_port_ == nullptr ? 0 : 1;
    }
    if (staged_write_issue_.has_value()) {
      ReadyWrite item = std::move(ready_writes_[*staged_write_issue_]);
      ready_writes_.erase(ready_writes_.begin() + *staged_write_issue_);
      const std::uint64_t id = transaction_id(item.offset);
      if (!write_inflight_.emplace(id, item.offset).second) {
        throw std::logic_error("duplicate ReGraph apply write transaction");
      }
      ++writes_;
      next_write_offset_ += kStateWordsPerBurst;
    }
    max_reads_inflight_ = std::max(max_reads_inflight_, read_inflight_.size());
    max_writes_inflight_ =
        std::max(max_writes_inflight_, write_inflight_.size());
    max_pipeline_occupancy_ =
        std::max(max_pipeline_occupancy_, pipeline_occupancy());
    if (completed_writes_ == total_bursts()) {
      running_ = false;
      done_ = true;
      done_signal_.notify();
    }
    clear_staged();
    refresh_evaluate_ready();
  }

private:
  struct PendingRead {
    ReGraphMergedBurst burst;
    std::optional<std::vector<std::uint8_t>> state_data;
    std::optional<std::vector<std::uint8_t>> degree_data;
  };

  struct ReadyWrite {
    std::size_t offset{};
    std::uint64_t due_cycle{};
    std::vector<std::uint8_t> data;
    std::vector<std::uint8_t> source_data;
  };

  static void notify_work_available(void *owner) noexcept {
    auto *apply = static_cast<ReGraphApply *>(owner);
    apply->evaluate_ready_ = apply->running_;
    apply->set_latched_evaluate_ready(apply->evaluate_ready_);
  }

  void account_suspended_read_window(std::uint64_t cycle) {
    if (!suspended_read_window_) {
      return;
    }
    if (!evaluated_once_ || cycle <= last_evaluate_cycle_) {
      throw std::logic_error(
          "ReGraph apply suspended-cycle accounting moved backwards");
    }
    read_window_stalls_ += cycle - last_evaluate_cycle_ - 1;
    suspended_read_window_ = false;
  }

  [[nodiscard]] bool response_available() const noexcept {
    return read_port_.responses().front() != nullptr ||
           write_port_.responses().front() != nullptr ||
           (degree_port_ != nullptr &&
            degree_port_->responses().front() != nullptr);
  }

  void refresh_evaluate_ready() noexcept {
    const bool input_available =
        input_bursts_this_round_ < total_bursts() &&
        input_.front() != nullptr;
    const bool staged_response = staged_read_response_.has_value() ||
                                 staged_degree_response_.has_value() ||
                                 staged_write_response_.has_value();
    const bool pure_read_window_wait =
        running_ && input_available && ready_writes_.empty() &&
        read_inflight_.size() >= config_.apply_request_window &&
        !response_available() && !staged_response;
    suspended_read_window_ = pure_read_window_wait;
    evaluate_ready_ = running_ && !pure_read_window_wait &&
                      (response_available() || staged_response ||
                       !ready_writes_.empty() || input_available);
    set_latched_evaluate_ready(evaluate_ready_);
  }

  void clear_staged() noexcept {
    staged_read_response_.reset();
    staged_degree_response_.reset();
    staged_write_response_.reset();
    staged_read_issue_.reset();
    staged_write_issue_.reset();
    staged_output_stall_ = false;
    set_latched_commit_ready(false);
  }

  [[nodiscard]] bool uses_page_rank() const noexcept {
    return policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
           policy_.config().kind == GraphAlgorithmKind::kResidualPageRank;
  }

  [[nodiscard]] std::uint64_t transaction_id(std::size_t offset) const {
    return global_offset(offset) / kStateWordsPerBurst;
  }

  [[nodiscard]] std::size_t global_offset(std::size_t offset) const noexcept {
    return destination_base_ + offset;
  }

  [[nodiscard]] std::size_t total_bursts() const noexcept {
    return config_.partition_vertices / kStateWordsPerBurst;
  }

  [[nodiscard]] std::size_t pipeline_occupancy() const noexcept {
    return read_inflight_.size() + ready_writes_.size();
  }

  void consume_read_response(const AxiResponse &response, std::uint64_t cycle,
                             bool degree_response) {
    const auto found = read_inflight_.find(response.transaction_id);
    const std::size_t expected_bytes =
        degree_response ? kStateWordsPerBurst * 4
                        : kStateWordsPerBurst * state_bytes_per_vertex(policy_);
    if (!response.success || found == read_inflight_.end() ||
        response.read_data.size() != expected_bytes) {
      throw std::runtime_error(
          "ReGraph apply received malformed read response");
    }
    if (degree_response) {
      found->second.degree_data = response.read_data;
    } else {
      found->second.state_data = response.read_data;
    }
    if (!found->second.state_data.has_value() ||
        (degree_port_ != nullptr && !found->second.degree_data.has_value())) {
      return;
    }
    PendingRead pending = std::move(found->second);
    read_inflight_.erase(found);
    complete_read(std::move(pending), cycle);
  }

  void complete_read(PendingRead pending, std::uint64_t cycle) {
    ReGraphMergedBurst &burst = pending.burst;
    const std::vector<std::uint8_t> &state_data = *pending.state_data;
    std::array<std::uint32_t, kStateWordsPerBurst> result{};
    std::array<std::uint32_t, kStateWordsPerBurst> auxiliary{};
    std::array<std::uint32_t, kStateWordsPerBurst> source_payload{};
    for (std::size_t lane = 0; lane < result.size(); ++lane) {
      const std::size_t local_vertex = burst.offset + lane;
      const std::size_t vertex = destination_base_ + local_vertex;
      const std::size_t byte_offset = lane * state_bytes_per_vertex(policy_);
      const std::uint32_t encoded = decode_u32(response.read_data, byte_offset);
      if (local_vertex >= destination_vertices_ || vertex >= vertices_) {
        result[lane] =
            policy_.config().kind == GraphAlgorithmKind::kWeightedSssp
                ? kReGraphInfinity
                : GraphAlgorithmPolicy::float_to_word(0.0F);
        auxiliary[lane] = GraphAlgorithmPolicy::float_to_word(0.0F);
        source_payload[lane] = GraphAlgorithmPolicy::float_to_word(0.0F);
        continue;
      }
      AlgorithmVertexState old_state{
          .primary = decode_policy_value(policy_, encoded),
          .auxiliary = uses_auxiliary_state(policy_)
                           ? decode_u32(state_data, byte_offset + 4)
                           : 0,
      };
      if (policy_.config().kind == GraphAlgorithmKind::kResidualPageRank &&
          std::fabs(GraphAlgorithmPolicy::word_to_float(old_state.auxiliary)) >
              GraphAlgorithmPolicy::word_to_float(
                  policy_.activation_threshold_word())) {
        old_state = policy_.prepare_source(old_state, 0).state_after;
      }
      const AlgorithmApplyResult applied = policy_.apply(
          old_state, burst.candidates[lane],
          iteration_context_.iteration_context());
      result[lane] = encode_policy_value(policy_, applied.state_after.primary,
                                         applied.active);
      auxiliary[lane] = applied.state_after.auxiliary;
      if (uses_page_rank()) {
        const std::uint32_t degree =
            decode_u32(*pending.degree_data, lane * 4);
        const float value = GraphAlgorithmPolicy::word_to_float(
            policy_.config().kind == GraphAlgorithmKind::kFullPageRank
                ? applied.state_after.primary
                : applied.state_after.auxiliary);
        const bool source_active =
            policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
            applied.active;
        source_payload[lane] = GraphAlgorithmPolicy::float_to_word(
            source_active && degree != 0
                ? policy_.config().damping * value / static_cast<float>(degree)
                : 0.0F);
        if (source_active && degree == 0) {
          next_dangling_ += value;
        }
      } else {
        source_payload[lane] = result[lane];
      }
      iteration_error_ += applied.error;
      if (applied.active) {
        ++active_vertices_;
        ++total_activated_;
      }
    }
    ready_writes_.push_back(ReadyWrite{
        .offset = burst.offset,
        .due_cycle = cycle + config_.apply_pipeline_latency,
        .data = encode_state_words(policy_, result, auxiliary),
        .source_data = encode_words(source_payload),
    });
  }

  void consume_write_response(const AxiResponse &response) {
    const auto found = write_inflight_.find(response.transaction_id);
    if (!response.success || found == write_inflight_.end() ||
        !response.read_data.empty()) {
      throw std::runtime_error(
          "ReGraph apply received malformed write response");
    }
    write_inflight_.erase(found);
    ++completed_writes_;
  }

  std::size_t vertices_{};
  std::size_t destination_base_{};
  std::size_t destination_vertices_{};
  GraphAlgorithmPolicy policy_;
  GraSuReGraphConfig config_;
  Fifo<ReGraphMergedBurst> &input_;
  Fifo<ReGraphAppliedBurst> &output_;
  FixedAxiPort &read_port_;
  FixedAxiPort &write_port_;
  FixedAxiPort *degree_port_{};
  const ReGraphReaderContext &iteration_context_;
  std::unordered_map<std::uint64_t, PendingRead> read_inflight_;
  std::unordered_map<std::uint64_t, std::size_t> write_inflight_;
  std::deque<ReadyWrite> ready_writes_;
  std::optional<AxiResponse> staged_read_response_;
  std::optional<AxiResponse> staged_degree_response_;
  std::optional<AxiResponse> staged_write_response_;
  std::optional<ReGraphMergedBurst> staged_read_issue_;
  std::optional<std::size_t> staged_write_issue_;
  std::size_t completed_writes_{};
  std::size_t input_bursts_this_round_{};
  std::size_t next_write_offset_{};
  std::size_t active_vertices_{};
  float iteration_error_{};
  float next_dangling_{};
  bool staged_output_stall_{};
  bool running_{};
  bool done_{};
  bool evaluate_ready_{};
  bool evaluated_once_{};
  bool suspended_read_window_{};
  std::uint64_t last_evaluate_cycle_{};
  std::uint64_t reads_{};
  std::uint64_t degree_reads_{};
  std::uint64_t writes_{};
  std::uint64_t input_bursts_{};
  std::uint64_t output_stall_cycles_{};
  std::uint64_t total_activated_{};
  std::uint64_t read_window_stalls_{};
  std::uint64_t pipeline_capacity_stalls_{};
  std::uint64_t write_window_stalls_{};
  std::size_t max_reads_inflight_{};
  std::size_t max_pipeline_occupancy_{};
  std::size_t max_writes_inflight_{};
  ReGraphDoneSignal done_signal_;
};

class ReGraphHbmWrapper final : public Component {
public:
  ReGraphHbmWrapper(std::string name, ClockId clock_id,
                    const GraSuReGraphConfig &config,
                    GraphAlgorithmPolicy policy,
                    Fifo<ReGraphAppliedBurst> &input,
                    FixedAxiPort &primary_write_port,
                    FixedAxiPort &mirror_write_port)
      : Component(std::move(name), clock_id), config_(config), input_(input),
        write_ports_{&primary_write_port, &mirror_write_port},
        policy_(std::move(policy)) {
    input_.bind_nonempty_notifier(this,
                                  &ReGraphHbmWrapper::notify_work_available);
    for (FixedAxiPort *port : write_ports_) {
      port->responses().bind_nonempty_notifier(
          this, &ReGraphHbmWrapper::notify_work_available);
    }
    refresh_evaluate_ready();
  }

  ~ReGraphHbmWrapper() override {
    input_.unbind_nonempty_notifier(this);
    for (FixedAxiPort *port : write_ports_) {
      port->responses().unbind_nonempty_notifier(this);
    }
  }

  void start_partition(std::uint64_t round, std::size_t destination_base) {
    const bool writes_pending =
        std::any_of(write_inflight_.begin(), write_inflight_.end(),
                    [](const auto &entries) { return !entries.empty(); });
    if (round == 0 || running_ || writes_pending || !pipeline_.empty()) {
      throw std::logic_error("ReGraph HBM wrapper round started while busy");
    }
    target_source_base_ = config_.source_state_base +
                          (round & 1U) * config_.source_state_buffer_stride +
                          destination_base * 4;
    destination_base_ = destination_base;
    input_bursts_this_round_ = 0;
    completed_writes_ = 0;
    done_ = false;
    running_ = true;
    refresh_evaluate_ready();
  }

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] std::uint64_t input_bursts() const noexcept {
    return input_bursts_;
  }
  [[nodiscard]] std::uint64_t source_writes() const noexcept {
    return source_writes_;
  }
  [[nodiscard]] std::uint64_t pipeline_capacity_stalls() const noexcept {
    return pipeline_capacity_stalls_;
  }
  [[nodiscard]] std::uint64_t write_window_stalls() const noexcept {
    return write_window_stalls_;
  }
  [[nodiscard]] std::size_t max_pipeline_occupancy() const noexcept {
    return max_pipeline_occupancy_;
  }
  [[nodiscard]] std::size_t max_writes_inflight() const noexcept {
    return max_writes_inflight_;
  }
  void bind_done_notifier(void *owner, ReGraphDoneSignal::Notifier notifier) {
    done_signal_.bind(owner, notifier);
  }
  void unbind_done_notifier(void *owner) noexcept { done_signal_.unbind(owner); }

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    return evaluate_ready_;
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return running_ &&
           (staged_input_.has_value() || staged_write_issue_.has_value() ||
            std::any_of(staged_write_responses_.begin(),
                        staged_write_responses_.end(),
                        [](const auto &response) {
                          return response.has_value();
                        }));
  }

  void evaluate(const CycleContext &context) override {
    staged_input_.reset();
    staged_write_issue_.reset();
    for (auto &response : staged_write_responses_) {
      response.reset();
    }
    if (!running_) {
      refresh_evaluate_ready();
      set_latched_commit_ready(false);
      return;
    }
    for (std::size_t port = 0; port < write_ports_.size(); ++port) {
      if (write_ports_[port]->responses().front() != nullptr) {
        AxiResponse response;
        if (write_ports_[port]->responses().try_pop(response)) {
          staged_write_responses_[port] = std::move(response);
        }
      }
    }

    const auto ready = std::find_if(
        pipeline_.begin(), pipeline_.end(), [&](const ReadyWrite &item) {
          return item.due_cycle <= context.domain_cycle;
        });
    if (ready != pipeline_.end()) {
      if (!write_window_available()) {
        ++write_window_stalls_;
      } else if (write_request_fifos_available()) {
        const std::size_t index =
            static_cast<std::size_t>(ready - pipeline_.begin());
        const ReadyWrite &item = pipeline_[index];
        for (FixedAxiPort *port : write_ports_) {
          if (!port->requests().try_push(AxiRequest{
                  .transaction_id = transaction_id(item.burst.offset),
                  .operation = MemoryOperation::kWrite,
                  .address =
                      target_source_base_ +
                      item.burst.offset * state_bytes_per_vertex(policy_),
                  .bytes = static_cast<std::uint32_t>(item.burst.data.size()),
                  .stream_read_beats = false,
                  .write_data = item.burst.source_data,
              })) {
            throw std::logic_error(
                "ReGraph HBM wrapper atomic write staging failed");
          }
        }
        staged_write_issue_ = index;
      } else {
        ++write_window_stalls_;
      }
    }

    if (input_bursts_this_round_ == total_bursts() ||
        input_.front() == nullptr) {
      refresh_evaluate_ready();
      set_latched_commit_ready(commit_ready());
      return;
    }
    if (pipeline_.size() >= config_.hbm_wrapper_pipeline_capacity) {
      ++pipeline_capacity_stalls_;
      refresh_evaluate_ready();
      set_latched_commit_ready(commit_ready());
      return;
    }
    ReGraphAppliedBurst burst;
    if (input_.try_pop(burst)) {
      staged_input_ = std::move(burst);
    }
    refresh_evaluate_ready();
    set_latched_commit_ready(commit_ready());
  }

  void commit(const CycleContext &context) override {
    if (!running_) {
      clear_staged();
      refresh_evaluate_ready();
      return;
    }
    for (std::size_t port = 0; port < staged_write_responses_.size(); ++port) {
      if (staged_write_responses_[port].has_value()) {
        consume_write_response(*staged_write_responses_[port], port);
      }
    }
    if (staged_write_issue_.has_value()) {
      ReadyWrite item = std::move(pipeline_[*staged_write_issue_]);
      pipeline_.erase(pipeline_.begin() + *staged_write_issue_);
      const std::uint64_t id = transaction_id(item.burst.offset);
      for (auto &entries : write_inflight_) {
        if (!entries.emplace(id, item.burst.offset).second) {
          throw std::logic_error(
              "duplicate ReGraph HBM wrapper write transaction");
        }
      }
      source_writes_ += write_ports_.size();
    }
    if (staged_input_.has_value()) {
      const std::size_t expected_offset =
          input_bursts_this_round_ * kStateWordsPerBurst;
      if (staged_input_->offset != expected_offset) {
        throw std::runtime_error(
            "ReGraph HBM wrapper received a burst out of order");
      }
      pipeline_.push_back(ReadyWrite{
          .burst = std::move(*staged_input_),
          .due_cycle =
              context.domain_cycle + config_.hbm_wrapper_pipeline_latency,
      });
      ++input_bursts_this_round_;
      ++input_bursts_;
    }
    max_pipeline_occupancy_ =
        std::max(max_pipeline_occupancy_, pipeline_.size());
    for (const auto &entries : write_inflight_) {
      max_writes_inflight_ = std::max(max_writes_inflight_, entries.size());
    }
    if (input_bursts_this_round_ == total_bursts() && pipeline_.empty() &&
        completed_writes_ == total_bursts() * write_ports_.size()) {
      running_ = false;
      done_ = true;
      done_signal_.notify();
    }
    clear_staged();
    refresh_evaluate_ready();
  }

private:
  struct ReadyWrite {
    ReGraphAppliedBurst burst;
    std::uint64_t due_cycle{};
  };

  static void notify_work_available(void *owner) noexcept {
    auto *wrapper = static_cast<ReGraphHbmWrapper *>(owner);
    wrapper->evaluate_ready_ = wrapper->running_;
    wrapper->set_latched_evaluate_ready(wrapper->evaluate_ready_);
  }

  [[nodiscard]] bool response_available() const noexcept {
    return std::any_of(write_ports_.begin(), write_ports_.end(),
                       [](FixedAxiPort *port) {
                         return port->responses().front() != nullptr;
                       });
  }

  void refresh_evaluate_ready() noexcept {
    evaluate_ready_ =
        running_ &&
        (response_available() || !pipeline_.empty() ||
         (input_bursts_this_round_ < total_bursts() &&
          input_.front() != nullptr));
    set_latched_evaluate_ready(evaluate_ready_);
  }

  void clear_staged() noexcept {
    staged_input_.reset();
    staged_write_issue_.reset();
    for (auto &response : staged_write_responses_) {
      response.reset();
    }
    set_latched_commit_ready(false);
  }

  [[nodiscard]] std::size_t total_bursts() const noexcept {
    return config_.partition_vertices / kStateWordsPerBurst;
  }

  [[nodiscard]] std::uint64_t transaction_id(std::size_t offset) const {
    return (destination_base_ + offset) / kStateWordsPerBurst;
  }

  [[nodiscard]] bool write_window_available() const noexcept {
    return std::all_of(write_inflight_.begin(), write_inflight_.end(),
                       [&](const auto &entries) {
                         return entries.size() < config_.apply_request_window;
                       });
  }

  [[nodiscard]] bool write_request_fifos_available() const noexcept {
    return std::all_of(
        write_ports_.begin(), write_ports_.end(),
        [](const auto *port) { return !port->requests().full(); });
  }

  void consume_write_response(const AxiResponse &response, std::size_t port) {
    auto &entries = write_inflight_.at(port);
    const auto found = entries.find(response.transaction_id);
    if (!response.success || found == entries.end() ||
        !response.read_data.empty()) {
      throw std::runtime_error(
          "ReGraph HBM wrapper received malformed write response");
    }
    entries.erase(found);
    ++completed_writes_;
  }

  GraSuReGraphConfig config_;
  Fifo<ReGraphAppliedBurst> &input_;
  std::array<FixedAxiPort *, 2> write_ports_;
  GraphAlgorithmPolicy policy_;
  std::array<std::unordered_map<std::uint64_t, std::size_t>, 2> write_inflight_;
  std::deque<ReadyWrite> pipeline_;
  std::optional<ReGraphAppliedBurst> staged_input_;
  std::optional<std::size_t> staged_write_issue_;
  std::array<std::optional<AxiResponse>, 2> staged_write_responses_;
  std::size_t input_bursts_this_round_{};
  std::size_t completed_writes_{};
  std::uint64_t target_source_base_{};
  std::size_t destination_base_{};
  bool running_{};
  bool done_{};
  bool evaluate_ready_{};
  std::uint64_t input_bursts_{};
  std::uint64_t source_writes_{};
  std::uint64_t pipeline_capacity_stalls_{};
  std::uint64_t write_window_stalls_{};
  std::size_t max_pipeline_occupancy_{};
  std::size_t max_writes_inflight_{};
  ReGraphDoneSignal done_signal_;
};

struct GraSuReGraphWorker {
  ReGraphSourceHbmReader *source_hbm{};
  PmaNativeReader *reader{};
  ReGraphGather *gather{};
  ReGraphMerger *merger{};
  ReGraphApply *apply{};
  ReGraphHbmWrapper *wrapper{};
  std::optional<std::size_t> partition;
  bool downstream_started{};

  [[nodiscard]] bool done() const noexcept {
    return partition.has_value() && downstream_started &&
           source_hbm->done() && reader->done() && gather->done() &&
           merger->done() && apply->done() && wrapper->done();
  }
};

class ReGraphFrontendMux final : public Component {
public:
  ReGraphFrontendMux(std::string name, ClockId clock_id,
                     const GraSuReGraphConfig &config,
                     std::array<Fifo<ReGraphGatherRow> *, 4> inputs,
                     Fifo<ReGraphGatherRow> &output)
      : Component(std::move(name), clock_id), config_(config), inputs_(inputs),
        output_(output) {
    if (std::any_of(inputs_.begin(), inputs_.end(),
                    [](const auto *input) { return input == nullptr; })) {
      throw std::invalid_argument("ReGraph frontend mux input is null");
    }
  }

  void start_partition(std::size_t partition) {
    if (running_) {
      throw std::logic_error("ReGraph frontend mux started while busy");
    }
    selected_ = partition % inputs_.size();
    rows_forwarded_this_partition_ = 0;
    running_ = true;
    done_ = false;
  }

  [[nodiscard]] bool done() const noexcept { return done_; }
  [[nodiscard]] std::uint64_t rows_forwarded() const noexcept {
    return rows_forwarded_;
  }
  [[nodiscard]] std::uint64_t input_wait_cycles() const noexcept {
    return input_wait_cycles_;
  }
  [[nodiscard]] std::uint64_t output_stall_cycles() const noexcept {
    return output_stall_cycles_;
  }

  void evaluate(const CycleContext &) override {
    staged_transfer_ = false;
    staged_input_wait_ = false;
    staged_output_stall_ = false;
    if (!running_) {
      return;
    }
    Fifo<ReGraphGatherRow> &input = *inputs_[selected_];
    if (input.front() == nullptr) {
      staged_input_wait_ = true;
      return;
    }
    if (output_.full()) {
      staged_output_stall_ = true;
      return;
    }
    ReGraphGatherRow row;
    if (!input.try_pop(row) || !output_.try_push(row)) {
      throw std::logic_error("ReGraph frontend mux atomic transfer failed");
    }
    if (row.row != rows_forwarded_this_partition_) {
      throw std::runtime_error(
          "ReGraph frontend mux received a row out of order");
    }
    staged_transfer_ = true;
  }

  void commit(const CycleContext &) override {
    if (!running_) {
      return;
    }
    if (staged_input_wait_) {
      ++input_wait_cycles_;
    }
    if (staged_output_stall_) {
      ++output_stall_cycles_;
    }
    if (!staged_transfer_) {
      return;
    }
    ++rows_forwarded_this_partition_;
    ++rows_forwarded_;
    if (rows_forwarded_this_partition_ == rows_per_partition()) {
      running_ = false;
      done_ = true;
    }
  }

private:
  [[nodiscard]] std::size_t rows_per_partition() const noexcept {
    return config_.partition_vertices / config_.gather_vertices_per_merge_cycle;
  }

  GraSuReGraphConfig config_;
  std::array<Fifo<ReGraphGatherRow> *, 4> inputs_;
  Fifo<ReGraphGatherRow> &output_;
  std::size_t selected_{};
  std::size_t rows_forwarded_this_partition_{};
  bool running_{};
  bool done_{true};
  bool staged_transfer_{};
  bool staged_input_wait_{};
  bool staged_output_stall_{};
  std::uint64_t rows_forwarded_{};
  std::uint64_t input_wait_cycles_{};
  std::uint64_t output_stall_cycles_{};
};

class GraSuReGraphController final : public Component {
public:
  GraSuReGraphController(std::string name, ClockId clock_id,
                         GraphAlgorithmKind algorithm, std::size_t round_limit,
                         bool fixed_round_limit,
                         std::vector<ReGraphPartitionPlan> partitions,
                         std::vector<GraSuReGraphWorker> workers,
                         ReGraphIterationContext *iteration_context,
                         ReGraphPageRankSourcePrepare *source_prepare,
                         bool shared_downstream)
      : Component(std::move(name), clock_id), algorithm_(algorithm),
        round_limit_(round_limit), fixed_round_limit_(fixed_round_limit),
        partitions_(std::move(partitions)), source_hbm_(source_hbm),
        reader_(reader), gather_(gather), merger_(merger), apply_(apply),
        wrapper_(wrapper) {
    if (partitions_.empty()) {
      throw std::invalid_argument("ReGraph controller requires a partition");
    }
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] bool failed() const noexcept { return !failure_.empty(); }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] std::uint64_t supersteps() const noexcept { return round_; }
  [[nodiscard]] std::uint64_t partition_passes() const noexcept {
    return partition_passes_;
  }
  [[nodiscard]] std::uint64_t pipeline_busy_cycles() const noexcept {
    return pipeline_busy_cycles_;
  }
  [[nodiscard]] std::size_t max_parallel_partitions() const noexcept {
    return max_parallel_partitions_;
  }
  [[nodiscard]] std::size_t max_parallel_downstream_partitions()
      const noexcept {
    return max_parallel_downstream_partitions_;
  }
  [[nodiscard]] std::uint64_t downstream_busy_cycles() const noexcept {
    return downstream_busy_cycles_;
  }
  [[nodiscard]] float iteration_error() const noexcept {
    return last_iteration_error_;
  }
  [[nodiscard]] const std::vector<std::size_t> &frontier_out_sizes()
      const noexcept {
    return frontier_out_sizes_;
  }

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_latched_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    return evaluate_ready_;
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return !failed() && !done() &&
           (staged_ != Action::kNone || !staged_completed_workers_.empty());
  }

  void evaluate(const CycleContext &) override {
    staged_ = Action::kNone;
    staged_completed_workers_.clear();
    if (failed() || done()) {
      set_latched_commit_ready(false);
      return;
    }
    if (phase_ == Phase::kStart) {
      staged_ = source_prepare_ == nullptr ? Action::kStartSuperstep
                                          : Action::kStartPrepare;
    } else if (phase_ == Phase::kPrepare && source_prepare_->done()) {
      staged_ = Action::kStartSuperstep;
    } else if (phase_ == Phase::kRound && source_hbm_.done() &&
               reader_.done() && gather_.done() && merger_.done() &&
               apply_.done() && wrapper_.done()) {
      if (partition_ + 1 < partitions_.size()) {
        staged_ = Action::kNextPartition;
      } else if (fixed_round_limit_ ||
                 algorithm_ == GraphAlgorithmKind::kFullPageRank) {
        staged_ =
            round_ == round_limit_ ? Action::kFinish : Action::kNextSuperstep;
      } else {
        staged_ = prospective_active == 0 ? Action::kFinish
                                          : Action::kNextSuperstep;
      }
    }
    refresh_evaluate_ready();
    set_latched_commit_ready(commit_ready());
  }

  void commit(const CycleContext &context) override {
    account_suspended_busy_cycles(context.domain_cycle);
    for (const std::size_t worker_index : staged_completed_workers_) {
      GraSuReGraphWorker &worker = workers_.at(worker_index);
      iteration_active_vertices_ += worker.apply->active_vertices();
      iteration_error_ += worker.apply->iteration_error();
      iteration_dangling_ += worker.apply->next_dangling();
      ++completed_partitions_;
      worker.partition.reset();
      worker.downstream_started = false;
    }
    if (staged_ == Action::kNextSuperstep || staged_ == Action::kFinish) {
      frontier_out_sizes_.push_back(iteration_active_vertices_);
    }
    if (staged_ == Action::kStartPrepare) {
      source_prepare_->start();
      phase_ = Phase::kPrepare;
    } else if (staged_ == Action::kStartSuperstep ||
        staged_ == Action::kNextSuperstep) {
      if (round_ == round_limit_) {
        failure_ = "ReGraph algorithm exceeded configured round limit";
        staged_ = Action::kNone;
        staged_completed_workers_.clear();
        set_latched_commit_ready(false);
        return;
      }
      if (round_ != 0 && iteration_context_ != nullptr) {
        iteration_context_->set_dangling(iteration_dangling_);
      }
      ++round_;
      next_partition_ = 0;
      completed_partitions_ = 0;
      iteration_active_vertices_ = 0;
      iteration_error_ = 0.0F;
      iteration_dangling_ = 0.0F;
      dispatch_available_workers();
      start_waiting_downstream();
      phase_ = Phase::kRound;
    } else if (staged_ == Action::kFinish) {
      last_iteration_error_ = iteration_error_;
      phase_ = Phase::kDone;
    }
    if (!staged_completed_workers_.empty() && staged_ == Action::kNone) {
      dispatch_available_workers();
      start_waiting_downstream();
      if (completed_partitions_ == partitions_.size()) {
        last_iteration_error_ = iteration_error_;
      }
    }
    const std::size_t busy = busy_worker_count();
    pipeline_busy_cycles_ += busy;
    max_parallel_partitions_ = std::max(max_parallel_partitions_, busy);
    const std::size_t downstream_busy = downstream_busy_worker_count();
    downstream_busy_cycles_ += downstream_busy;
    max_parallel_downstream_partitions_ =
        std::max(max_parallel_downstream_partitions_, downstream_busy);
    last_busy_workers_ = busy;
    last_downstream_busy_workers_ = downstream_busy;
    last_commit_cycle_ = context.domain_cycle;
    committed_once_ = true;
    staged_ = Action::kNone;
    staged_completed_workers_.clear();
    set_latched_commit_ready(false);
    refresh_evaluate_ready();
  }

private:
  enum class Phase { kStart, kPrepare, kRound, kDone };
  enum class Action {
    kNone,
    kStartPrepare,
    kStartSuperstep,
    kNextSuperstep,
    kFinish
  };

  static void notify_worker_done(void *owner) noexcept {
    static_cast<GraSuReGraphController *>(owner)->refresh_evaluate_ready();
  }

  void account_suspended_busy_cycles(std::uint64_t cycle) {
    if (!committed_once_) {
      return;
    }
    if (cycle <= last_commit_cycle_) {
      throw std::logic_error(
          "ReGraph controller suspended-cycle accounting moved backwards");
    }
    const std::uint64_t skipped = cycle - last_commit_cycle_ - 1;
    pipeline_busy_cycles_ += skipped * last_busy_workers_;
    downstream_busy_cycles_ += skipped * last_downstream_busy_workers_;
  }

  void refresh_evaluate_ready() noexcept {
    evaluate_ready_ = false;
    if (failed() || done()) {
      set_latched_evaluate_ready(false);
      return;
    }
    if (phase_ == Phase::kStart) {
      evaluate_ready_ = true;
    } else if (phase_ == Phase::kPrepare) {
      evaluate_ready_ = source_prepare_->done();
    } else if (phase_ == Phase::kRound) {
      evaluate_ready_ = std::any_of(
          workers_.begin(), workers_.end(),
          [](const GraSuReGraphWorker &worker) { return worker.done(); });
    }
    set_latched_evaluate_ready(evaluate_ready_);
  }

  [[nodiscard]] std::size_t busy_worker_count() const noexcept {
    return static_cast<std::size_t>(std::count_if(
        workers_.begin(), workers_.end(), [](const GraSuReGraphWorker &worker) {
          return worker.partition.has_value();
        }));
  }

  [[nodiscard]] std::size_t downstream_busy_worker_count() const noexcept {
    return static_cast<std::size_t>(std::count_if(
        workers_.begin(), workers_.end(), [](const GraSuReGraphWorker &worker) {
          return worker.partition.has_value() && worker.downstream_started;
        }));
  }

  void start_downstream(GraSuReGraphWorker &worker) {
    if (!worker.partition.has_value() || worker.downstream_started) {
      throw std::logic_error("invalid ReGraph shared-downstream dispatch");
    }
    const ReGraphPartitionPlan &plan = partitions_.at(*worker.partition);
    worker.merger->start_round();
    worker.apply->start_partition(round_, plan.destination_base,
                                  plan.destination_vertices, true);
    worker.wrapper->start_partition(round_, plan.destination_base);
    worker.downstream_started = true;
  }

  void start_waiting_downstream() {
    if (!shared_downstream_ || downstream_busy_worker_count() != 0) {
      return;
    }
    GraSuReGraphWorker *selected = nullptr;
    for (GraSuReGraphWorker &worker : workers_) {
      if (!worker.partition.has_value() || worker.downstream_started) {
        continue;
      }
      if (selected == nullptr || *worker.partition < *selected->partition) {
        selected = &worker;
      }
    }
    if (selected != nullptr) {
      start_downstream(*selected);
    }
  }

  void start_partition(GraSuReGraphWorker &worker, std::size_t partition) {
    const ReGraphPartitionPlan &plan = partitions_.at(partition);
    worker.partition = partition;
    worker.downstream_started = false;
    worker.source_hbm->start_partition(round_, partition);
    worker.reader->start_partition(
        round_, plan,
        partition == 0 && !uses_prepared_page_rank_source());
    worker.gather->start_partition(plan.destination_vertices, round_ == 1);
    if (!shared_downstream_) {
      start_downstream(worker);
    }
    ++partition_passes_;
  }

  void dispatch_available_workers() {
    for (GraSuReGraphWorker &worker : workers_) {
      if (worker.partition.has_value() || next_partition_ == partitions_.size()) {
        continue;
      }
      start_partition(worker, next_partition_++);
    }
  }

  [[nodiscard]] bool uses_prepared_page_rank_source() const noexcept {
    return iteration_context_ != nullptr;
  }

  GraphAlgorithmKind algorithm_{GraphAlgorithmKind::kWeightedSssp};
  std::size_t round_limit_{};
  bool fixed_round_limit_{};
  std::vector<ReGraphPartitionPlan> partitions_;
  std::vector<GraSuReGraphWorker> workers_;
  ReGraphIterationContext *iteration_context_{};
  ReGraphPageRankSourcePrepare *source_prepare_{};
  bool shared_downstream_{};
  Phase phase_{Phase::kStart};
  Action staged_{Action::kNone};
  std::vector<std::size_t> staged_completed_workers_;
  std::uint64_t round_{};
  std::size_t next_partition_{};
  std::size_t completed_partitions_{};
  std::size_t iteration_active_vertices_{};
  float iteration_error_{};
  float iteration_dangling_{};
  float last_iteration_error_{};
  std::uint64_t partition_passes_{};
  std::uint64_t pipeline_busy_cycles_{};
  std::size_t max_parallel_partitions_{};
  std::uint64_t downstream_busy_cycles_{};
  std::size_t max_parallel_downstream_partitions_{};
  std::size_t last_busy_workers_{};
  std::size_t last_downstream_busy_workers_{};
  std::uint64_t last_commit_cycle_{};
  bool committed_once_{};
  bool evaluate_ready_{};
  std::vector<std::size_t> frontier_out_sizes_;
  std::string failure_;
};

class GraSuReGraphK4Controller final : public Component {
public:
  GraSuReGraphK4Controller(std::string name, ClockId clock_id,
                           std::size_t round_limit, bool fixed_round_limit,
                           std::vector<ReGraphPartitionPlan> partitions,
                           std::array<ReGraphSourceHbmReader *, 4> source_hbm,
                           std::array<PmaNativeReader *, 4> readers,
                           std::array<ReGraphGather *, 4> gathers,
                           ReGraphFrontendMux &mux, ReGraphMerger &merger,
                           ReGraphApply &apply, ReGraphHbmWrapper &wrapper)
      : Component(std::move(name), clock_id), round_limit_(round_limit),
        fixed_round_limit_(fixed_round_limit),
        partitions_(std::move(partitions)), source_hbm_(source_hbm),
        readers_(readers), gathers_(gathers), mux_(mux), merger_(merger),
        apply_(apply), wrapper_(wrapper), launched_(partitions_.size()) {
    if (partitions_.empty() ||
        std::any_of(source_hbm_.begin(), source_hbm_.end(),
                    [](const auto *value) { return value == nullptr; }) ||
        std::any_of(readers_.begin(), readers_.end(),
                    [](const auto *value) { return value == nullptr; }) ||
        std::any_of(gathers_.begin(), gathers_.end(),
                    [](const auto *value) { return value == nullptr; })) {
      throw std::invalid_argument("invalid sharded-K4 ReGraph controller");
    }
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] bool failed() const noexcept { return !failure_.empty(); }
  [[nodiscard]] const std::string &failure() const noexcept { return failure_; }
  [[nodiscard]] std::uint64_t supersteps() const noexcept { return round_; }
  [[nodiscard]] std::uint64_t partition_passes() const noexcept {
    return partition_passes_;
  }
  [[nodiscard]] std::uint64_t frontend_launches() const noexcept {
    return frontend_launches_;
  }

  void evaluate(const CycleContext &) override {
    staged_round_action_ = RoundAction::kNone;
    staged_worker_launches_.fill(false);
    if (failed() || done()) {
      return;
    }
    if (phase_ == Phase::kStart) {
      staged_round_action_ = RoundAction::kStartSuperstep;
      return;
    }
    for (std::size_t worker = 0; worker < workers(); ++worker) {
      if (active_partition_[worker].has_value() && worker_done(worker) &&
          next_partition_[worker] < partitions_.size()) {
        staged_worker_launches_[worker] = true;
      }
    }
    if (!mux_.done() || !merger_.done() || !apply_.done() || !wrapper_.done()) {
      return;
    }
    if (output_partition_ + 1 < partitions_.size()) {
      if (launched_[output_partition_ + 1]) {
        staged_round_action_ = RoundAction::kNextPartition;
      }
      return;
    }
    if (fixed_round_limit_) {
      staged_round_action_ = round_ == round_limit_
                                 ? RoundAction::kFinish
                                 : RoundAction::kNextSuperstep;
    } else {
      staged_round_action_ = apply_.active_vertices() == 0
                                 ? RoundAction::kFinish
                                 : RoundAction::kNextSuperstep;
    }
  }

  void commit(const CycleContext &) override {
    if (staged_round_action_ == RoundAction::kStartSuperstep ||
        staged_round_action_ == RoundAction::kNextSuperstep) {
      if (round_ == round_limit_) {
        failure_ = "sharded-K4 ReGraph exceeded configured round limit";
        return;
      }
      ++round_;
      begin_superstep();
      phase_ = Phase::kRound;
      return;
    }
    for (std::size_t worker = 0; worker < workers(); ++worker) {
      if (staged_worker_launches_[worker]) {
        launch_worker(worker, next_partition_[worker]);
      }
    }
    if (staged_round_action_ == RoundAction::kNextPartition) {
      ++output_partition_;
      start_downstream(output_partition_);
    } else if (staged_round_action_ == RoundAction::kFinish) {
      phase_ = Phase::kDone;
    }
  }

private:
  static constexpr std::size_t workers() noexcept { return 4; }
  enum class Phase { kStart, kRound, kDone };
  enum class RoundAction {
    kNone,
    kStartSuperstep,
    kNextPartition,
    kNextSuperstep,
    kFinish,
  };

  [[nodiscard]] bool worker_done(std::size_t worker) const noexcept {
    return source_hbm_[worker]->done() && readers_[worker]->done() &&
           gathers_[worker]->done();
  }

  void begin_superstep() {
    launched_.assign(partitions_.size(), false);
    active_partition_.fill(std::nullopt);
    for (std::size_t worker = 0; worker < workers(); ++worker) {
      next_partition_[worker] = worker;
      if (worker < partitions_.size()) {
        launch_worker(worker, worker);
      }
    }
    output_partition_ = 0;
    start_downstream(output_partition_);
  }

  void launch_worker(std::size_t worker, std::size_t partition) {
    if (partition >= partitions_.size() || partition % workers() != worker ||
        (active_partition_[worker].has_value() && !worker_done(worker))) {
      throw std::logic_error("invalid sharded-K4 worker launch");
    }
    const ReGraphPartitionPlan &plan = partitions_[partition];
    source_hbm_[worker]->start_partition(round_, partition);
    readers_[worker]->start_partition(round_, plan, false);
    gathers_[worker]->start_partition(plan.destination_vertices, true);
    active_partition_[worker] = partition;
    next_partition_[worker] = partition + workers();
    launched_[partition] = true;
    ++partition_passes_;
    ++frontend_launches_;
  }

  void start_downstream(std::size_t partition) {
    if (!launched_.at(partition)) {
      throw std::logic_error("sharded-K4 mux selected an unlaunched partition");
    }
    const ReGraphPartitionPlan &plan = partitions_[partition];
    mux_.start_partition(partition);
    merger_.start_round();
    apply_.start_partition(round_, plan.destination_base,
                           plan.destination_vertices, partition == 0);
    wrapper_.start_partition(round_, plan.destination_base);
  }

  std::size_t round_limit_{};
  bool fixed_round_limit_{};
  std::vector<ReGraphPartitionPlan> partitions_;
  std::array<ReGraphSourceHbmReader *, 4> source_hbm_;
  std::array<PmaNativeReader *, 4> readers_;
  std::array<ReGraphGather *, 4> gathers_;
  ReGraphFrontendMux &mux_;
  ReGraphMerger &merger_;
  ReGraphApply &apply_;
  ReGraphHbmWrapper &wrapper_;
  std::array<std::optional<std::size_t>, 4> active_partition_;
  std::array<std::size_t, 4> next_partition_{};
  std::vector<bool> launched_;
  Phase phase_{Phase::kStart};
  RoundAction staged_round_action_{RoundAction::kNone};
  std::array<bool, 4> staged_worker_launches_{};
  std::uint64_t round_{};
  std::size_t output_partition_{};
  std::uint64_t partition_passes_{};
  std::uint64_t frontend_launches_{};
  std::string failure_;
};

class GraSuNativeReGraphController final : public Component {
public:
  GraSuNativeReGraphController(std::string name, ClockId clock_id,
                               std::size_t supersteps, std::size_t vertices,
                               ReGraphSourceHbmReader &source_hbm,
                               NativeEdgeArrayHbmReader &edge_reader,
                               NativeEdgeArrayScatter &scatter,
                               ReGraphGather &gather, ReGraphMerger &merger,
                               ReGraphApply &apply, ReGraphHbmWrapper &wrapper)
      : Component(std::move(name), clock_id), supersteps_(supersteps),
        vertices_(vertices), source_hbm_(source_hbm), edge_reader_(edge_reader),
        scatter_(scatter), gather_(gather), merger_(merger), apply_(apply),
        wrapper_(wrapper) {}

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] std::uint64_t rounds() const noexcept { return round_; }

  [[nodiscard]] bool has_dynamic_evaluate_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool has_dynamic_commit_guard() const noexcept override {
    return true;
  }
  [[nodiscard]] bool evaluate_ready() const noexcept override {
    return !done();
  }
  [[nodiscard]] bool commit_ready() const noexcept override {
    return !done() && (staged_start_ || staged_finish_);
  }

  void evaluate(const CycleContext &) override {
    staged_start_ = false;
    staged_finish_ = false;
    if (phase_ == Phase::kStart) {
      staged_start_ = true;
    } else if (phase_ == Phase::kRound && source_hbm_.done() &&
               edge_reader_.done() && scatter_.done() && gather_.done() &&
               merger_.done() && apply_.done() && wrapper_.done()) {
      if (round_ == supersteps_) {
        staged_finish_ = true;
      } else {
        staged_start_ = true;
      }
    }
  }

  void commit(const CycleContext &) override {
    if (staged_finish_) {
      phase_ = Phase::kDone;
      return;
    }
    if (!staged_start_) {
      return;
    }
    ++round_;
    source_hbm_.start_partition(round_, 0);
    edge_reader_.start_round(round_);
    scatter_.start_round(round_);
    gather_.start_partition(vertices_, round_ == 1);
    merger_.start_round();
    apply_.start_partition(round_, 0, vertices_, true);
    wrapper_.start_partition(round_, 0);
    phase_ = Phase::kRound;
  }

private:
  enum class Phase { kStart, kRound, kDone };

  std::size_t supersteps_{};
  std::size_t vertices_{};
  ReGraphSourceHbmReader &source_hbm_;
  NativeEdgeArrayHbmReader &edge_reader_;
  NativeEdgeArrayScatter &scatter_;
  ReGraphGather &gather_;
  ReGraphMerger &merger_;
  ReGraphApply &apply_;
  ReGraphHbmWrapper &wrapper_;
  Phase phase_{Phase::kStart};
  bool staged_start_{};
  bool staged_finish_{};
  std::uint64_t round_{};
};

} // namespace

class GraSuReGraphSsspSystem::Impl {
  struct Pipeline {
    std::unique_ptr<Fifo<PmaEdgeBatch>> edge_axis;
    std::unique_ptr<Fifo<ReGraphSourceCacheRequest>> source_request_axis;
    std::unique_ptr<Fifo<ReGraphSourceCacheResponse>> source_response_axis;
    std::unique_ptr<Fifo<ReGraphGatherRow>> gather_axis;
    std::unique_ptr<Fifo<ReGraphMergedBurst>> merger_axis;
    std::unique_ptr<Fifo<ReGraphAppliedBurst>> wrapper_axis;
    std::unique_ptr<FixedAxiPort> row_port;
    std::unique_ptr<FixedAxiPort> source_state_port;
    std::unique_ptr<FixedAxiPort> degree_port;
    std::array<std::unique_ptr<FixedAxiPort>, 4> pma_ports;
    std::unique_ptr<FixedAxiPort> apply_state_read_port;
    std::unique_ptr<FixedAxiPort> apply_state_write_port;
    std::unique_ptr<FixedAxiPort> source_state_primary_write_port;
    std::unique_ptr<FixedAxiPort> source_state_mirror_write_port;
    std::unique_ptr<ReGraphSourceHbmReader> source_hbm_reader;
    std::unique_ptr<PmaNativeReader> reader;
    std::unique_ptr<ReGraphGather> gather;
    std::unique_ptr<ReGraphMerger> merger;
    std::unique_ptr<ReGraphApply> apply;
    std::unique_ptr<ReGraphHbmWrapper> wrapper;
  };

public:
  struct K4ControllerInputs {
    std::array<ReGraphSourceHbmReader *, 4> source_hbm{};
    std::array<PmaNativeReader *, 4> readers{};
    std::array<ReGraphGather *, 4> gathers{};
  };

  Impl(Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
       GraSuPartitionedPmaLayout layout, GraphAlgorithmPolicy policy,
       std::vector<std::uint32_t> out_degrees, std::size_t fixed_rounds,
       GraSuReGraphConfig config,
       std::optional<AlgorithmInitialState> initial_state = std::nullopt)
      : scheduler_(scheduler), clock_id_(clock_id), backend_(backend),
        layout_(std::move(layout)), source_(policy.config().source),
        config_(config), policy_(std::move(policy)),
        out_degrees_(std::move(out_degrees)),
        initial_state_(std::move(initial_state)), fixed_rounds_(fixed_rounds),
        start_cycle_(scheduler_.clock(clock_id_).completed_cycles) {
    address_plan_ = make_grasu_partition_address_plan(
        layout_, config_.packed_partition_addresses, config_.row_offset_base,
        0, config_.pma_base, config_.partition_address_stride,
        config_.partition_address_arena_base,
        config_.partition_address_alignment);
    if (config_.packed_partition_addresses) {
      const std::uint64_t alignment = config_.partition_address_alignment;
      const auto align_up = [alignment](std::uint64_t value) {
        const std::uint64_t remainder = value % alignment;
        if (remainder == 0) {
          return value;
        }
        if (alignment - remainder >
            std::numeric_limits<std::uint64_t>::max() - value) {
          throw std::overflow_error("ReGraph packed source-state overflow");
        }
        return value + alignment - remainder;
      };
      config_.source_state_base = align_up(address_plan_.arena_end);
      const std::uint64_t required_stride = align_up(
          layout_.partitions.size() * config_.partition_vertices *
          state_bytes_per_vertex(policy_));
      config_.source_state_buffer_stride =
          std::max(config_.source_state_buffer_stride, required_stride);
    }
    validate_config();
    construct_partition_plans();
    construct_ports();
    if (policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
        policy_.config().kind == GraphAlgorithmKind::kResidualPageRank) {
      iteration_context_ =
          std::make_unique<ReGraphIterationContext>(policy_);
    }
    initialize_sharded_graph_payloads();
    initialize_state();
    construct_components();
  }

  void register_components() {
    if (registered_) {
      throw std::logic_error("GraSU-ReGraph system registered more than once");
    }
    scheduler_.add_component(gather_axis_);
    scheduler_.add_component(merger_axis_);
    scheduler_.add_component(wrapper_axis_);
    if (config_.frontend_count == 1) {
      scheduler_.add_component(edge_axis_);
      scheduler_.add_component(source_request_axis_);
      scheduler_.add_component(source_response_axis_);
      row_port_->register_components(scheduler_);
      source_state_port_->register_components(scheduler_);
      if (degree_port_ != nullptr) {
        degree_port_->register_components(scheduler_);
      }
      for (auto &port : pma_ports_) {
        port->register_components(scheduler_);
      }
      scheduler_.add_component(*source_hbm_reader_);
      scheduler_.add_component(*reader_);
      scheduler_.add_component(*gather_);
    } else {
      for (std::size_t worker = 0; worker < config_.frontend_count; ++worker) {
        scheduler_.add_component(*k4_edge_axes_[worker]);
        scheduler_.add_component(*k4_source_request_axes_[worker]);
        scheduler_.add_component(*k4_source_response_axes_[worker]);
        scheduler_.add_component(*k4_gather_axes_[worker]);
        k4_row_ports_[worker]->register_components(scheduler_);
        k4_source_state_ports_[worker]->register_components(scheduler_);
        for (auto &port : k4_pma_ports_[worker]) {
          port->register_components(scheduler_);
        }
        scheduler_.add_component(*k4_source_hbm_readers_[worker]);
        scheduler_.add_component(*k4_readers_[worker]);
        scheduler_.add_component(*k4_gathers_[worker]);
      }
      scheduler_.add_component(*frontend_mux_);
    }
    apply_state_read_port_->register_components(scheduler_);
    apply_state_write_port_->register_components(scheduler_);
    source_state_primary_write_port_->register_components(scheduler_);
    source_state_mirror_write_port_->register_components(scheduler_);
    scheduler_.add_component(*merger_);
    scheduler_.add_component(*apply_);
    scheduler_.add_component(*wrapper_);
    if (config_.frontend_count == 1) {
      scheduler_.add_component(*controller_);
    } else {
      scheduler_.add_component(*k4_controller_);
    }
    registered_ = true;
  }

  [[nodiscard]] bool done() const noexcept {
    const bool controller_done = config_.frontend_count == 1
                                     ? controller_->done()
                                     : k4_controller_->done();
    return registered_ && controller_done && all_ports_idle();
  }
  [[nodiscard]] bool failed() const noexcept {
    return config_.frontend_count == 1 ? controller_->failed()
                                       : k4_controller_->failed();
  }
  [[nodiscard]] const std::string &failure() const noexcept {
    return config_.frontend_count == 1 ? controller_->failure()
                                       : k4_controller_->failure();
  }
  [[nodiscard]] std::vector<std::size_t> frontier_out_sizes() const {
    return controller_->frontier_out_sizes();
  }

  [[nodiscard]] GraSuReGraphCounters counters() const noexcept {
    GraSuReGraphCounters result;
    const auto account_axi_port = [&result](const FixedAxiPort &port) {
      result.axi_request_fifo_stalls +=
          port.requests().stats().push_stalls;
      result.axi_backend_submit_stalls +=
          port.master().stats().backend_submit_stalls;
      result.axi_beats_issued += port.master().stats().beats_issued;
      result.axi_beats_completed += port.master().stats().beats_completed;
    };
    const auto sum = [this](auto value) {
      std::uint64_t total = 0;
      for (const Pipeline &pipeline : pipelines_) {
        total += value(pipeline);
      }
      return total;
    };
    const auto maximum = [this](auto value) {
      std::size_t result = 0;
      for (const Pipeline &pipeline : pipelines_) {
        result = std::max(result, value(pipeline));
      }
      return result;
    };
    result.state_bytes_per_vertex = state_bytes_per_vertex(policy_);
    result.destination_partitions = layout_.partitions.size();
    result.frontend_count = config_.frontend_count;
    const auto add_frontend =
        [&](const PmaNativeReader &reader,
            const ReGraphSourceHbmReader &source_hbm,
            const ReGraphGather &gather,
            const Fifo<ReGraphSourceCacheRequest> &requests,
            const Fifo<ReGraphSourceCacheResponse> &responses) {
          result.row_reads += reader.row_reads();
          result.source_state_reads += source_hbm.requests();
          result.source_cache_requests += reader.source_requests();
          result.source_cache_request_markers +=
              reader.source_request_markers();
          result.source_cache_lines += reader.source_lines();
          result.source_cache_lane_writes += reader.source_lane_writes();
          result.source_cache_response_markers +=
              reader.source_response_markers();
          result.source_cache_wait_cycles += reader.source_wait_cycles();
          result.source_cache_output_stall_cycles +=
              source_hbm.output_stall_cycles();
          result.source_cache_request_fifo_max_occupancy =
              std::max(result.source_cache_request_fifo_max_occupancy,
                       requests.stats().max_occupancy);
          result.source_cache_response_fifo_max_occupancy =
              std::max(result.source_cache_response_fifo_max_occupancy,
                       responses.stats().max_occupancy);
          result.degree_reads += reader.degree_reads();
          result.source_map_cycles += reader.source_map_cycles();
          result.pma_segment_reads += reader.segment_reads();
          result.edge_batches_scanned += gather.batches_scanned();
          result.pma_slots_scanned += gather.slots_scanned();
          result.live_edges_scanned += gather.live_edges();
          result.active_edges_mapped += gather.active_edges();
          result.gather_reset_cycles += gather.reset_cycles();
          result.gather_merge_cycles += gather.merge_cycles();
          result.gather_pipeline_drain_cycles += gather.pipeline_drain_cycles();
          result.gather_output_stall_cycles += gather.output_stall_cycles();
          result.gather_bank_conflict_cycles += gather.conflict_cycles();
          result.gather_bank_updates += gather.bank_updates();
          result.gather_bypass_hits += gather.bypass_hits();
          result.gather_bypass_misses += gather.bypass_misses();
          result.gather_cross_bank_reductions += gather.cross_bank_reductions();
          result.gather_rows_emitted += gather.rows_emitted();
        };
    if (config_.frontend_count == 1) {
      result.supersteps = controller_->supersteps();
      result.partition_passes = controller_->partition_passes();
      result.frontend_launches = result.partition_passes;
      add_frontend(*reader_, *source_hbm_reader_, *gather_,
                   source_request_axis_, source_response_axis_);
    } else {
      result.supersteps = k4_controller_->supersteps();
      result.partition_passes = k4_controller_->partition_passes();
      result.frontend_launches = k4_controller_->frontend_launches();
      result.frontend_mux_rows = frontend_mux_->rows_forwarded();
      result.frontend_mux_input_wait_cycles =
          frontend_mux_->input_wait_cycles();
      result.frontend_mux_output_stall_cycles =
          frontend_mux_->output_stall_cycles();
      for (std::size_t worker = 0; worker < config_.frontend_count; ++worker) {
        add_frontend(*k4_readers_[worker], *k4_source_hbm_readers_[worker],
                     *k4_gathers_[worker], *k4_source_request_axes_[worker],
                     *k4_source_response_axes_[worker]);
      }
    }
    result.source_state_writes = wrapper_->source_writes();
    result.merger_rows_consumed = merger_->rows_consumed();
    result.merger_bursts_emitted = merger_->bursts_emitted();
    result.merger_output_stall_cycles = merger_->output_stall_cycles();
    result.apply_state_reads = apply_->reads();
    result.apply_state_writes = apply_->writes();
    result.apply_input_bursts = apply_->input_bursts();
    result.apply_output_stall_cycles = apply_->output_stall_cycles();
    result.apply_read_window_stalls = apply_->read_window_stalls();
    result.apply_pipeline_capacity_stalls = apply_->pipeline_capacity_stalls();
    result.apply_write_window_stalls = apply_->write_window_stalls();
    result.apply_max_reads_inflight = apply_->max_reads_inflight();
    result.apply_max_pipeline_occupancy = apply_->max_pipeline_occupancy();
    result.apply_max_writes_inflight = apply_->max_writes_inflight();
    result.hbm_wrapper_input_bursts = wrapper_->input_bursts();
    result.hbm_wrapper_pipeline_capacity_stalls =
        wrapper_->pipeline_capacity_stalls();
    result.hbm_wrapper_write_window_stalls = wrapper_->write_window_stalls();
    result.hbm_wrapper_max_pipeline_occupancy =
        wrapper_->max_pipeline_occupancy();
    result.hbm_wrapper_max_writes_inflight = wrapper_->max_writes_inflight();
    result.gather_merger_fifo_max_occupancy =
        gather_axis_.stats().max_occupancy;
    result.merger_apply_fifo_max_occupancy = merger_axis_.stats().max_occupancy;
    result.apply_wrapper_fifo_max_occupancy =
        wrapper_axis_.stats().max_occupancy;
    result.activated_vertices = apply_->total_activated();
    result.row_read_bytes = result.row_reads * 8;
    result.source_state_read_bytes = result.source_state_reads *
                                     config_.source_buffer_vertices *
                                     state_bytes_per_vertex(policy_);
    result.source_state_write_bytes = result.source_state_writes *
                                      kStateWordsPerBurst *
                                      state_bytes_per_vertex(policy_);
    result.degree_read_bytes = result.degree_reads * 4;
    result.pma_read_bytes = result.pma_segment_reads * kGraSuSegmentBytes;
    result.apply_read_bytes = result.apply_state_reads * kStateWordsPerBurst *
                              state_bytes_per_vertex(policy_);
    result.apply_write_bytes = result.apply_state_writes * kStateWordsPerBurst *
                               state_bytes_per_vertex(policy_);
    result.axi_backend_submit_stalls =
        apply_state_read_port_->master().stats().backend_submit_stalls +
        apply_state_write_port_->master().stats().backend_submit_stalls +
        source_state_primary_write_port_->master()
            .stats()
            .backend_submit_stalls +
        source_state_mirror_write_port_->master().stats().backend_submit_stalls;
    if (config_.frontend_count == 1) {
      result.axi_backend_submit_stalls +=
          row_port_->master().stats().backend_submit_stalls +
          source_state_port_->master().stats().backend_submit_stalls;
      if (degree_port_ != nullptr) {
        result.axi_backend_submit_stalls +=
            degree_port_->master().stats().backend_submit_stalls;
      }
      for (const auto &port : pma_ports_) {
        result.axi_backend_submit_stalls +=
            port->master().stats().backend_submit_stalls;
      }
      result.axis_push_stalls = source_request_axis_.stats().push_stalls +
                                source_response_axis_.stats().push_stalls +
                                edge_axis_.stats().push_stalls;
    } else {
      for (std::size_t worker = 0; worker < config_.frontend_count; ++worker) {
        result.axi_backend_submit_stalls +=
            k4_row_ports_[worker]->master().stats().backend_submit_stalls +
            k4_source_state_ports_[worker]
                ->master()
                .stats()
                .backend_submit_stalls;
        for (const auto &port : k4_pma_ports_[worker]) {
          result.axi_backend_submit_stalls +=
              port->master().stats().backend_submit_stalls;
        }
        result.axis_push_stalls +=
            k4_source_request_axes_[worker]->stats().push_stalls +
            k4_source_response_axes_[worker]->stats().push_stalls +
            k4_edge_axes_[worker]->stats().push_stalls +
            k4_gather_axes_[worker]->stats().push_stalls;
      }
    }
    result.axis_push_stalls += gather_axis_.stats().push_stalls +
                               merger_axis_.stats().push_stalls +
                               wrapper_axis_.stats().push_stalls;
    result.start_cycle = start_cycle_;
    result.end_cycle = scheduler_.clock(clock_id_).completed_cycles;
    result.last_iteration_error = controller_->iteration_error();
    return result;
  }

  [[nodiscard]] std::vector<std::uint32_t> distances() const {
    if (policy_.config().kind != GraphAlgorithmKind::kWeightedSssp) {
      throw std::logic_error("distance view requires weighted SSSP policy");
    }
    return state_words();
  }

  [[nodiscard]] std::vector<std::uint32_t> state_words() const {
    const auto bytes = backend_.inspect_payload(
        config_.vertex_state_channel, config_.vertex_state_base,
        layout_.vertices * state_bytes_per_vertex(policy_));
    std::vector<std::uint32_t> result(layout_.vertices);
    for (std::size_t vertex = 0; vertex < result.size(); ++vertex) {
      result[vertex] = decode_policy_value(
          policy_, decode_u32(bytes, vertex * state_bytes_per_vertex(policy_)));
    }
    return result;
  }

  [[nodiscard]] std::vector<std::uint32_t> auxiliary_state_words() const {
    if (!uses_auxiliary_state(policy_)) {
      throw std::logic_error(
          "auxiliary state view requires residual PageRank policy");
    }
    const auto bytes = backend_.inspect_payload(
        config_.vertex_state_channel, config_.vertex_state_base,
        layout_.vertices * state_bytes_per_vertex(policy_));
    std::vector<std::uint32_t> result(layout_.vertices);
    for (std::size_t vertex = 0; vertex < result.size(); ++vertex) {
      result[vertex] =
          decode_u32(bytes, vertex * state_bytes_per_vertex(policy_) + 4);
    }
    return result;
  }

private:
  void validate_config() const {
    const bool full_pagerank =
        policy_.config().kind == GraphAlgorithmKind::kFullPageRank;
    const bool residual_pagerank =
        policy_.config().kind == GraphAlgorithmKind::kResidualPageRank;
    const bool pagerank = full_pagerank || residual_pagerank;
    if (layout_.vertices == 0 || source_ >= layout_.vertices ||
        policy_.config().vertices != layout_.vertices ||
        (policy_.config().kind != GraphAlgorithmKind::kWeightedSssp &&
         !pagerank) ||
        (pagerank &&
         (out_degrees_.size() != layout_.vertices || fixed_rounds_ == 0)) ||
        (!pagerank && !out_degrees_.empty()) || config_.memory_channels < 4 ||
        layout_.partitions.empty() ||
        layout_.partitions.size() !=
            (layout_.vertices + config_.partition_vertices - 1) /
                config_.partition_vertices ||
        layout_.partition_vertices != config_.partition_vertices ||
        config_.partition_vertices % kStateWordsPerBurst != 0 ||
        config_.source_state_buffer_stride <
            layout_.partitions.size() * config_.partition_vertices *
                state_bytes_per_vertex(policy_) ||
        config_.source_state_buffer_stride % 4096 != 0 ||
        config_.source_buffer_vertices == 0 ||
        config_.source_buffer_vertices % kStateWordsPerBurst != 0 ||
        config_.source_cache_request_fifo_depth == 0 ||
        config_.source_cache_response_fifo_depth == 0 ||
        config_.edge_lanes == 0 || config_.edge_lanes > 8 ||
        kGraSuSegmentSlots % config_.edge_lanes != 0 ||
        config_.gather_banks != config_.edge_lanes ||
        config_.gather_bypass_distance == 0 ||
        config_.gather_pipeline_latency <= config_.gather_bypass_distance ||
        config_.gather_vertices_per_reset_cycle == 0 ||
        config_.gather_vertices_per_merge_cycle != 2 ||
        config_.axis_fifo_depth == 0 || config_.gather_merger_fifo_depth == 0 ||
        config_.merger_apply_fifo_depth == 0 ||
        config_.apply_wrapper_fifo_depth == 0 ||
        config_.reader_buffer_batches <
            kGraSuSegmentSlots / config_.edge_lanes ||
        config_.max_pending_requests == 0 ||
        config_.max_outstanding_bursts == 0 ||
        config_.response_beats_per_cycle == 0 ||
        config_.apply_request_window == 0 ||
        config_.apply_pipeline_latency == 0 ||
        config_.apply_pipeline_capacity == 0 ||
        config_.hbm_wrapper_pipeline_latency == 0 ||
        config_.hbm_wrapper_pipeline_capacity == 0 ||
        (config_.frontend_count != 1 && config_.frontend_count != 4) ||
        config_.frontend_mux_fifo_depth == 0 ||
        (config_.frontend_count == 4 &&
         (!config_.sharded_runtime_placement || pagerank)) ||
        (config_.sharded_runtime_placement &&
         (config_.memory_channels < kGraSuReGraphU55cGraphChannels ||
          config_.runtime_channel_capacity_bytes == 0)) ||
        config_.max_supersteps == 0 || config_.partition_address_stride == 0 ||
        config_.row_channel >= config_.memory_channels ||
        config_.source_state_channel >= config_.memory_channels ||
        config_.source_state_mirror_channel >= config_.memory_channels ||
        config_.vertex_state_channel >= config_.memory_channels ||
        (pagerank && config_.degree_channel >= config_.memory_channels)) {
      throw std::invalid_argument("invalid GraSU-ReGraph configuration");
    }
    require(config_.memory_channels >= 4, "fewer than four HBM channels");
    require(config_.compute_pipelines != 0, "zero compute pipelines");
    require(!layout_.partitions.empty(), "empty PMA partition list");
    require(config_.partition_vertices != 0, "zero partition vertices");
    require(layout_.partitions.size() ==
                (layout_.vertices + config_.partition_vertices - 1) /
                    config_.partition_vertices,
            "PMA partition count mismatch");
    require(layout_.partition_vertices == config_.partition_vertices,
            "PMA partition span mismatch");
    require(config_.partition_vertices % kStateWordsPerBurst == 0,
            "partition span is not burst aligned");
    require(config_.source_state_buffer_stride >=
                layout_.partitions.size() * config_.partition_vertices *
                    state_bytes_per_vertex(policy_),
            "source-state double-buffer stride is too small");
    require(config_.source_state_buffer_stride % 4096 == 0,
            "source-state stride is not 4 KiB aligned");
    require(config_.source_buffer_vertices != 0,
            "zero source-cache capacity");
    require(config_.source_buffer_vertices % kStateWordsPerBurst == 0,
            "source-cache capacity is not burst aligned");
    require(config_.source_cache_request_fifo_depth != 0,
            "zero source request FIFO depth");
    require(config_.source_cache_response_fifo_depth != 0,
            "zero source response FIFO depth");
    require(config_.edge_lanes != 0 && config_.edge_lanes <= 8,
            "invalid edge lane count");
    require(kGraSuSegmentSlots % config_.edge_lanes == 0,
            "edge lanes do not divide PMA segment slots");
    require(config_.gather_banks == config_.edge_lanes,
            "gather banks differ from edge lanes");
    require(config_.gather_bypass_distance != 0,
            "zero gather bypass distance");
    require(config_.gather_pipeline_latency > config_.gather_bypass_distance,
            "gather latency does not exceed bypass distance");
    require(config_.gather_vertices_per_reset_cycle != 0,
            "zero gather reset width");
    require(config_.gather_vertices_per_merge_cycle == 2,
            "unsupported gather merge width");
    require(config_.axis_fifo_depth != 0, "zero AXIS FIFO depth");
    require(config_.gather_merger_fifo_depth != 0,
            "zero gather-merger FIFO depth");
    require(config_.merger_apply_fifo_depth != 0,
            "zero merger-apply FIFO depth");
    require(config_.apply_wrapper_fifo_depth != 0,
            "zero apply-wrapper FIFO depth");
    require(config_.reader_buffer_batches >=
                kGraSuSegmentSlots / config_.edge_lanes,
            "reader buffer cannot hold one PMA segment");
    require(config_.max_pending_requests != 0,
            "zero pending-request capacity");
    require(config_.max_outstanding_bursts != 0,
            "zero outstanding-burst capacity");
    require(config_.response_beats_per_cycle != 0,
            "zero response bandwidth");
    require(config_.apply_request_window != 0, "zero apply request window");
    require(config_.apply_pipeline_latency != 0,
            "zero apply pipeline latency");
    require(config_.apply_pipeline_capacity != 0,
            "zero apply pipeline capacity");
    require(config_.hbm_wrapper_pipeline_latency != 0,
            "zero HBM-wrapper latency");
    require(config_.hbm_wrapper_pipeline_capacity != 0,
            "zero HBM-wrapper capacity");
    require(config_.max_supersteps != 0, "zero maximum supersteps");
    require(config_.partition_address_stride != 0,
            "zero partition address stride");
    require(config_.partition_address_alignment != 0,
            "zero partition address alignment");
    require(config_.row_channel < config_.memory_channels,
            "row channel outside HBM");
    require(config_.source_state_channel < config_.memory_channels,
            "source-state channel outside HBM");
    require(config_.source_state_mirror_channel < config_.memory_channels,
            "source-state mirror channel outside HBM");
    require(config_.vertex_state_channel < config_.memory_channels,
            "vertex-state channel outside HBM");
    require(!pagerank || config_.degree_channel < config_.memory_channels,
            "degree channel outside HBM");
    for (std::size_t partition = 0; partition < layout_.partitions.size();
         ++partition) {
      const GraSuPmaLayout &part = layout_.partitions[partition];
      const std::size_t expected_base = partition * config_.partition_vertices;
      const std::size_t expected_vertices = std::min(
          config_.partition_vertices, layout_.vertices - expected_base);
      if (part.vertices != layout_.vertices ||
          part.destination_base != expected_base ||
          part.destination_vertices != expected_vertices) {
        throw std::invalid_argument(
            "GraSU-ReGraph PMA partitions are not contiguous");
      }
    }
  }

  void construct_partition_plans() {
    partition_plans_.reserve(layout_.partitions.size());
    if (config_.sharded_runtime_placement) {
      runtime_plan_ = build_grasu_regraph_runtime_plan(
          layout_, std::vector<std::size_t>(layout_.partitions.size(), 0),
          config_.cache_segments_per_half, kGraSuReGraphU55cGraphChannels,
          config_.runtime_channel_capacity_bytes);
      for (std::size_t partition = 0; partition < layout_.partitions.size();
           ++partition) {
        const GraSuPmaLayout &part = layout_.partitions[partition];
        const auto row =
            find_grasu_regraph_runtime_region(*runtime_plan_, partition, "row");
        ReGraphPartitionPlan plan{
            .destination_base = part.destination_base,
            .destination_vertices = part.destination_vertices,
            .row_base = row.channel_offset_bytes,
            .row_channel = row.channel,
        };
        for (std::size_t lane = 0; lane < 4; ++lane) {
          const auto pma = find_grasu_regraph_runtime_region(
              *runtime_plan_, partition, "pma" + std::to_string(lane));
          plan.pma_base[lane] = pma.channel_offset_bytes;
          plan.pma_channel[lane] = pma.channel;
        }
        partition_plans_.push_back(plan);
      }
      return;
    }
    for (std::size_t partition = 0; partition < layout_.partitions.size();
         ++partition) {
      const std::uint64_t offset = partition * config_.partition_address_stride;
      if (offset > std::numeric_limits<std::uint64_t>::max() -
                       std::max(config_.row_offset_base, config_.pma_base)) {
        throw std::overflow_error("GraSU-ReGraph partition address overflow");
      }
      const GraSuPmaLayout &part = layout_.partitions[partition];
      partition_plans_.push_back(ReGraphPartitionPlan{
          .destination_base = part.destination_base,
          .destination_vertices = part.destination_vertices,
          .row_base = address_plan_.row_bases.at(partition),
          .row_channel = config_.row_channel,
          .pma_base = {config_.pma_base + offset, config_.pma_base + offset,
                       config_.pma_base + offset, config_.pma_base + offset},
          .pma_channel = {0, 1, 2, 3},
      });
    }
  }

  void initialize_sharded_graph_payloads() {
    if (!runtime_plan_.has_value()) {
      return;
    }
    for (std::size_t partition = 0; partition < layout_.partitions.size();
         ++partition) {
      const GraSuPmaLayout &part = layout_.partitions[partition];
      const ReGraphPartitionPlan &plan = partition_plans_[partition];
      std::vector<std::uint8_t> rows;
      rows.reserve(part.row_slot_bounds.size() * sizeof(std::uint64_t));
      for (const auto &[begin, end] : part.row_slot_bounds) {
        const std::uint64_t packed =
            (static_cast<std::uint64_t>(begin) << 32) | end;
        for (std::size_t byte = 0; byte < sizeof(packed); ++byte) {
          rows.push_back(static_cast<std::uint8_t>(packed >> (byte * 8)));
        }
      }
      backend_.initialize_payload(plan.row_channel, plan.row_base, rows);

      for (std::size_t segment = 0; segment < part.segments.size(); ++segment) {
        const std::size_t local = segment >> 1;
        const std::size_t parity = segment & 1U;
        const std::size_t lane = local < config_.cache_segments_per_half
                                     ? parity * 2
                                     : parity * 2 + 1;
        std::vector<std::uint8_t> bytes;
        bytes.reserve(kGraSuSegmentBytes);
        for (const std::uint32_t word : part.segments[segment]) {
          for (std::size_t byte = 0; byte < sizeof(word); ++byte) {
            bytes.push_back(static_cast<std::uint8_t>(word >> (byte * 8)));
          }
        }
        backend_.initialize_payload(
            plan.pma_channel[lane],
            plan.pma_base[lane] + local * kGraSuSegmentBytes, bytes);
      }
    }
  }

  std::unique_ptr<FixedAxiPort>
  make_port(const std::string &name, std::size_t channel, std::uint32_t width) {
    return std::make_unique<FixedAxiPort>(
        name, clock_id_,
        port_config(config_, channel, next_initiator_++, width), backend_);
  }

  std::unique_ptr<FixedAxiPort> make_source_stream_port(const std::string &name,
                                                        std::size_t channel) {
    FixedAxiPortConfig source =
        port_config(config_, channel, next_initiator_++, 64);
    source.stream_read_beats = true;
    source.read_beat_fifo_depth = config_.source_cache_response_fifo_depth;
    source.read_reorder_capacity = config_.max_outstanding_bursts * 16;
    return std::make_unique<FixedAxiPort>(name, clock_id_, source, backend_);
  }

  void construct_ports() {
    if (config_.frontend_count == 1) {
      row_port_ = make_port("grasu-regraph-row", config_.row_channel, 8);
      source_state_port_ = make_source_stream_port(
          "grasu-regraph-source-state", config_.source_state_channel);
      if (policy_.config().kind != GraphAlgorithmKind::kWeightedSssp) {
        degree_port_ =
            make_port("grasu-regraph-degree", config_.degree_channel, 4);
      }
      for (std::size_t channel = 0; channel < pma_ports_.size(); ++channel) {
        pma_ports_[channel] = make_port(
            "grasu-regraph-pma" + std::to_string(channel), channel, 64);
      }
    } else {
      for (std::size_t worker = 0; worker < config_.frontend_count; ++worker) {
        k4_row_ports_[worker] =
            make_port("grasu-regraph-k4-row" + std::to_string(worker), 0, 8);
        const std::size_t source_channel =
            worker % 2 == 0 ? config_.source_state_channel
                            : config_.source_state_mirror_channel;
        k4_source_state_ports_[worker] = make_source_stream_port(
            "grasu-regraph-k4-source" + std::to_string(worker), source_channel);
        for (std::size_t lane = 0; lane < 4; ++lane) {
          k4_pma_ports_[worker][lane] =
              make_port("grasu-regraph-k4-pma" + std::to_string(worker) + "-" +
                            std::to_string(lane),
                        lane, 64);
        }
      }
    }
  }

  void initialize_state() {
    const std::size_t bytes_per_vertex = state_bytes_per_vertex(policy_);
    const std::size_t padded_vertices =
        layout_.partitions.size() * config_.partition_vertices;
    std::vector<std::uint8_t> bytes(padded_vertices * bytes_per_vertex);
    for (std::size_t vertex = 0; vertex < padded_vertices; ++vertex) {
      std::uint32_t encoded =
          policy_.config().kind == GraphAlgorithmKind::kWeightedSssp ||
                  policy_.config().kind ==
                      GraphAlgorithmKind::kConnectedComponents
              ? kReGraphInfinity
              : GraphAlgorithmPolicy::float_to_word(0.0F);
      if (vertex < layout_.vertices) {
        const AlgorithmVertexState state =
            initial_state_.has_value()
                ? AlgorithmVertexState{
                      .primary = initial_state_->primary[vertex],
                      .auxiliary = uses_auxiliary_state(policy_)
                                       ? initial_state_->auxiliary[vertex]
                                       : 0U,
                  }
                : policy_.initial_state(static_cast<std::uint32_t>(vertex));
        const bool active =
            initial_state_.has_value()
                ? initial_active.contains(static_cast<std::uint32_t>(vertex))
                : policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
                      policy_.config().kind ==
                          GraphAlgorithmKind::kConnectedComponents ||
                      vertex == source_;
        encoded = encode_policy_value(policy_, state.primary, active);
        if (uses_auxiliary_state(policy_)) {
          for (std::size_t byte = 0; byte < 4; ++byte) {
            bytes[vertex * bytes_per_vertex + 4 + byte] =
                static_cast<std::uint8_t>(state.auxiliary >> (byte * 8));
          }
        }
      }
      for (std::size_t byte = 0; byte < 4; ++byte) {
        bytes[vertex * bytes_per_vertex + byte] =
            static_cast<std::uint8_t>(encoded >> (byte * 8));
      }
    }
    backend_.initialize_payload(config_.vertex_state_channel,
                                config_.vertex_state_base, bytes);
    std::vector<std::uint8_t> source_bytes(padded_vertices * 4);
    if (iteration_context_ == nullptr) {
      for (std::size_t vertex = 0; vertex < padded_vertices; ++vertex) {
        std::copy_n(bytes.begin() +
                        static_cast<std::ptrdiff_t>(vertex * bytes_per_vertex),
                    4, source_bytes.begin() +
                           static_cast<std::ptrdiff_t>(vertex * 4));
      }
    }
    backend_.initialize_payload(config_.source_state_channel,
                                config_.source_state_base, source_bytes);
    backend_.initialize_payload(config_.source_state_mirror_channel,
                                config_.source_state_base, source_bytes);
    if ((policy_.config().kind == GraphAlgorithmKind::kFullPageRank ||
         policy_.config().kind == GraphAlgorithmKind::kResidualPageRank) &&
        config_.initialize_degree_payload) {
      std::vector<std::uint8_t> degree_bytes(layout_.vertices * 4);
      for (std::size_t vertex = 0; vertex < out_degrees_.size(); ++vertex) {
        for (std::size_t byte = 0; byte < 4; ++byte) {
          degree_bytes[vertex * 4 + byte] =
              static_cast<std::uint8_t>(out_degrees_[vertex] >> (byte * 8));
        }
      }
      backend_.initialize_payload(config_.degree_channel, config_.degree_base,
                                  degree_bytes);
    }
  }

  void construct_components() {
    ReGraphReaderContext *apply_context = nullptr;
    if (config_.frontend_count == 1) {
      std::array<FixedAxiPort *, 4> pma{};
      for (std::size_t index = 0; index < pma.size(); ++index) {
        pma[index] = pma_ports_[index].get();
      }
      source_hbm_reader_ = std::make_unique<ReGraphSourceHbmReader>(
          "grasu-regraph-source-hbm-reader", clock_id_, config_, policy_,
          source_request_axis_, source_response_axis_, *source_state_port_);
      reader_ = std::make_unique<PmaNativeReader>(
          "grasu-regraph-reader", clock_id_, layout_.vertices, policy_, config_,
          PmaNativeReader::Ports{
              .rows = row_port_.get(),
              .degree = degree_port_.get(),
              .pma = pma,
              .output = &edge_axis_,
              .source_requests = &source_request_axis_,
              .source_responses = &source_response_axis_,
          });
      gather_ = std::make_unique<ReGraphGather>(
          "grasu-regraph-gather", clock_id_, layout_.vertices, policy_, config_,
          edge_axis_, gather_axis_, *reader_);
      apply_context = reader_.get();
    } else {
      std::array<Fifo<ReGraphGatherRow> *, 4> mux_inputs{};
      std::array<ReGraphSourceHbmReader *, 4> source_readers{};
      std::array<PmaNativeReader *, 4> readers{};
      std::array<ReGraphGather *, 4> gathers{};
      for (std::size_t worker = 0; worker < config_.frontend_count; ++worker) {
        const std::string suffix = std::to_string(worker);
        k4_edge_axes_[worker] = std::make_unique<Fifo<PmaEdgeBatch>>(
            "grasu-regraph-k4-edge-" + suffix, clock_id_,
            config_.axis_fifo_depth);
        k4_source_request_axes_[worker] =
            std::make_unique<Fifo<ReGraphSourceCacheRequest>>(
                "grasu-regraph-k4-source-request-" + suffix, clock_id_,
                config_.source_cache_request_fifo_depth);
        k4_source_response_axes_[worker] =
            std::make_unique<Fifo<ReGraphSourceCacheResponse>>(
                "grasu-regraph-k4-source-response-" + suffix, clock_id_,
                config_.source_cache_response_fifo_depth);
        k4_gather_axes_[worker] = std::make_unique<Fifo<ReGraphGatherRow>>(
            "grasu-regraph-k4-gather-" + suffix, clock_id_,
            config_.frontend_mux_fifo_depth);
        std::array<FixedAxiPort *, 4> pma{};
        for (std::size_t lane = 0; lane < pma.size(); ++lane) {
          pma[lane] = k4_pma_ports_[worker][lane].get();
        }
        k4_source_hbm_readers_[worker] =
            std::make_unique<ReGraphSourceHbmReader>(
                "grasu-regraph-k4-source-reader-" + suffix, clock_id_, config_,
                policy_, *k4_source_request_axes_[worker],
                *k4_source_response_axes_[worker],
                *k4_source_state_ports_[worker]);
        k4_readers_[worker] = std::make_unique<PmaNativeReader>(
            "grasu-regraph-k4-reader-" + suffix, clock_id_, layout_.vertices,
            policy_, config_,
            PmaNativeReader::Ports{
                .rows = k4_row_ports_[worker].get(),
                .degree = nullptr,
                .pma = pma,
                .output = k4_edge_axes_[worker].get(),
                .source_requests = k4_source_request_axes_[worker].get(),
                .source_responses = k4_source_response_axes_[worker].get(),
            });
        k4_gathers_[worker] = std::make_unique<ReGraphGather>(
            "grasu-regraph-k4-gather-unit-" + suffix, clock_id_,
            layout_.vertices, policy_, config_, *k4_edge_axes_[worker],
            *k4_gather_axes_[worker], *k4_readers_[worker]);
        mux_inputs[worker] = k4_gather_axes_[worker].get();
        source_readers[worker] = k4_source_hbm_readers_[worker].get();
        readers[worker] = k4_readers_[worker].get();
        gathers[worker] = k4_gathers_[worker].get();
      }
      frontend_mux_ = std::make_unique<ReGraphFrontendMux>(
          "grasu-regraph-k4-frontend-mux", clock_id_, config_, mux_inputs,
          gather_axis_);
      apply_context = k4_readers_[0].get();
      k4_controller_inputs_ = K4ControllerInputs{
          .source_hbm = source_readers, .readers = readers, .gathers = gathers};
    }
    merger_ = std::make_unique<ReGraphMerger>(
        "grasu-regraph-merger", clock_id_, config_, gather_axis_, merger_axis_);
    apply_ = std::make_unique<ReGraphApply>(
        "grasu-regraph-apply", clock_id_, layout_.vertices, policy_, config_,
        merger_axis_, wrapper_axis_, *apply_state_read_port_,
        *apply_state_write_port_, *apply_context);
    wrapper_ = std::make_unique<ReGraphHbmWrapper>(
        "grasu-regraph-hbm-wrapper", clock_id_, config_, policy_, wrapper_axis_,
        *source_state_primary_write_port_, *source_state_mirror_write_port_);
    const std::size_t round_limit =
        policy_.config().kind == GraphAlgorithmKind::kWeightedSssp &&
                fixed_rounds_ == 0
            ? config_.max_supersteps
            : fixed_rounds_;
    const bool fixed_round_limit =
        policy_.config().kind == GraphAlgorithmKind::kWeightedSssp &&
        fixed_rounds_ != 0;
    if (config_.frontend_count == 1) {
      controller_ = std::make_unique<GraSuReGraphController>(
          "grasu-regraph-controller", clock_id_, policy_.config().kind,
          round_limit, fixed_round_limit, partition_plans_, *source_hbm_reader_,
          *reader_, *gather_, *merger_, *apply_, *wrapper_);
    } else {
      k4_controller_ = std::make_unique<GraSuReGraphK4Controller>(
          "grasu-regraph-k4-controller", clock_id_, round_limit,
          fixed_round_limit, partition_plans_, k4_controller_inputs_.source_hbm,
          k4_controller_inputs_.readers, k4_controller_inputs_.gathers,
          *frontend_mux_, *merger_, *apply_, *wrapper_);
    }
  }

  [[nodiscard]] bool all_ports_idle() const noexcept {
    if (!gather_axis_.empty() || !merger_axis_.empty() ||
        !wrapper_axis_.empty() || !apply_state_read_port_->idle() ||
        !apply_state_write_port_->idle() ||
        !source_state_primary_write_port_->idle() ||
        !source_state_mirror_write_port_->idle()) {
      return false;
    }
    if (config_.frontend_count == 1) {
      if (!source_request_axis_.empty() || !source_response_axis_.empty() ||
          !edge_axis_.empty() || !row_port_->idle() ||
          !source_state_port_->idle() ||
          (degree_port_ != nullptr && !degree_port_->idle())) {
        return false;
      }
      return std::all_of(pma_ports_.begin(), pma_ports_.end(),
                         [](const auto &port) { return port->idle(); });
    }
    for (std::size_t worker = 0; worker < config_.frontend_count; ++worker) {
      if (!k4_source_request_axes_[worker]->empty() ||
          !k4_source_response_axes_[worker]->empty() ||
          !k4_edge_axes_[worker]->empty() ||
          !k4_gather_axes_[worker]->empty() || !k4_row_ports_[worker]->idle() ||
          !k4_source_state_ports_[worker]->idle() ||
          !std::all_of(k4_pma_ports_[worker].begin(),
                       k4_pma_ports_[worker].end(),
                       [](const auto &port) { return port->idle(); })) {
        return false;
      }
    }
    return true;
  }

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
  GraSuPartitionedPmaLayout layout_;
  std::uint32_t source_{};
  GraSuReGraphConfig config_;
  GraphAlgorithmPolicy policy_;
  std::vector<std::uint32_t> out_degrees_;
  std::optional<AlgorithmInitialState> initial_state_;
  std::size_t fixed_rounds_{};
  GraSuPartitionAddressPlan address_plan_;
  std::vector<ReGraphPartitionPlan> partition_plans_;
  std::optional<GraSuReGraphRuntimePlan> runtime_plan_;
  Fifo<PmaEdgeBatch> edge_axis_;
  Fifo<ReGraphSourceCacheRequest> source_request_axis_;
  Fifo<ReGraphSourceCacheResponse> source_response_axis_;
  Fifo<ReGraphGatherRow> gather_axis_;
  Fifo<ReGraphMergedBurst> merger_axis_;
  Fifo<ReGraphAppliedBurst> wrapper_axis_;
  std::array<std::unique_ptr<Fifo<PmaEdgeBatch>>, 4> k4_edge_axes_;
  std::array<std::unique_ptr<Fifo<ReGraphSourceCacheRequest>>, 4>
      k4_source_request_axes_;
  std::array<std::unique_ptr<Fifo<ReGraphSourceCacheResponse>>, 4>
      k4_source_response_axes_;
  std::array<std::unique_ptr<Fifo<ReGraphGatherRow>>, 4> k4_gather_axes_;
  std::unique_ptr<FixedAxiPort> row_port_;
  std::unique_ptr<FixedAxiPort> source_state_port_;
  std::unique_ptr<FixedAxiPort> degree_port_;
  std::array<std::unique_ptr<FixedAxiPort>, 4> pma_ports_;
  std::array<std::unique_ptr<FixedAxiPort>, 4> k4_row_ports_;
  std::array<std::unique_ptr<FixedAxiPort>, 4> k4_source_state_ports_;
  std::array<std::array<std::unique_ptr<FixedAxiPort>, 4>, 4> k4_pma_ports_;
  std::unique_ptr<FixedAxiPort> apply_state_read_port_;
  std::unique_ptr<FixedAxiPort> apply_state_write_port_;
  std::unique_ptr<FixedAxiPort> source_state_primary_write_port_;
  std::unique_ptr<FixedAxiPort> source_state_mirror_write_port_;
  std::unique_ptr<ReGraphSourceHbmReader> source_hbm_reader_;
  std::unique_ptr<PmaNativeReader> reader_;
  std::unique_ptr<ReGraphGather> gather_;
  std::array<std::unique_ptr<ReGraphSourceHbmReader>, 4> k4_source_hbm_readers_;
  std::array<std::unique_ptr<PmaNativeReader>, 4> k4_readers_;
  std::array<std::unique_ptr<ReGraphGather>, 4> k4_gathers_;
  std::unique_ptr<ReGraphFrontendMux> frontend_mux_;
  std::unique_ptr<ReGraphMerger> merger_;
  std::unique_ptr<ReGraphApply> apply_;
  std::unique_ptr<ReGraphHbmWrapper> wrapper_;
  std::unique_ptr<GraSuReGraphController> controller_;
  K4ControllerInputs k4_controller_inputs_;
  std::unique_ptr<GraSuReGraphK4Controller> k4_controller_;
  std::uint32_t next_initiator_{3100};
  std::uint64_t start_cycle_{};
  bool registered_{};
};

class GraSuNativeReGraphSsspSystem::Impl {
public:
  Impl(Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
       std::size_t vertices, std::size_t compact_edge_slots,
       std::uint32_t source, std::size_t supersteps, GraSuReGraphConfig config)
      : scheduler_(scheduler), clock_id_(clock_id), backend_(backend),
        vertices_(vertices), compact_edge_slots_(compact_edge_slots),
        source_(source), supersteps_(supersteps), config_(config),
        policy_(AlgorithmPolicyConfig{
            .kind = GraphAlgorithmKind::kWeightedSssp,
            .vertices = vertices,
            .source = source,
        }),
        edge_burst_axis_("grasu-native-edge-array-axis", clock_id_,
                         config_.edge_array_fifo_depth),
        scatter_axis_("grasu-native-scatter-axis", clock_id_,
                      config_.axis_fifo_depth),
        source_request_axis_("grasu-native-source-cache-request-axis",
                             clock_id_,
                             config_.source_cache_request_fifo_depth),
        source_response_axis_("grasu-native-source-cache-response-axis",
                              clock_id_,
                              config_.source_cache_response_fifo_depth),
        gather_axis_("grasu-native-gather-merger-axis", clock_id_,
                     config_.gather_merger_fifo_depth),
        merger_axis_("grasu-native-merger-apply-axis", clock_id_,
                     config_.merger_apply_fifo_depth),
        wrapper_axis_("grasu-native-apply-wrapper-axis", clock_id_,
                      config_.apply_wrapper_fifo_depth),
        start_cycle_(scheduler_.clock(clock_id_).completed_cycles) {
    validate_config();
    construct_ports();
    initialize_state();
    construct_components();
  }

  void register_components() {
    if (registered_) {
      throw std::logic_error(
          "native GraSU-ReGraph system registered more than once");
    }
    scheduler_.add_component(edge_burst_axis_);
    scheduler_.add_component(scatter_axis_);
    scheduler_.add_component(source_request_axis_);
    scheduler_.add_component(source_response_axis_);
    scheduler_.add_component(gather_axis_);
    scheduler_.add_component(merger_axis_);
    scheduler_.add_component(wrapper_axis_);
    edge_array_port_->register_components(scheduler_);
    source_state_port_->register_components(scheduler_);
    apply_state_read_port_->register_components(scheduler_);
    apply_state_write_port_->register_components(scheduler_);
    source_state_primary_write_port_->register_components(scheduler_);
    source_state_mirror_write_port_->register_components(scheduler_);
    scheduler_.add_component(*source_hbm_reader_);
    scheduler_.add_component(*edge_reader_);
    scheduler_.add_component(*scatter_);
    scheduler_.add_component(*gather_);
    scheduler_.add_component(*merger_);
    scheduler_.add_component(*apply_);
    scheduler_.add_component(*wrapper_);
    scheduler_.add_component(*controller_);
    registered_ = true;
  }

  [[nodiscard]] bool done() const noexcept {
    return registered_ && controller_->done() && all_ports_idle();
  }

  [[nodiscard]] bool failed() const noexcept { return false; }

  [[nodiscard]] const std::string &failure() const noexcept {
    static const std::string none;
    return none;
  }

  [[nodiscard]] GraSuNativeReGraphCounters counters() const noexcept {
    GraSuNativeReGraphCounters result;
    GraSuReGraphCounters &pipeline = result.pipeline;
    const auto account_axi_port = [&pipeline](const FixedAxiPort &port) {
      pipeline.axi_request_fifo_stalls +=
          port.requests().stats().push_stalls;
      pipeline.axi_backend_submit_stalls +=
          port.master().stats().backend_submit_stalls;
    };
    pipeline.state_bytes_per_vertex = state_bytes_per_vertex(policy_);
    pipeline.destination_partitions = 1;
    pipeline.supersteps = controller_->rounds();
    pipeline.partition_passes = controller_->rounds();
    pipeline.source_state_reads = source_hbm_reader_->requests();
    pipeline.source_cache_requests = scatter_->source_requests();
    pipeline.source_cache_request_markers = scatter_->source_request_markers();
    pipeline.source_cache_lines = scatter_->source_lines();
    pipeline.source_cache_lane_writes = scatter_->source_lane_writes();
    pipeline.source_cache_response_markers =
        scatter_->source_response_markers();
    pipeline.source_cache_wait_cycles = scatter_->source_wait_cycles();
    pipeline.source_cache_output_stall_cycles =
        source_hbm_reader_->output_stall_cycles();
    pipeline.source_cache_request_fifo_max_occupancy =
        source_request_axis_.stats().max_occupancy;
    pipeline.source_cache_response_fifo_max_occupancy =
        source_response_axis_.stats().max_occupancy;
    pipeline.source_state_writes = wrapper_->source_writes();
    pipeline.edge_batches_scanned = gather_->batches_scanned();
    pipeline.live_edges_scanned = gather_->live_edges();
    pipeline.active_edges_mapped = gather_->active_edges();
    pipeline.gather_reset_cycles = gather_->reset_cycles();
    pipeline.gather_merge_cycles = gather_->merge_cycles();
    pipeline.gather_pipeline_drain_cycles = gather_->pipeline_drain_cycles();
    pipeline.gather_output_stall_cycles = gather_->output_stall_cycles();
    pipeline.gather_bank_conflict_cycles = gather_->conflict_cycles();
    pipeline.gather_bank_updates = gather_->bank_updates();
    pipeline.gather_bypass_hits = gather_->bypass_hits();
    pipeline.gather_bypass_misses = gather_->bypass_misses();
    pipeline.gather_cross_bank_reductions = gather_->cross_bank_reductions();
    pipeline.gather_rows_emitted = gather_->rows_emitted();
    pipeline.merger_rows_consumed = merger_->rows_consumed();
    pipeline.merger_bursts_emitted = merger_->bursts_emitted();
    pipeline.merger_output_stall_cycles = merger_->output_stall_cycles();
    pipeline.apply_state_reads = apply_->reads();
    pipeline.apply_state_writes = apply_->writes();
    pipeline.apply_input_bursts = apply_->input_bursts();
    pipeline.apply_output_stall_cycles = apply_->output_stall_cycles();
    pipeline.apply_read_window_stalls = apply_->read_window_stalls();
    pipeline.apply_pipeline_capacity_stalls =
        apply_->pipeline_capacity_stalls();
    pipeline.apply_write_window_stalls = apply_->write_window_stalls();
    pipeline.apply_max_reads_inflight = apply_->max_reads_inflight();
    pipeline.apply_max_pipeline_occupancy = apply_->max_pipeline_occupancy();
    pipeline.apply_max_writes_inflight = apply_->max_writes_inflight();
    pipeline.hbm_wrapper_input_bursts = wrapper_->input_bursts();
    pipeline.hbm_wrapper_pipeline_capacity_stalls =
        wrapper_->pipeline_capacity_stalls();
    pipeline.hbm_wrapper_write_window_stalls = wrapper_->write_window_stalls();
    pipeline.hbm_wrapper_max_pipeline_occupancy =
        wrapper_->max_pipeline_occupancy();
    pipeline.hbm_wrapper_max_writes_inflight = wrapper_->max_writes_inflight();
    pipeline.gather_merger_fifo_max_occupancy =
        gather_axis_.stats().max_occupancy;
    pipeline.merger_apply_fifo_max_occupancy =
        merger_axis_.stats().max_occupancy;
    pipeline.apply_wrapper_fifo_max_occupancy =
        wrapper_axis_.stats().max_occupancy;
    pipeline.activated_vertices = apply_->total_activated();
    pipeline.source_state_read_bytes = source_hbm_reader_->read_bytes();
    pipeline.source_state_write_bytes = pipeline.source_state_writes *
                                        kStateWordsPerBurst *
                                        state_bytes_per_vertex(policy_);
    pipeline.apply_read_bytes = pipeline.apply_state_reads *
                                kStateWordsPerBurst *
                                state_bytes_per_vertex(policy_);
    pipeline.apply_write_bytes = pipeline.apply_state_writes *
                                 kStateWordsPerBurst *
                                 state_bytes_per_vertex(policy_);
    pipeline.axi_backend_submit_stalls =
        edge_array_port_->master().stats().backend_submit_stalls +
        source_state_port_->master().stats().backend_submit_stalls +
        apply_state_read_port_->master().stats().backend_submit_stalls +
        apply_state_write_port_->master().stats().backend_submit_stalls +
        source_state_primary_write_port_->master()
            .stats()
            .backend_submit_stalls +
        source_state_mirror_write_port_->master().stats().backend_submit_stalls;
    pipeline.axis_push_stalls = edge_burst_axis_.stats().push_stalls +
                                scatter_axis_.stats().push_stalls +
                                source_request_axis_.stats().push_stalls +
                                source_response_axis_.stats().push_stalls +
                                gather_axis_.stats().push_stalls +
                                merger_axis_.stats().push_stalls +
                                wrapper_axis_.stats().push_stalls;
    pipeline.start_cycle = start_cycle_;
    pipeline.end_cycle = scheduler_.clock(clock_id_).completed_cycles;
    pipeline.last_iteration_error = apply_->iteration_error();
    result.edge_array_requests = edge_reader_->requests();
    result.edge_array_bursts = edge_reader_->bursts();
    result.edge_array_slots_scanned = gather_->slots_scanned();
    result.edge_array_read_bytes =
        result.edge_array_requests * compact_edge_slots_ * 8;
    result.edge_array_output_stall_cycles = edge_reader_->output_stall_cycles();
    result.cross_source_round_bursts = scatter_->cross_source_round_bursts();
    return result;
  }

  [[nodiscard]] std::vector<std::uint32_t> distances() const {
    const auto bytes = backend_.inspect_payload(
        config_.vertex_state_channel, config_.vertex_state_base,
        vertices_ * state_bytes_per_vertex(policy_));
    std::vector<std::uint32_t> result(vertices_);
    for (std::size_t vertex = 0; vertex < vertices_; ++vertex) {
      result[vertex] = policy_distance(decode_u32(bytes, vertex * 4));
    }
    return result;
  }

private:
  void validate_config() const {
    const std::size_t highest_channel = std::max(
        {config_.edge_array_channel, config_.source_state_channel,
         config_.source_state_mirror_channel, config_.vertex_state_channel});
    if (vertices_ == 0 || vertices_ > config_.partition_vertices ||
        vertices_ > 65536 || source_ >= vertices_ || supersteps_ == 0 ||
        supersteps_ > config_.max_supersteps || compact_edge_slots_ < 8 ||
        compact_edge_slots_ % 8 != 0 ||
        compact_edge_slots_ > std::numeric_limits<std::uint32_t>::max() / 8U ||
        config_.memory_channels <= highest_channel ||
        config_.partition_vertices != 65536 ||
        config_.partition_vertices % kStateWordsPerBurst != 0 ||
        config_.source_buffer_vertices != 4096 ||
        config_.source_buffer_vertices % kStateWordsPerBurst != 0 ||
        config_.source_state_buffer_stride <
            config_.partition_vertices * state_bytes_per_vertex(policy_) ||
        config_.source_state_buffer_stride % 4096 != 0 ||
        config_.source_cache_request_fifo_depth == 0 ||
        config_.source_cache_response_fifo_depth == 0 ||
        config_.edge_array_fifo_depth == 0 || config_.axis_fifo_depth == 0 ||
        config_.gather_merger_fifo_depth == 0 ||
        config_.merger_apply_fifo_depth == 0 ||
        config_.apply_wrapper_fifo_depth == 0 || config_.edge_lanes != 8 ||
        config_.gather_banks != 8 || config_.gather_bypass_distance == 0 ||
        config_.gather_pipeline_latency <= config_.gather_bypass_distance ||
        config_.gather_vertices_per_reset_cycle == 0 ||
        config_.gather_vertices_per_merge_cycle != 2 ||
        config_.max_pending_requests == 0 ||
        config_.max_outstanding_bursts == 0 ||
        config_.response_beats_per_cycle == 0 ||
        config_.apply_request_window == 0 ||
        config_.apply_pipeline_latency == 0 ||
        config_.apply_pipeline_capacity == 0 ||
        config_.hbm_wrapper_pipeline_latency == 0 ||
        config_.hbm_wrapper_pipeline_capacity == 0) {
      throw std::invalid_argument("invalid native GraSU-ReGraph configuration");
    }
  }

  std::unique_ptr<FixedAxiPort>
  make_port(const std::string &name, std::size_t channel, std::uint32_t width) {
    return std::make_unique<FixedAxiPort>(
        name, clock_id_,
        port_config(config_, channel, next_initiator_++, width), backend_);
  }

  std::unique_ptr<FixedAxiPort> make_stream_port(const std::string &name,
                                                 std::size_t channel,
                                                 std::size_t read_fifo_depth) {
    FixedAxiPortConfig port =
        port_config(config_, channel, next_initiator_++, 64);
    port.stream_read_beats = true;
    port.read_beat_fifo_depth = read_fifo_depth;
    port.read_reorder_capacity = config_.max_outstanding_bursts * 16;
    return std::make_unique<FixedAxiPort>(name, clock_id_, port, backend_);
  }

  void construct_ports() {
    edge_array_port_ =
        make_stream_port("grasu-native-edge-array", config_.edge_array_channel,
                         config_.edge_array_fifo_depth);
    source_state_port_ = make_stream_port(
        "grasu-native-source-state", config_.source_state_channel,
        config_.source_cache_response_fifo_depth);
    apply_state_read_port_ = make_port("grasu-native-apply-state-read",
                                       config_.vertex_state_channel, 64);
    apply_state_write_port_ = make_port("grasu-native-apply-state-write",
                                        config_.vertex_state_channel, 64);
    source_state_primary_write_port_ =
        make_port("grasu-native-source-state-primary-write",
                  config_.source_state_channel, 64);
    source_state_mirror_write_port_ =
        make_port("grasu-native-source-state-mirror-write",
                  config_.source_state_mirror_channel, 64);
  }

  void initialize_state() {
    std::vector<std::uint8_t> bytes(config_.partition_vertices * 4);
    for (std::size_t vertex = 0; vertex < config_.partition_vertices;
         ++vertex) {
      const std::uint32_t encoded =
          vertex == source_
              ? encode_distance(0, true)
              : encode_distance(GraphAlgorithmPolicy::kSsspInfinity, false);
      for (std::size_t byte = 0; byte < 4; ++byte) {
        bytes[vertex * 4 + byte] =
            static_cast<std::uint8_t>(encoded >> (byte * 8));
      }
    }
    backend_.initialize_payload(config_.vertex_state_channel,
                                config_.vertex_state_base, bytes);
    backend_.initialize_payload(config_.source_state_channel,
                                config_.source_state_base, bytes);
    backend_.initialize_payload(config_.source_state_mirror_channel,
                                config_.source_state_base, bytes);
  }

  void construct_components() {
    source_hbm_reader_ = std::make_unique<ReGraphSourceHbmReader>(
        "grasu-native-source-hbm-reader", clock_id_, config_, policy_,
        source_request_axis_, source_response_axis_, *source_state_port_);
    edge_reader_ = std::make_unique<NativeEdgeArrayHbmReader>(
        "grasu-native-edge-array-reader", clock_id_, compact_edge_slots_,
        config_, edge_burst_axis_, *edge_array_port_);
    scatter_ = std::make_unique<NativeEdgeArrayScatter>(
        "grasu-native-edge-array-scatter", clock_id_, vertices_, config_,
        edge_burst_axis_, scatter_axis_, source_request_axis_,
        source_response_axis_, *edge_reader_);
    gather_ = std::make_unique<ReGraphGather>(
        "grasu-native-regraph-gather", clock_id_, vertices_, policy_, config_,
        scatter_axis_, gather_axis_, *scatter_);
    merger_ = std::make_unique<ReGraphMerger>("grasu-native-regraph-merger",
                                              clock_id_, config_, gather_axis_,
                                              merger_axis_);
    apply_ = std::make_unique<ReGraphApply>(
        "grasu-native-regraph-apply", clock_id_, vertices_, policy_, config_,
        merger_axis_, wrapper_axis_, *apply_state_read_port_,
        *apply_state_write_port_, nullptr, *scatter_);
    wrapper_ = std::make_unique<ReGraphHbmWrapper>(
        "grasu-native-regraph-hbm-wrapper", clock_id_, config_, policy_,
        wrapper_axis_, *source_state_primary_write_port_,
        *source_state_mirror_write_port_);
    controller_ = std::make_unique<GraSuNativeReGraphController>(
        "grasu-native-regraph-controller", clock_id_, supersteps_, vertices_,
        *source_hbm_reader_, *edge_reader_, *scatter_, *gather_, *merger_,
        *apply_, *wrapper_);
  }

  [[nodiscard]] bool all_ports_idle() const noexcept {
    return edge_burst_axis_.empty() && scatter_axis_.empty() &&
           source_request_axis_.empty() && source_response_axis_.empty() &&
           gather_axis_.empty() && merger_axis_.empty() &&
           wrapper_axis_.empty() && edge_array_port_->idle() &&
           source_state_port_->idle() && apply_state_read_port_->idle() &&
           apply_state_write_port_->idle() &&
           source_state_primary_write_port_->idle() &&
           source_state_mirror_write_port_->idle();
  }

  Scheduler &scheduler_;
  ClockId clock_id_{};
  MemoryBackend &backend_;
  std::size_t vertices_{};
  std::size_t compact_edge_slots_{};
  std::uint32_t source_{};
  std::size_t supersteps_{};
  GraSuReGraphConfig config_;
  GraphAlgorithmPolicy policy_;
  Fifo<NativeEdgeArrayBurst> edge_burst_axis_;
  Fifo<PmaEdgeBatch> scatter_axis_;
  Fifo<ReGraphSourceCacheRequest> source_request_axis_;
  Fifo<ReGraphSourceCacheResponse> source_response_axis_;
  Fifo<ReGraphGatherRow> gather_axis_;
  Fifo<ReGraphMergedBurst> merger_axis_;
  Fifo<ReGraphAppliedBurst> wrapper_axis_;
  std::unique_ptr<FixedAxiPort> edge_array_port_;
  std::unique_ptr<FixedAxiPort> source_state_port_;
  std::unique_ptr<FixedAxiPort> apply_state_read_port_;
  std::unique_ptr<FixedAxiPort> apply_state_write_port_;
  std::unique_ptr<FixedAxiPort> source_state_primary_write_port_;
  std::unique_ptr<FixedAxiPort> source_state_mirror_write_port_;
  std::unique_ptr<ReGraphSourceHbmReader> source_hbm_reader_;
  std::unique_ptr<NativeEdgeArrayHbmReader> edge_reader_;
  std::unique_ptr<NativeEdgeArrayScatter> scatter_;
  std::unique_ptr<ReGraphGather> gather_;
  std::unique_ptr<ReGraphMerger> merger_;
  std::unique_ptr<ReGraphApply> apply_;
  std::unique_ptr<ReGraphHbmWrapper> wrapper_;
  std::unique_ptr<GraSuNativeReGraphController> controller_;
  std::uint32_t next_initiator_{4100};
  std::uint64_t start_cycle_{};
  bool registered_{};
};

GraSuReGraphSsspSystem::GraSuReGraphSsspSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPmaLayout layout, std::uint32_t source, GraSuReGraphConfig config)
    : impl_(std::make_unique<Impl>(
          scheduler, clock_id, backend,
          one_partition_layout(layout, config.partition_vertices),
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kWeightedSssp,
              .vertices = layout.vertices,
              .source = source,
          }),
          std::vector<std::uint32_t>{}, 0, config)) {}

GraSuReGraphSsspSystem::GraSuReGraphSsspSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPmaLayout layout, GraphAlgorithmPolicy policy,
    std::vector<std::uint32_t> out_degrees, std::size_t fixed_rounds,
    GraSuReGraphConfig config,
    std::optional<AlgorithmInitialState> initial_state)
    : impl_(std::make_unique<Impl>(
          scheduler, clock_id, backend,
          one_partition_layout(std::move(layout), config.partition_vertices),
          std::move(policy), std::move(out_degrees), fixed_rounds, config,
          std::move(initial_state))) {}

GraSuReGraphSsspSystem::GraSuReGraphSsspSystem(Scheduler &scheduler,
                                               ClockId clock_id,
                                               MemoryBackend &backend,
                                               GraSuPartitionedPmaLayout layout,
                                               std::uint32_t source,
                                               GraSuReGraphConfig config)
    : impl_(
          std::make_unique<Impl>(scheduler, clock_id, backend, layout,
                                 GraphAlgorithmPolicy(AlgorithmPolicyConfig{
                                     .kind = GraphAlgorithmKind::kWeightedSssp,
                                     .vertices = layout.vertices,
                                     .source = source,
                                 }),
                                 std::vector<std::uint32_t>{}, 0, config)) {}

GraSuReGraphSsspSystem::GraSuReGraphSsspSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPartitionedPmaLayout layout, GraphAlgorithmPolicy policy,
    std::vector<std::uint32_t> out_degrees, std::size_t fixed_rounds,
    GraSuReGraphConfig config,
    std::optional<AlgorithmInitialState> initial_state)
    : impl_(std::make_unique<Impl>(
          scheduler, clock_id, backend, std::move(layout), std::move(policy),
          std::move(out_degrees), fixed_rounds, config,
          std::move(initial_state))) {}

GraSuReGraphSsspSystem::~GraSuReGraphSsspSystem() = default;

void GraSuReGraphSsspSystem::register_components() {
  impl_->register_components();
}

bool GraSuReGraphSsspSystem::done() const noexcept { return impl_->done(); }

bool GraSuReGraphSsspSystem::failed() const noexcept { return impl_->failed(); }

const std::string &GraSuReGraphSsspSystem::failure() const noexcept {
  return impl_->failure();
}

GraSuReGraphCounters GraSuReGraphSsspSystem::counters() const noexcept {
  return impl_->counters();
}

std::vector<std::size_t>
GraSuReGraphSsspSystem::frontier_out_sizes() const {
  return impl_->frontier_out_sizes();
}

std::vector<std::uint32_t> GraSuReGraphSsspSystem::distances() const {
  return impl_->distances();
}

std::vector<std::uint32_t> GraSuReGraphSsspSystem::state_words() const {
  return impl_->state_words();
}

std::vector<std::uint32_t>
GraSuReGraphSsspSystem::auxiliary_state_words() const {
  return impl_->auxiliary_state_words();
}

GraSuNativeReGraphSsspSystem::GraSuNativeReGraphSsspSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    std::size_t vertices, std::size_t compact_edge_slots, std::uint32_t source,
    std::size_t supersteps, GraSuReGraphConfig config)
    : impl_(std::make_unique<Impl>(scheduler, clock_id, backend, vertices,
                                   compact_edge_slots, source, supersteps,
                                   config)) {}

GraSuNativeReGraphSsspSystem::~GraSuNativeReGraphSsspSystem() = default;

void GraSuNativeReGraphSsspSystem::register_components() {
  impl_->register_components();
}

bool GraSuNativeReGraphSsspSystem::done() const noexcept {
  return impl_->done();
}

bool GraSuNativeReGraphSsspSystem::failed() const noexcept {
  return impl_->failed();
}

const std::string &GraSuNativeReGraphSsspSystem::failure() const noexcept {
  return impl_->failure();
}

GraSuNativeReGraphCounters
GraSuNativeReGraphSsspSystem::counters() const noexcept {
  return impl_->counters();
}

std::vector<std::uint32_t> GraSuNativeReGraphSsspSystem::distances() const {
  return impl_->distances();
}

GraSuReGraphPageRankSystem::GraSuReGraphPageRankSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPmaLayout layout, std::vector<std::uint32_t> out_degrees,
    std::size_t iterations, float damping, GraSuReGraphConfig config)
    : engine_(std::make_unique<GraSuReGraphSsspSystem>(
          scheduler, clock_id, backend, layout,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kFullPageRank,
              .vertices = layout.vertices,
              .source = 0,
              .damping = damping,
          }),
          std::move(out_degrees), iterations, config)) {}

GraSuReGraphPageRankSystem::GraSuReGraphPageRankSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPartitionedPmaLayout layout, std::vector<std::uint32_t> out_degrees,
    std::size_t iterations, float damping, GraSuReGraphConfig config)
    : engine_(std::make_unique<GraSuReGraphSsspSystem>(
          scheduler, clock_id, backend, layout,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kFullPageRank,
              .vertices = layout.vertices,
              .source = 0,
              .damping = damping,
          }),
          std::move(out_degrees), iterations, config)) {}

GraSuReGraphPageRankSystem::~GraSuReGraphPageRankSystem() = default;

void GraSuReGraphPageRankSystem::register_components() {
  engine_->register_components();
}

bool GraSuReGraphPageRankSystem::done() const noexcept {
  return engine_->done();
}

bool GraSuReGraphPageRankSystem::failed() const noexcept {
  return engine_->failed();
}

const std::string &GraSuReGraphPageRankSystem::failure() const noexcept {
  return engine_->failure();
}

GraSuReGraphCounters GraSuReGraphPageRankSystem::counters() const noexcept {
  return engine_->counters();
}

std::vector<float> GraSuReGraphPageRankSystem::ranks() const {
  const std::vector<std::uint32_t> words = engine_->state_words();
  std::vector<float> ranks(words.size());
  std::transform(words.begin(), words.end(), ranks.begin(),
                 GraphAlgorithmPolicy::word_to_float);
  return ranks;
}

GraSuReGraphResidualPageRankSystem::GraSuReGraphResidualPageRankSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPmaLayout layout, std::vector<std::uint32_t> out_degrees,
    std::size_t max_iterations, float damping, float epsilon,
    GraSuReGraphConfig config, ResidualPageRankContract residual_contract,
    std::optional<AlgorithmInitialState> initial_state)
    : engine_(std::make_unique<GraSuReGraphSsspSystem>(
          scheduler, clock_id, backend, layout,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kResidualPageRank,
              .vertices = layout.vertices,
              .source = 0,
              .damping = damping,
              .epsilon = epsilon,
              .residual_contract = residual_contract,
          }),
          std::move(out_degrees), max_iterations, config,
          std::move(initial_state))) {}

GraSuReGraphResidualPageRankSystem::GraSuReGraphResidualPageRankSystem(
    Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
    GraSuPartitionedPmaLayout layout, std::vector<std::uint32_t> out_degrees,
    std::size_t max_iterations, float damping, float epsilon,
    GraSuReGraphConfig config)
    : engine_(std::make_unique<GraSuReGraphSsspSystem>(
          scheduler, clock_id, backend, layout,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kResidualPageRank,
              .vertices = layout.vertices,
              .source = 0,
              .damping = damping,
              .epsilon = epsilon,
              .residual_contract = residual_contract,
          }),
          std::move(out_degrees), max_iterations, config,
          std::move(initial_state))) {}

GraSuReGraphResidualPageRankSystem::~GraSuReGraphResidualPageRankSystem() =
    default;

void GraSuReGraphResidualPageRankSystem::register_components() {
  engine_->register_components();
}

bool GraSuReGraphResidualPageRankSystem::done() const noexcept {
  return engine_->done();
}

bool GraSuReGraphResidualPageRankSystem::failed() const noexcept {
  return engine_->failed();
}

const std::string &
GraSuReGraphResidualPageRankSystem::failure() const noexcept {
  return engine_->failure();
}

GraSuReGraphCounters
GraSuReGraphResidualPageRankSystem::counters() const noexcept {
  return engine_->counters();
}

std::vector<float> GraSuReGraphResidualPageRankSystem::ranks() const {
  const std::vector<std::uint32_t> words = engine_->state_words();
  std::vector<float> values(words.size());
  std::transform(words.begin(), words.end(), values.begin(),
                 GraphAlgorithmPolicy::word_to_float);
  return values;
}

std::vector<float> GraSuReGraphResidualPageRankSystem::residuals() const {
  const std::vector<std::uint32_t> words = engine_->auxiliary_state_words();
  std::vector<float> values(words.size());
  std::transform(words.begin(), words.end(), values.begin(),
                 GraphAlgorithmPolicy::word_to_float);
  return values;
}

std::vector<std::size_t>
GraSuReGraphResidualPageRankSystem::frontier_out_sizes() const {
  return engine_->frontier_out_sizes();
}

GraSuReGraphConnectedComponentsSystem::
    GraSuReGraphConnectedComponentsSystem(
        Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
        GraSuPmaLayout layout, std::size_t max_iterations,
        GraSuReGraphConfig config,
        std::optional<AlgorithmInitialState> initial_state)
    : engine_(std::make_unique<GraSuReGraphSsspSystem>(
          scheduler, clock_id, backend, layout,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kConnectedComponents,
              .vertices = layout.vertices,
              .source = 0,
          }),
          std::vector<std::uint32_t>{}, max_iterations, config,
          std::move(initial_state))) {}

GraSuReGraphConnectedComponentsSystem::
    GraSuReGraphConnectedComponentsSystem(
        Scheduler &scheduler, ClockId clock_id, MemoryBackend &backend,
        GraSuPartitionedPmaLayout layout, std::size_t max_iterations,
        GraSuReGraphConfig config,
        std::optional<AlgorithmInitialState> initial_state)
    : engine_(std::make_unique<GraSuReGraphSsspSystem>(
          scheduler, clock_id, backend, layout,
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = GraphAlgorithmKind::kConnectedComponents,
              .vertices = layout.vertices,
              .source = 0,
          }),
          std::vector<std::uint32_t>{}, max_iterations, config,
          std::move(initial_state))) {}

GraSuReGraphConnectedComponentsSystem::
    ~GraSuReGraphConnectedComponentsSystem() = default;

void GraSuReGraphConnectedComponentsSystem::register_components() {
  engine_->register_components();
}

bool GraSuReGraphConnectedComponentsSystem::done() const noexcept {
  return engine_->done();
}

bool GraSuReGraphConnectedComponentsSystem::failed() const noexcept {
  return engine_->failed();
}

const std::string &
GraSuReGraphConnectedComponentsSystem::failure() const noexcept {
  return engine_->failure();
}

GraSuReGraphCounters
GraSuReGraphConnectedComponentsSystem::counters() const noexcept {
  return engine_->counters();
}

std::vector<std::uint32_t>
GraSuReGraphConnectedComponentsSystem::labels() const {
  return engine_->state_words();
}

std::vector<std::size_t>
GraSuReGraphConnectedComponentsSystem::frontier_out_sizes() const {
  return engine_->frontier_out_sizes();
}

} // namespace spine::sim
