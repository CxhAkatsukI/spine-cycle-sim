// clang-format off
#include "sst/core/sst_config.h"
// clang-format on

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <fstream>
#include <map>
#include <memory>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "spine_sim/axi.hpp"
#include "spine_sim/fifo.hpp"
#include "spine_sim/grasu.hpp"
#include "spine_sim/grasu_regraph.hpp"
#include "spine_sim/memory_backend.hpp"
#include "spine_sim/scheduler.hpp"
#include "spine_sim/spine_system.hpp"
#include "sst/core/component.h"
#include "sst/core/interfaces/stdMem.h"
#include "sst/core/output.h"
#include "sst/core/params.h"
#include "sst/core/subcomponent.h"
#include "sst/core/timeConverter.h"

namespace spine::sim::sst_adapter {

namespace {

struct SsspReference {
  std::vector<std::uint32_t> values;
  std::vector<std::vector<std::uint32_t>> frontiers;
  bool converged{};
};

struct SsspComparison {
  std::uint64_t value_mismatches{};
  std::uint64_t frontier_mismatches{};
};

struct ResidualPageRankReference {
  std::vector<float> ranks;
  std::vector<float> residuals;
  std::vector<std::size_t> frontier_in_sizes;
  std::vector<std::size_t> frontier_out_sizes;
  bool converged{};
};

std::vector<float> run_full_pagerank_reference(const SpineEdgeSlice &workload,
                                               float damping,
                                               std::size_t iterations) {
  std::vector<std::vector<std::uint32_t>> adjacency(workload.vertices);
  std::vector<std::uint32_t> out_degrees(workload.vertices, 0);
  for (const SpineEdgeRecord &edge : workload.edges) {
    if (edge.diff <= 0 || edge.src >= workload.vertices ||
        edge.dst >= workload.vertices) {
      throw std::invalid_argument(
          "PageRank SST reference requires in-range insertion edges");
    }
    adjacency[edge.src].push_back(edge.dst);
    ++out_degrees[edge.src];
  }
  std::vector<float> ranks(workload.vertices,
                           1.0F / static_cast<float>(workload.vertices));
  for (std::size_t iteration = 0; iteration < iterations; ++iteration) {
    float dangling_mass = 0.0F;
    for (std::size_t vertex = 0; vertex < workload.vertices; ++vertex) {
      if (out_degrees[vertex] == 0) {
        dangling_mass += ranks[vertex];
      }
    }
    const float base = (1.0F - damping) / static_cast<float>(workload.vertices);
    const float dangling_share =
        damping * dangling_mass / static_cast<float>(workload.vertices);
    std::vector<float> next(workload.vertices, base + dangling_share);
    for (std::size_t source = 0; source < workload.vertices; ++source) {
      if (out_degrees[source] == 0) {
        continue;
      }
      const float contribution =
          damping * ranks[source] / static_cast<float>(out_degrees[source]);
      for (const std::uint32_t destination : adjacency[source]) {
        next[destination] += contribution;
      }
    }
    ranks = std::move(next);
  }
  return ranks;
}

ResidualPageRankReference run_residual_pagerank_reference(
    const SpineEdgeSlice &workload, float damping, float epsilon,
    std::size_t max_iterations) {
  std::vector<std::vector<std::uint32_t>> adjacency(workload.vertices);
  std::vector<std::uint32_t> out_degrees(workload.vertices, 0);
  for (const SpineEdgeRecord &edge : workload.edges) {
    if (edge.diff <= 0 || edge.src >= workload.vertices ||
        edge.dst >= workload.vertices) {
      throw std::invalid_argument(
          "residual PageRank SST reference requires insertion edges");
    }
    adjacency[edge.src].push_back(edge.dst);
    ++out_degrees[edge.src];
  }
  ResidualPageRankReference reference;
  reference.ranks.assign(workload.vertices, 0.0F);
  reference.residuals.assign(
      workload.vertices,
      (1.0F - damping) / static_cast<float>(workload.vertices));
  std::vector<std::uint32_t> active(workload.vertices);
  std::iota(active.begin(), active.end(), 0U);
  const float threshold = epsilon / static_cast<float>(workload.vertices);
  for (std::size_t iteration = 0; iteration < max_iterations; ++iteration) {
    reference.frontier_in_sizes.push_back(active.size());
    std::vector<float> deltas(workload.vertices, 0.0F);
    float dangling = 0.0F;
    for (const std::uint32_t source : active) {
      const float delta = reference.residuals[source];
      deltas[source] = delta;
      reference.residuals[source] = 0.0F;
      reference.ranks[source] += delta;
      if (out_degrees[source] == 0) {
        dangling += delta;
      }
    }
    const float dangling_share =
        damping * dangling / static_cast<float>(workload.vertices);
    std::vector<float> incoming(workload.vertices, 0.0F);
    for (std::size_t source = 0; source < workload.vertices; ++source) {
      if (deltas[source] == 0.0F || out_degrees[source] == 0) {
        continue;
      }
      const float contribution =
          damping * deltas[source] / static_cast<float>(out_degrees[source]);
      for (const std::uint32_t destination : adjacency[source]) {
        incoming[destination] += contribution;
      }
    }
    std::vector<std::uint32_t> next;
    for (std::size_t vertex = 0; vertex < workload.vertices; ++vertex) {
      const float combined = incoming[vertex] + dangling_share;
      reference.residuals[vertex] += combined;
      if (std::fabs(reference.residuals[vertex]) > threshold) {
        next.push_back(static_cast<std::uint32_t>(vertex));
      }
    }
    reference.frontier_out_sizes.push_back(next.size());
    if (next.empty()) {
      reference.converged = true;
      break;
    }
    active = std::move(next);
  }
  return reference;
}

SpineAxiInterfaceProfile spine_axi_profile_from_id(const std::string &id) {
  if (id == "hls_split_9c08763") {
    return {};
  }
  if (id == "legacy_uniform64") {
    return SpineAxiInterfaceProfile::legacy_uniform64();
  }
  throw std::invalid_argument("unknown Spine AXI interface profile: " + id);
}

using SsspAdjacency =
    std::vector<std::vector<std::pair<std::uint32_t, std::uint16_t>>>;

SsspAdjacency build_sssp_adjacency(const SpineEdgeSlice &workload) {
  using EdgeKey = std::pair<std::uint32_t, std::uint32_t>;
  std::map<EdgeKey, std::pair<std::uint16_t, std::int64_t>> coalesced;
  for (const SpineEdgeRecord &edge : workload.edges) {
    const EdgeKey key{edge.src, edge.dst};
    const auto found = coalesced.find(key);
    if (found == coalesced.end()) {
      coalesced.emplace(
          key, std::pair{edge.weight, static_cast<std::int64_t>(edge.diff)});
    } else {
      found->second.first = std::min(found->second.first, edge.weight);
      found->second.second += edge.diff;
    }
  }
  SsspAdjacency adjacency(workload.vertices);
  for (const auto &[key, value] : coalesced) {
    if (value.second > 0) {
      adjacency[key.first].push_back({key.second, value.first});
    }
  }
  return adjacency;
}

SpineEdgeSlice materialize_weighted_snapshot(const SpineEdgeSlice &initial,
                                             const SpineEdgeSlice &update) {
  if (initial.vertices == 0 || update.vertices != initial.vertices) {
    throw std::invalid_argument(
        "weighted update snapshot requires matching non-empty graphs");
  }
  using EdgeKey =
      std::tuple<std::uint32_t, std::uint32_t, std::uint16_t>;
  std::map<EdgeKey, std::int64_t> multiplicities;
  const auto apply = [&](const SpineEdgeSlice &slice) {
    for (const SpineEdgeRecord &edge : slice.edges) {
      if (edge.src >= initial.vertices || edge.dst >= initial.vertices ||
          edge.diff == 0) {
        throw std::invalid_argument(
            "weighted update contains an invalid edge record");
      }
      std::int64_t &count =
          multiplicities[{edge.src, edge.dst, edge.weight}];
      count += edge.diff;
      if (count < 0) {
        throw std::invalid_argument(
            "weighted update deletes a missing edge instance");
      }
    }
  };
  apply(initial);
  apply(update);

  SpineEdgeSlice snapshot{
      .vertices = initial.vertices,
      .edges = {},
      .case_name = initial.case_name + "+" + update.case_name,
  };
  for (const auto &[key, count] : multiplicities) {
    std::int64_t remaining = count;
    while (remaining > 0) {
      const std::int16_t chunk = static_cast<std::int16_t>(
          std::min<std::int64_t>(remaining,
                                 std::numeric_limits<std::int16_t>::max()));
      snapshot.edges.push_back(SpineEdgeRecord{
          .src = std::get<0>(key),
          .dst = std::get<1>(key),
          .weight = std::get<2>(key),
          .diff = chunk,
      });
      remaining -= chunk;
    }
  }
  if (snapshot.edges.empty()) {
    throw std::invalid_argument("weighted update produced an empty graph");
  }
  return snapshot;
}

SsspReference run_sssp_reference_from_state(
    const SpineEdgeSlice &workload, std::vector<std::uint32_t> initial_values,
    std::vector<std::uint32_t> initial_frontier, std::size_t max_rounds) {
  if (initial_values.size() != workload.vertices || initial_frontier.empty() ||
      std::any_of(initial_frontier.begin(), initial_frontier.end(),
                  [&](std::uint32_t vertex) {
                    return vertex >= workload.vertices;
                  })) {
    throw std::invalid_argument("invalid incremental SSSP reference state");
  }
  const SsspAdjacency adjacency = build_sssp_adjacency(workload);
  SsspReference reference;
  reference.values = std::move(initial_values);
  std::vector<std::uint32_t> frontier = std::move(initial_frontier);
  for (std::size_t round = 0; round < max_rounds; ++round) {
    reference.frontiers.push_back(frontier);
    std::map<std::uint32_t, std::uint32_t> reduced;
    for (const std::uint32_t src : frontier) {
      for (const auto &[dst, weight] : adjacency[src]) {
        const std::uint32_t value = reference.values[src];
        const std::uint32_t proposal =
            value == SpineSplitSsspCompute::kInfinity ||
                    value > SpineSplitSsspCompute::kInfinity - weight
                ? SpineSplitSsspCompute::kInfinity
                : value + weight;
        const auto found = reduced.find(dst);
        if (found == reduced.end()) {
          reduced.emplace(dst, proposal);
        } else {
          found->second = std::min(found->second, proposal);
        }
      }
    }
    std::vector<std::uint32_t> next;
    for (const auto &[vertex, proposal] : reduced) {
      if (proposal < reference.values[vertex]) {
        reference.values[vertex] = proposal;
        next.push_back(vertex);
      }
    }
    if (next.empty()) {
      reference.converged = true;
      break;
    }
    frontier = std::move(next);
  }
  return reference;
}

SsspReference run_sssp_reference(const SpineEdgeSlice &workload,
                                 std::uint32_t source, std::size_t max_rounds) {
  if (source >= workload.vertices) {
    throw std::invalid_argument("SSSP source is outside the workload");
  }
  std::vector<std::uint32_t> values(workload.vertices,
                                    SpineSplitSsspCompute::kInfinity);
  values[source] = 0;
  return run_sssp_reference_from_state(workload, std::move(values), {source},
                                       max_rounds);
}

SsspComparison compare_sssp_result(
    const std::vector<std::uint32_t> &values,
    const std::vector<SpineSsspRoundEvidence> &rounds,
    const SsspReference &reference) {
  SsspComparison comparison;
  if (values.size() != reference.values.size()) {
    comparison.value_mismatches = 1;
  }
  const std::size_t compared_values =
      std::min(values.size(), reference.values.size());
  for (std::size_t vertex = 0; vertex < compared_values; ++vertex) {
    comparison.value_mismatches +=
        values[vertex] == reference.values[vertex] ? 0 : 1;
  }
  comparison.frontier_mismatches =
      rounds.size() == reference.frontiers.size() ? 0 : 1;
  const std::size_t compared_rounds =
      std::min(rounds.size(), reference.frontiers.size());
  for (std::size_t round = 0; round < compared_rounds; ++round) {
    auto actual_in = rounds[round].active_in;
    auto actual_out = rounds[round].active_out;
    std::sort(actual_in.begin(), actual_in.end());
    std::sort(actual_out.begin(), actual_out.end());
    const std::vector<std::uint32_t> expected_out =
        round + 1 < reference.frontiers.size()
            ? reference.frontiers[round + 1]
            : std::vector<std::uint32_t>{};
    if (actual_in != reference.frontiers[round] ||
        actual_out != expected_out) {
      ++comparison.frontier_mismatches;
    }
  }
  return comparison;
}

template <typename T>
void write_json_array(std::ostream &output, const std::vector<T> &values) {
  output << '[';
  for (std::size_t index = 0; index < values.size(); ++index) {
    if (index != 0) {
      output << ", ";
    }
    output << values[index];
  }
  output << ']';
}

class ProbeSource final : public Component {
 public:
  ProbeSource(ClockId clock_id, Fifo<AxiRequest> &output,
              std::uint64_t request_count, std::uint64_t request_bytes,
              std::uint64_t stride_bytes, std::uint64_t address_span,
              std::uint32_t write_percent)
      : Component("probe-source", clock_id),
        output_(output),
        request_count_(request_count),
        request_bytes_(request_bytes),
        stride_bytes_(stride_bytes),
        address_span_(address_span),
        write_percent_(write_percent) {}

  void evaluate(const CycleContext &) override {
    accepted_ = false;
    if (issued_ >= request_count_) {
      return;
    }
    const std::uint64_t usable_span =
        address_span_ > request_bytes_ ? address_span_ - request_bytes_ : 1;
    const std::uint64_t address = (issued_ * stride_bytes_) % usable_span;
    const std::uint64_t writes_before = issued_ * write_percent_ / 100;
    const std::uint64_t writes_after = (issued_ + 1) * write_percent_ / 100;
    const MemoryOperation operation = writes_after > writes_before
                                          ? MemoryOperation::kWrite
                                          : MemoryOperation::kRead;
    accepted_ = output_.try_push(AxiRequest{
        .transaction_id = issued_,
        .operation = operation,
        .address = address,
        .bytes = request_bytes_,
        .write_data = {},
    });
  }

  void commit(const CycleContext &) override {
    if (accepted_) {
      ++issued_;
      accepted_ = false;
    }
  }

  [[nodiscard]] bool done() const noexcept { return issued_ == request_count_; }
  [[nodiscard]] std::uint64_t issued() const noexcept { return issued_; }

 private:
  Fifo<AxiRequest> &output_;
  std::uint64_t request_count_{};
  std::uint64_t request_bytes_{};
  std::uint64_t stride_bytes_{};
  std::uint64_t address_span_{};
  std::uint32_t write_percent_{};
  std::uint64_t issued_{};
  bool accepted_{};
};

class ProbeSink final : public Component {
 public:
  ProbeSink(ClockId clock_id, Fifo<AxiResponse> &input)
      : Component("probe-sink", clock_id), input_(input) {}

  void evaluate(const CycleContext &) override {
    accepted_ = input_.try_pop(staged_);
  }

  void commit(const CycleContext &) override {
    if (!accepted_) {
      return;
    }
    ++completed_;
    if (!staged_.success) {
      ++failed_;
    }
    accepted_ = false;
  }

  [[nodiscard]] std::uint64_t completed() const noexcept { return completed_; }
  [[nodiscard]] std::uint64_t failed() const noexcept { return failed_; }

 private:
  Fifo<AxiResponse> &input_;
  AxiResponse staged_;
  std::uint64_t completed_{};
  std::uint64_t failed_{};
  bool accepted_{};
};

class PayloadRoundTrip final : public Component {
 public:
  PayloadRoundTrip(ClockId clock_id, Fifo<AxiRequest> &requests,
                   Fifo<AxiResponse> &responses)
      : Component("payload-round-trip", clock_id),
        requests_(requests),
        responses_(responses),
        pattern_(1600) {
    for (std::size_t index = 0; index < pattern_.size(); ++index) {
      pattern_[index] = static_cast<std::uint8_t>((index * 17 + 3) & 0xff);
    }
  }

  void evaluate(const CycleContext &) override {
    action_ = Action::kNone;
    if (phase_ == Phase::kWriteIssue) {
      if (requests_.try_push(AxiRequest{
              .transaction_id = 0,
              .operation = MemoryOperation::kWrite,
              .address = 4032,
              .bytes = pattern_.size(),
              .write_data = pattern_,
          })) {
        action_ = Action::kIssued;
      }
    } else if (phase_ == Phase::kReadIssue) {
      if (requests_.try_push(AxiRequest{
              .transaction_id = 1,
              .operation = MemoryOperation::kRead,
              .address = 4032,
              .bytes = pattern_.size(),
              .write_data = {},
          })) {
        action_ = Action::kIssued;
      }
    } else if (phase_ == Phase::kWriteWait || phase_ == Phase::kReadWait) {
      if (responses_.try_pop(staged_response_)) {
        action_ = Action::kCompleted;
      }
    }
  }

  void commit(const CycleContext &) override {
    if (action_ == Action::kIssued) {
      phase_ =
          phase_ == Phase::kWriteIssue ? Phase::kWriteWait : Phase::kReadWait;
    } else if (action_ == Action::kCompleted) {
      if (!staged_response_.success) {
        failed_ = true;
      }
      if (phase_ == Phase::kWriteWait) {
        if (staged_response_.transaction_id != 0 ||
            !staged_response_.read_data.empty()) {
          failed_ = true;
        }
        phase_ = Phase::kReadIssue;
      } else {
        if (staged_response_.transaction_id != 1 ||
            staged_response_.read_data != pattern_) {
          failed_ = true;
        }
        phase_ = Phase::kDone;
      }
    }
    action_ = Action::kNone;
  }

  [[nodiscard]] bool done() const noexcept { return phase_ == Phase::kDone; }
  [[nodiscard]] bool failed() const noexcept { return failed_; }
  [[nodiscard]] std::size_t bytes() const noexcept { return pattern_.size(); }

 private:
  enum class Phase { kWriteIssue, kWriteWait, kReadIssue, kReadWait, kDone };
  enum class Action { kNone, kIssued, kCompleted };

  Fifo<AxiRequest> &requests_;
  Fifo<AxiResponse> &responses_;
  std::vector<std::uint8_t> pattern_;
  AxiResponse staged_response_;
  Phase phase_{Phase::kWriteIssue};
  Action action_{Action::kNone};
  bool failed_{};
};

class SpineWordSource final : public Component {
 public:
  SpineWordSource(ClockId clock_id, Fifo<PartConvWord> &output,
                  std::vector<PartConvWord> words)
      : Component("spine-word-source", clock_id),
        output_(output),
        words_(std::move(words)) {}

  void evaluate(const CycleContext &) override {
    accepted_ = index_ < words_.size() && output_.try_push(words_[index_]);
  }

  void commit(const CycleContext &) override {
    if (accepted_) {
      ++index_;
      accepted_ = false;
    }
  }

  [[nodiscard]] bool done() const noexcept { return index_ == words_.size(); }

 private:
  Fifo<PartConvWord> &output_;
  std::vector<PartConvWord> words_;
  std::size_t index_{};
  bool accepted_{};
};

class SstMemoryBackend final : public MemoryBackend {
 public:
  SstMemoryBackend(ClockId clock_id,
                   std::vector<SST::Interfaces::StandardMem *> interfaces,
                   std::uint64_t channel_capacity_bytes,
                   std::size_t accepts_per_channel_per_cycle,
                   std::size_t max_outstanding_per_channel,
                   std::size_t response_queue_depth)
      : MemoryBackend("sst-hbm-backend", clock_id),
        interfaces_(std::move(interfaces)),
        channel_capacity_bytes_(channel_capacity_bytes),
        accepts_per_channel_per_cycle_(accepts_per_channel_per_cycle),
        max_outstanding_per_channel_(max_outstanding_per_channel),
        response_queue_depth_(response_queue_depth),
        channel_outstanding_(interfaces_.size(), 0) {
    if (interfaces_.empty() || channel_capacity_bytes_ == 0 ||
        accepts_per_channel_per_cycle_ == 0 ||
        max_outstanding_per_channel_ == 0 || response_queue_depth_ == 0) {
      throw std::invalid_argument("invalid SST memory backend configuration");
    }
  }

  bool try_submit(const BackendRequest &request) override {
    if (!initiator_registered(request.initiator_id) ||
        request.channel >= interfaces_.size() || request.bytes == 0) {
      throw std::invalid_argument("invalid SST backend request");
    }
    if ((request.operation == MemoryOperation::kRead &&
         !request.write_data.empty()) ||
        (request.operation == MemoryOperation::kWrite &&
         request.write_data.size() != request.bytes)) {
      throw std::invalid_argument("invalid SST backend request payload");
    }
    const auto staged_for_channel = static_cast<std::size_t>(
        std::count_if(staged_submissions_.begin(), staged_submissions_.end(),
                      [&request](const BackendRequest &staged) {
                        return staged.channel == request.channel;
                      }));
    if (staged_for_channel >= accepts_per_channel_per_cycle_ ||
        channel_outstanding_[request.channel] + staged_for_channel >=
            max_outstanding_per_channel_) {
      ++submit_stalls_;
      return false;
    }
    staged_submissions_.push_back(request);
    return true;
  }

  [[nodiscard]] std::size_t response_count(
      std::uint32_t initiator_id) const noexcept override {
    const auto found = responses_.find(initiator_id);
    return found == responses_.end() ? 0 : found->second.size();
  }

  [[nodiscard]] const BackendResponse &response_at(
      std::uint32_t initiator_id, std::size_t index) const override {
    const auto found = responses_.find(initiator_id);
    if (found == responses_.end() || index >= found->second.size()) {
      throw std::out_of_range("SST backend response index out of range");
    }
    return found->second[index];
  }

  bool stage_pop_responses(std::uint32_t initiator_id,
                           std::size_t count) override {
    const std::size_t staged = staged_response_pops_[initiator_id];
    if (staged != 0 || count > response_count(initiator_id)) {
      return false;
    }
    staged_response_pops_[initiator_id] = count;
    return true;
  }

  [[nodiscard]] std::size_t outstanding() const noexcept override {
    std::size_t count = staged_submissions_.size();
    for (std::size_t value : channel_outstanding_) {
      count += value;
    }
    return count;
  }

  [[nodiscard]] std::size_t outstanding_for(
      std::uint32_t initiator_id) const noexcept override {
    const auto staged = static_cast<std::size_t>(
        std::count_if(staged_submissions_.begin(), staged_submissions_.end(),
                      [initiator_id](const BackendRequest &request) {
                        return request.initiator_id == initiator_id;
                      }));
    const auto inflight = initiator_outstanding_.find(initiator_id);
    return staged +
           (inflight == initiator_outstanding_.end() ? 0 : inflight->second);
  }

  void prepare(const CycleContext &) override {
    for (auto iterator = external_arrivals_.begin();
         iterator != external_arrivals_.end();) {
      auto &queue = responses_[iterator->initiator_id];
      if (queue.size() >= response_queue_depth_) {
        ++response_queue_stalls_;
        ++iterator;
        continue;
      }
      queue.push_back(*iterator);
      iterator = external_arrivals_.erase(iterator);
    }
  }

  void evaluate(const CycleContext &) override {}

  void commit(const CycleContext &) override {
    for (const auto &[initiator_id, count] : staged_response_pops_) {
      auto &queue = responses_[initiator_id];
      for (std::size_t index = 0; index < count; ++index) {
        queue.pop_front();
      }
    }
    staged_response_pops_.clear();

    for (const BackendRequest &request : staged_submissions_) {
      const std::uint64_t local_address =
          request.address % channel_capacity_bytes_;
      SST::Interfaces::StandardMem::Request *standard_request = nullptr;
      if (request.operation == MemoryOperation::kWrite) {
        standard_request = new SST::Interfaces::StandardMem::Write(
            local_address, request.bytes, request.write_data);
      } else {
        standard_request = new SST::Interfaces::StandardMem::Read(
            local_address, request.bytes);
      }
      standard_request->setNoncacheable();
      const auto standard_id = standard_request->getID();
      inflight_.emplace(standard_id,
                        Inflight{
                            .backend_request_id = request.request_id,
                            .initiator_id = request.initiator_id,
                            .channel = request.channel,
                            .operation = request.operation,
                            .bytes = request.bytes,
                            .request = request,
                        });
      ++channel_outstanding_[request.channel];
      ++initiator_outstanding_[request.initiator_id];
      ++accepted_;
      interfaces_[request.channel]->send(standard_request);
    }
    staged_submissions_.clear();
    max_outstanding_ = std::max(max_outstanding_, outstanding());
  }

  void on_response(SST::Interfaces::StandardMem::Request *request) {
    const auto found = inflight_.find(request->getID());
    if (found == inflight_.end()) {
      throw std::logic_error("SST returned an unknown StandardMem request");
    }
    std::vector<std::uint8_t> read_data;
    if (found->second.operation == MemoryOperation::kRead) {
      auto *read_response =
          dynamic_cast<SST::Interfaces::StandardMem::ReadResp *>(request);
      if (read_response == nullptr ||
          read_response->data.size() != found->second.bytes) {
        throw std::logic_error("SST returned a malformed read response");
      }
      read_data = complete_read_payload(found->second.request);
    } else if (dynamic_cast<SST::Interfaces::StandardMem::WriteResp *>(
                   request) == nullptr) {
      throw std::logic_error("SST returned a malformed write response");
    } else {
      commit_write_payload(found->second.request);
    }
    external_arrivals_.push_back(BackendResponse{
        .initiator_id = found->second.initiator_id,
        .request_id = found->second.backend_request_id,
        .success = request->getSuccess(),
        .read_data = std::move(read_data),
    });
    --channel_outstanding_[found->second.channel];
    --initiator_outstanding_[found->second.initiator_id];
    inflight_.erase(found);
    delete request;
  }

  [[nodiscard]] std::uint64_t accepted() const noexcept { return accepted_; }
  [[nodiscard]] std::uint64_t submit_stalls() const noexcept {
    return submit_stalls_;
  }
  [[nodiscard]] std::uint64_t response_queue_stalls() const noexcept {
    return response_queue_stalls_;
  }
  [[nodiscard]] std::size_t max_outstanding() const noexcept {
    return max_outstanding_;
  }

 private:
  struct Inflight {
    std::uint64_t backend_request_id{};
    std::uint32_t initiator_id{};
    std::size_t channel{};
    MemoryOperation operation{MemoryOperation::kRead};
    std::uint32_t bytes{};
    BackendRequest request;
  };

  std::vector<SST::Interfaces::StandardMem *> interfaces_;
  std::uint64_t channel_capacity_bytes_{};
  std::size_t accepts_per_channel_per_cycle_{};
  std::size_t max_outstanding_per_channel_{};
  std::size_t response_queue_depth_{};
  std::vector<std::size_t> channel_outstanding_;
  std::unordered_map<std::uint32_t, std::size_t> initiator_outstanding_;
  std::vector<BackendRequest> staged_submissions_;
  std::unordered_map<SST::Interfaces::StandardMem::Request::id_t, Inflight>
      inflight_;
  std::deque<BackendResponse> external_arrivals_;
  std::unordered_map<std::uint32_t, std::deque<BackendResponse>> responses_;
  std::unordered_map<std::uint32_t, std::size_t> staged_response_pops_;
  std::uint64_t accepted_{};
  std::uint64_t submit_stalls_{};
  std::uint64_t response_queue_stalls_{};
  std::size_t max_outstanding_{};
};

}  // namespace

class OnlineMemoryProbe final : public SST::Component {
 public:
  OnlineMemoryProbe(SST::ComponentId_t id, SST::Params &params)
      : SST::Component(id) {
    output_.init("[spine_cycle.OnlineMemoryProbe] ",
                 params.find<int>("verbose", 0), 0, SST::Output::STDOUT);
    result_path_ = params.find<std::string>("output", "sst_memory_probe.json");
    mode_ = params.find<std::string>("mode", "probe");
    workload_path_ = params.find<std::string>("workload", "");
    update_workload_path_ =
        params.find<std::string>("update_workload", "");
    preload_path_ = params.find<std::string>("preload_workload", "");
    hot_vertices_text_ = params.find<std::string>("hot_vertices", "");
    source_vertex_ = params.find<std::uint32_t>("source_vertex", 0);
    core_clock_ = params.find<std::string>("core_clock", "141MHz");
    core_mhz_ = params.find<double>("core_mhz", 141.0);
    request_count_ = params.find<std::uint64_t>("requests", 256);
    request_bytes_ = params.find<std::uint64_t>("request_bytes", 64);
    stride_bytes_ = params.find<std::uint64_t>("stride_bytes", 64);
    channels_ = params.find<std::size_t>("channels", 1);
    channel_capacity_bytes_ =
        params.find<std::uint64_t>("channel_capacity_bytes", 1ULL << 30);
    write_percent_ = params.find<std::uint32_t>("write_percent", 0);
    max_cycles_ = params.find<std::uint64_t>("max_cycles", 1'000'000);
    max_rounds_ = params.find<std::size_t>("max_rounds", 256);
    pagerank_iterations_ = params.find<std::size_t>("pagerank_iterations", 1);
    pagerank_damping_ = params.find<float>("pagerank_damping", 0.85F);
    pagerank_epsilon_ = params.find<float>("pagerank_epsilon", 1.0e-6F);
    residual_max_iterations_ =
        params.find<std::size_t>("residual_max_iterations", 256);
    pagerank_pipeline_config_.source_map = {
        .latency_cycles =
            params.find<std::uint64_t>("pagerank_source_latency", 3),
        .initiation_interval =
            params.find<std::uint64_t>("pagerank_source_ii", 1),
        .capacity = params.find<std::size_t>("pagerank_source_capacity", 4),
    };
    pagerank_pipeline_config_.edge_map = {
        .latency_cycles =
            params.find<std::uint64_t>("pagerank_edge_latency", 1),
        .initiation_interval =
            params.find<std::uint64_t>("pagerank_edge_ii", 1),
        .capacity = params.find<std::size_t>("pagerank_edge_capacity", 4),
    };
    pagerank_pipeline_config_.reduce = {
        .latency_cycles =
            params.find<std::uint64_t>("pagerank_reduce_latency", 2),
        .initiation_interval =
            params.find<std::uint64_t>("pagerank_reduce_ii", 1),
        .capacity = params.find<std::size_t>("pagerank_reduce_capacity", 8),
    };
    pagerank_pipeline_config_.apply = {
        .latency_cycles =
            params.find<std::uint64_t>("pagerank_apply_latency", 3),
        .initiation_interval =
            params.find<std::uint64_t>("pagerank_apply_ii", 1),
        .capacity = params.find<std::size_t>("pagerank_apply_capacity", 8),
    };
    device_dirty_source_limit_ =
        params.find<std::size_t>("device_dirty_source_limit", 4'096);
    range_task_active_gate_ =
        params.find<std::size_t>("range_task_active_gate", 16'384);
    range_task_capacity_ =
        params.find<std::size_t>("range_task_capacity", 65'536);
    range_task_payload_budget_ =
        params.find<std::uint64_t>("range_task_payload_budget", 1'048'576);
    fallback_replay_threshold_ =
        params.find<std::uint64_t>("fallback_replay_threshold", 65'536);
    memory_request_window_ =
        params.find<std::size_t>("memory_request_window", 1);
    compute_memory_request_window_ =
        params.find<std::size_t>("compute_memory_request_window", 7);
    compute_writeonly_request_window_ =
        params.find<std::size_t>("compute_writeonly_request_window", 4);
    compute_on_chip_profile_.tiny_bram_read_latency =
        params.find<std::size_t>("compute_tiny_bram_read_latency", 2);
    compute_on_chip_profile_.vs_uram_read_latency =
        params.find<std::size_t>("compute_vs_uram_read_latency", 2);
    compute_on_chip_profile_.active_bram_read_latency =
        params.find<std::size_t>("compute_active_bram_read_latency", 2);
    compute_on_chip_profile_.pipeline_capacity =
        params.find<std::size_t>("compute_onchip_pipeline_capacity", 4);
    compute_on_chip_profile_.vs_bypass_depth =
        params.find<std::size_t>("compute_vs_bypass_depth", 4);
    reader_edge_pipeline_depth_ =
        params.find<std::size_t>("reader_edge_pipeline_depth", 32);
    reader_edge_response_capacity_ =
        params.find<std::size_t>("reader_edge_response_capacity", 32);
    maintenance_count_scan_ii_ =
        params.find<std::size_t>("maintenance_count_scan_ii", 1);
    maintenance_count_scan_tail_cycles_ =
        params.find<std::size_t>("maintenance_count_scan_tail_cycles", 19);
    maintenance_l0_write_scan_ii_ =
        params.find<std::size_t>("maintenance_l0_write_scan_ii", 24);
    maintenance_l0_write_scan_tail_cycles_ =
        params.find<std::size_t>("maintenance_l0_write_scan_tail_cycles", 42);
    maintenance_scan_response_capacity_ =
        params.find<std::size_t>("maintenance_scan_response_capacity", 32);
    spine_axi_profile_id_ =
        params.find<std::string>("spine_axi_profile", "hls_split_9c08763");
    grasu_config_.memory_channels = channels_;
    grasu_config_.cache_segments_per_half =
        params.find<std::size_t>("grasu_cache_segments_per_half", 131072);
    grasu_config_.partition_vertices =
        params.find<std::size_t>("grasu_partition_vertices", 65536);
    grasu_config_.source_buffer_vertices =
        params.find<std::size_t>("grasu_source_buffer_vertices", 4096);
    grasu_config_.edge_lanes =
        params.find<std::size_t>("grasu_edge_lanes", 4);
    grasu_config_.gather_banks =
        params.find<std::size_t>("grasu_gather_banks", 4);
    grasu_config_.source_state_channel =
        params.find<std::size_t>("grasu_source_state_channel", 1);
    grasu_config_.source_state_mirror_channel =
        params.find<std::size_t>("grasu_source_state_mirror_channel", 3);
    grasu_config_.vertex_state_channel =
        params.find<std::size_t>("grasu_apply_state_channel", 30);
    grasu_config_.axis_fifo_depth =
        params.find<std::size_t>("grasu_axis_fifo_depth", 16);
    grasu_config_.gather_merger_fifo_depth =
        params.find<std::size_t>("grasu_gather_merger_fifo_depth", 16);
    grasu_config_.merger_apply_fifo_depth =
        params.find<std::size_t>("grasu_merger_apply_fifo_depth", 16);
    grasu_config_.apply_wrapper_fifo_depth =
        params.find<std::size_t>("grasu_apply_wrapper_fifo_depth", 16);
    grasu_config_.reader_buffer_batches =
        params.find<std::size_t>("grasu_reader_buffer_batches", 32);
    grasu_config_.max_pending_requests =
        params.find<std::size_t>("grasu_max_pending_requests", 32);
    grasu_config_.max_outstanding_bursts =
        params.find<std::size_t>("grasu_max_outstanding_bursts", 32);
    grasu_config_.apply_request_window =
        params.find<std::size_t>("grasu_apply_request_window", 32);
    grasu_config_.apply_pipeline_latency =
        params.find<std::size_t>("grasu_apply_pipeline_latency", 100);
    grasu_config_.apply_pipeline_capacity =
        params.find<std::size_t>("grasu_apply_pipeline_capacity", 100);
    grasu_config_.hbm_wrapper_pipeline_latency =
        params.find<std::size_t>("grasu_hbm_wrapper_pipeline_latency", 71);
    grasu_config_.hbm_wrapper_pipeline_capacity =
        params.find<std::size_t>("grasu_hbm_wrapper_pipeline_capacity", 71);
    grasu_config_.max_supersteps = max_rounds_;
    grasu_update_config_.memory_channels = channels_;
    grasu_update_config_.cache_segments_per_half =
        grasu_config_.cache_segments_per_half;
    grasu_update_config_.axis_fifo_depth = grasu_config_.axis_fifo_depth;
    grasu_update_config_.max_pending_requests =
        grasu_config_.max_pending_requests;
    grasu_update_config_.max_outstanding_bursts =
        grasu_config_.max_outstanding_bursts;
    if ((mode_ != "probe" && mode_ != "payload_roundtrip" &&
         mode_ != "spine_vertical" && mode_ != "spine_compute" &&
         mode_ != "spine_sssp" && mode_ != "spine_pagerank" &&
         mode_ != "spine_residual_pagerank" &&
         mode_ != "grasu_regraph_sssp") ||
        channels_ == 0 || channel_capacity_bytes_ == 0 || max_rounds_ == 0 ||
        pagerank_iterations_ == 0 || !(pagerank_damping_ > 0.0F) ||
        !(pagerank_damping_ < 1.0F) ||
        !(pagerank_epsilon_ > 0.0F) || residual_max_iterations_ == 0 ||
        pagerank_pipeline_config_.source_map.latency_cycles == 0 ||
        pagerank_pipeline_config_.source_map.initiation_interval == 0 ||
        pagerank_pipeline_config_.source_map.capacity == 0 ||
        pagerank_pipeline_config_.edge_map.latency_cycles == 0 ||
        pagerank_pipeline_config_.edge_map.initiation_interval == 0 ||
        pagerank_pipeline_config_.edge_map.capacity == 0 ||
        pagerank_pipeline_config_.reduce.latency_cycles == 0 ||
        pagerank_pipeline_config_.reduce.initiation_interval == 0 ||
        pagerank_pipeline_config_.reduce.capacity == 0 ||
        pagerank_pipeline_config_.apply.latency_cycles == 0 ||
        pagerank_pipeline_config_.apply.initiation_interval == 0 ||
        pagerank_pipeline_config_.apply.capacity == 0 ||
        device_dirty_source_limit_ == 0 || range_task_active_gate_ == 0 ||
        range_task_capacity_ == 0 || range_task_capacity_ > 65'536 ||
        range_task_payload_budget_ == 0 || fallback_replay_threshold_ == 0 ||
        memory_request_window_ == 0 || compute_memory_request_window_ == 0 ||
        compute_writeonly_request_window_ == 0 ||
        compute_on_chip_profile_.tiny_bram_read_latency == 0 ||
        compute_on_chip_profile_.vs_uram_read_latency == 0 ||
        compute_on_chip_profile_.active_bram_read_latency == 0 ||
        compute_on_chip_profile_.pipeline_capacity == 0 ||
        compute_on_chip_profile_.vs_bypass_depth == 0 ||
        reader_edge_pipeline_depth_ == 0 ||
        reader_edge_response_capacity_ == 0 ||
        maintenance_count_scan_ii_ == 0 || maintenance_l0_write_scan_ii_ == 0 ||
        maintenance_scan_response_capacity_ == 0 ||
        (spine_axi_profile_id_ != "hls_split_9c08763" &&
         spine_axi_profile_id_ != "legacy_uniform64") ||
        write_percent_ > 100 ||
        (mode_ == "probe" &&
         (request_count_ == 0 || request_bytes_ == 0 || stride_bytes_ == 0)) ||
        ((mode_ == "spine_vertical" || mode_ == "spine_compute" ||
          mode_ == "spine_sssp" || mode_ == "spine_pagerank" ||
          mode_ == "spine_residual_pagerank" ||
          mode_ == "grasu_regraph_sssp") &&
         (channels_ < 23 || workload_path_.empty())) ||
        (mode_ == "grasu_regraph_sssp" && channels_ < 32)) {
      output_.fatal(CALL_INFO, -1, "invalid online memory probe parameters\n");
    }
    spine_axi_profile_ = spine_axi_profile_from_id(spine_axi_profile_id_);

    clock_converter_ = registerClock(
        core_clock_,
        new SST::Clock::Handler<OnlineMemoryProbe,
                                &OnlineMemoryProbe::clock_tick>(this));

    SST::SubComponentSlotInfo *slot = getSubComponentSlotInfo("memory");
    if (slot == nullptr) {
      output_.fatal(CALL_INFO, -1, "memory subcomponent slots are required\n");
    }
    interfaces_.resize(channels_, nullptr);
    for (std::size_t channel = 0; channel < channels_; ++channel) {
      interfaces_[channel] = slot->create<SST::Interfaces::StandardMem>(
          channel, SST::ComponentInfo::SHARE_NONE, clock_converter_,
          new SST::Interfaces::StandardMem::Handler<
              OnlineMemoryProbe, &OnlineMemoryProbe::on_memory_response>(this));
      if (interfaces_[channel] == nullptr) {
        output_.fatal(CALL_INFO, -1,
                      "memory slot %zu is not populated with StandardMem\n",
                      channel);
      }
    }

    registerAsPrimaryComponent();
    primaryComponentDoNotEndSim();
  }

  void init(unsigned int phase) override {
    for (auto *interface : interfaces_) {
      interface->init(phase);
    }
  }

  void setup() override {
    for (auto *interface : interfaces_) {
      interface->setup();
    }
    const ClockId core = scheduler_.add_clock_mhz("core", core_mhz_);
    backend_ = std::make_unique<SstMemoryBackend>(
        core, interfaces_, channel_capacity_bytes_, 1, 32, 128);
    if (mode_ == "grasu_regraph_sssp") {
      SpineEdgeSlice initial = load_spine_edge_slice(workload_path_);
      SpineEdgeSlice final_snapshot = initial;
      std::vector<GraSuEdge> initial_edges;
      std::vector<GraSuEdge> reserved_updates;
      std::vector<GraSuEdge> updates;
      const auto append_initial = [&](const SpineEdgeRecord &edge) {
        if (edge.weight != 1 || edge.diff != 1 ||
            edge.src >= initial.vertices || edge.dst >= initial.vertices) {
          throw std::invalid_argument(
              "GraSU/ReGraph SST initial graph requires unique unit-weight "
              "insertion records");
        }
        initial_edges.push_back(GraSuEdge{
            .source = edge.src,
            .destination = edge.dst,
        });
      };
      for (const SpineEdgeRecord &edge : initial.edges) {
        append_initial(edge);
      }
      if (!update_workload_path_.empty()) {
        SpineEdgeSlice update = load_spine_edge_slice(update_workload_path_);
        if (update.vertices != initial.vertices) {
          throw std::invalid_argument(
              "GraSU/ReGraph update vertex count does not match snapshot");
        }
        for (const SpineEdgeRecord &edge : update.edges) {
          if (edge.weight != 1 || std::abs(edge.diff) != 1 ||
              edge.src >= initial.vertices || edge.dst >= initial.vertices) {
            throw std::invalid_argument(
                "GraSU/ReGraph SST update requires unit multiplicity and "
                "unit weight");
          }
          GraSuEdge converted{
              .source = edge.src,
              .destination = edge.dst,
              .delete_op = edge.diff < 0,
          };
          updates.push_back(converted);
          if (!converted.delete_op) {
            reserved_updates.push_back(converted);
          }
        }
        final_snapshot = materialize_weighted_snapshot(initial, update);
      }
      grasu_initial_edges_ = initial_edges.size();
      grasu_update_edges_ = updates.size();
      grasu_layout_ = GraSuPmaLayout::build(initial.vertices, initial_edges,
                                            reserved_updates);
      grasu_sssp_reference_ =
          run_sssp_reference(final_snapshot, source_vertex_, max_rounds_);
      if (!grasu_sssp_reference_.converged) {
        throw std::invalid_argument(
            "GraSU/ReGraph SST SSSP reference did not converge");
      }
      grasu_update_system_ = std::make_unique<GraSuPmaUpdateSystem>(
          scheduler_, core, *backend_, grasu_layout_, std::move(updates),
          grasu_update_config_);
      grasu_update_system_->register_components();
      scheduler_.add_component(*backend_);
      return;
    }
    if (mode_ == "spine_pagerank" || mode_ == "spine_residual_pagerank") {
      SpineEdgeSlice workload = load_spine_edge_slice(workload_path_);
      spine_expected_edges_ = workload.edges.size();
      if (mode_ == "spine_pagerank") {
        pagerank_reference_ = run_full_pagerank_reference(
            workload, pagerank_damping_, pagerank_iterations_);
      } else {
        residual_pagerank_reference_ = run_residual_pagerank_reference(
            workload, pagerank_damping_, pagerank_epsilon_,
            residual_max_iterations_);
      }
      SpineL0Config maintenance_config;
      maintenance_config.device_dirty_source_limit = device_dirty_source_limit_;
      maintenance_config.range_task_active_gate = range_task_active_gate_;
      maintenance_config.range_task_capacity = range_task_capacity_;
      maintenance_config.range_task_payload_budget = range_task_payload_budget_;
      maintenance_config.fallback_replay_threshold = fallback_replay_threshold_;
      maintenance_config.memory_request_window = memory_request_window_;
      maintenance_config.reader_edge_pipeline_depth =
          reader_edge_pipeline_depth_;
      maintenance_config.reader_edge_response_capacity =
          reader_edge_response_capacity_;
      maintenance_config.maintenance_count_scan_ii = maintenance_count_scan_ii_;
      maintenance_config.maintenance_count_scan_tail_cycles =
          maintenance_count_scan_tail_cycles_;
      maintenance_config.maintenance_l0_write_scan_ii =
          maintenance_l0_write_scan_ii_;
      maintenance_config.maintenance_l0_write_scan_tail_cycles =
          maintenance_l0_write_scan_tail_cycles_;
      maintenance_config.maintenance_scan_response_capacity =
          maintenance_scan_response_capacity_;
      if (!hot_vertices_text_.empty()) {
        std::istringstream vertices(hot_vertices_text_);
        std::string item;
        while (std::getline(vertices, item, ',')) {
          if (item.empty()) {
            output_.fatal(CALL_INFO, -1, "empty hot vertex token\n");
          }
          maintenance_config.hot_vertices.push_back(
              static_cast<std::uint32_t>(std::stoul(item)));
        }
      }
      const GraphAlgorithmKind kind =
          mode_ == "spine_pagerank" ? GraphAlgorithmKind::kFullPageRank
                                    : GraphAlgorithmKind::kResidualPageRank;
      const std::size_t vertices = workload.vertices;
      pagerank_system_ = std::make_unique<SpinePageRankVerticalSliceSystem>(
          scheduler_, core, *backend_, std::move(workload),
          GraphAlgorithmPolicy(AlgorithmPolicyConfig{
              .kind = kind,
              .vertices = vertices,
              .source = 0,
              .damping = pagerank_damping_,
              .epsilon = pagerank_epsilon_,
          }),
          std::move(maintenance_config), spine_axi_profile_,
          pagerank_pipeline_config_, compute_memory_request_window_);
      pagerank_system_->register_components();
      pagerank_iteration_start_cycle_ = scheduler_.clock(core).completed_cycles;
      scheduler_.add_component(*backend_);
      return;
    }
    if (mode_ == "spine_compute") {
      const SpineEdgeSlice workload = load_spine_edge_slice(workload_path_);
      std::map<std::uint32_t, std::vector<SpineEdgeRecord>> tiles;
      for (const SpineEdgeRecord &edge : workload.edges) {
        if (edge.diff <= 0) {
          continue;
        }
        const std::uint32_t tile_base = (edge.dst / 65'536U) * 65'536U;
        tiles[tile_base].push_back(edge);
        ++spine_expected_edges_;
        const std::uint32_t initial =
            edge.dst == source_vertex_ ? 0 : SpineSplitSsspCompute::kInfinity;
        const auto found = expected_distances_.find(edge.dst);
        const std::uint32_t previous =
            found == expected_distances_.end() ? initial : found->second;
        expected_distances_[edge.dst] =
            std::min<std::uint32_t>(previous, edge.weight);
      }
      std::vector<PartConvWord> words;
      words.reserve(spine_expected_edges_ + 2 * tiles.size() + 1);
      for (const auto &[tile_base, edges] : tiles) {
        words.push_back(PartConvWord{.kind = PartConvWordKind::kTileBegin,
                                     .first = tile_base});
        for (const SpineEdgeRecord &edge : edges) {
          words.push_back(PartConvWord{
              .kind = PartConvWordKind::kEdge,
              .first = edge.dst,
              .second = edge.weight,
          });
        }
        words.push_back(PartConvWord{
            .kind = PartConvWordKind::kTileEnd,
            .first = tile_base,
            .second = static_cast<std::uint32_t>(
                std::min<std::size_t>(65'536, workload.vertices - tile_base)),
        });
      }
      words.push_back(PartConvWord{.kind = PartConvWordKind::kDoneAll});

      spine_edge_stream_ =
          std::make_unique<Fifo<PartConvWord>>("spine-edge-axis", core, 32);
      spine_value_stream_ =
          std::make_unique<Fifo<SourceValueWord>>("spine-value-axis", core, 32);
      const auto make_port = [&](const std::string &name,
                                 std::uint32_t initiator, std::size_t channel,
                                 SpineAxiPortKind kind) {
        return std::make_unique<FixedAxiPort>(
            name, core,
            spine_axi_profile_.port_config(kind, channels_, channel, initiator),
            *backend_);
      };
      spine_vertex_state_ = make_port("spine-vertex-state", 117, 17,
                                      SpineAxiPortKind::kVertexState);
      spine_active_out_ =
          make_port("spine-active-out", 119, 19, SpineAxiPortKind::kActiveOut);
      spine_compute_result_ = make_port("spine-compute-result", 121, 21,
                                        SpineAxiPortKind::kComputeResult);
      spine_active_bitmap_ = make_port("spine-active-bitmap", 122, 22,
                                       SpineAxiPortKind::kActiveBitmap);
      spine_word_source_ = std::make_unique<SpineWordSource>(
          core, *spine_edge_stream_, std::move(words));
      spine_compute_ = std::make_unique<SpineSplitSsspCompute>(
          "spine-split-compute", core, workload.vertices, source_vertex_, 4096,
          SpineComputePorts{
              .vertex_state = spine_vertex_state_.get(),
              .active_out = spine_active_out_.get(),
              .active_bitmap = spine_active_bitmap_.get(),
              .result = spine_compute_result_.get(),
          },
          *spine_edge_stream_, *spine_value_stream_,
          compute_memory_request_window_, compute_writeonly_request_window_,
          compute_on_chip_profile_);
      scheduler_.add_component(*spine_word_source_);
      scheduler_.add_component(*spine_compute_);
      scheduler_.add_component(*spine_edge_stream_);
      scheduler_.add_component(*spine_value_stream_);
      spine_vertex_state_->register_components(scheduler_);
      spine_active_out_->register_components(scheduler_);
      spine_active_bitmap_->register_components(scheduler_);
      spine_compute_result_->register_components(scheduler_);
      scheduler_.add_component(*backend_);
      return;
    }
    if (mode_ == "spine_vertical" || mode_ == "spine_sssp") {
      SpineEdgeSlice workload = load_spine_edge_slice(workload_path_);
      spine_expected_edges_ = workload.edges.size();
      if (mode_ == "spine_sssp") {
        sssp_reference_ =
            run_sssp_reference(workload, source_vertex_, max_rounds_);
        if (!sssp_reference_.converged || !preload_path_.empty()) {
          output_.fatal(CALL_INFO, -1,
                        "SSSP reference did not converge or preload is set\n");
        }
        if (!update_workload_path_.empty()) {
          dynamic_update_workload_ =
              load_spine_edge_slice(update_workload_path_);
          if (dynamic_update_workload_.vertices != workload.vertices ||
              dynamic_update_workload_.edges.empty()) {
            output_.fatal(
                CALL_INFO, -1,
                "dynamic SSSP update must be non-empty and use the same "
                "vertex count\n");
          }
          dynamic_sssp_enabled_ = true;
          dynamic_full_rebuild_ = std::any_of(
              dynamic_update_workload_.edges.begin(),
              dynamic_update_workload_.edges.end(),
              [](const SpineEdgeRecord &edge) { return edge.diff < 0; });
          cold_sssp_reference_ = sssp_reference_;
          for (const SpineEdgeRecord &edge : dynamic_update_workload_.edges) {
            dynamic_update_sources_.push_back(edge.src);
          }
          std::sort(dynamic_update_sources_.begin(),
                    dynamic_update_sources_.end());
          dynamic_update_sources_.erase(
              std::unique(dynamic_update_sources_.begin(),
                          dynamic_update_sources_.end()),
              dynamic_update_sources_.end());
          dynamic_materialized_snapshot_ =
              materialize_weighted_snapshot(workload,
                                            dynamic_update_workload_);
          sssp_reference_ =
              run_sssp_reference(dynamic_materialized_snapshot_, source_vertex_,
                                 max_rounds_);
          if (!dynamic_full_rebuild_) {
            dynamic_sssp_reference_ = run_sssp_reference_from_state(
                dynamic_materialized_snapshot_, cold_sssp_reference_.values,
                dynamic_update_sources_, max_rounds_);
          }
          if (!sssp_reference_.converged ||
              (!dynamic_full_rebuild_ &&
               (!dynamic_sssp_reference_.converged ||
                dynamic_sssp_reference_.values != sssp_reference_.values))) {
            output_.fatal(CALL_INFO, -1,
                          "dynamic SSSP references did not converge or agree\n");
          }
        }
        sst_current_frontier_ = {source_vertex_};
        sst_round_start_cycle_ = scheduler_.clock(core).completed_cycles;
      }
      SpineL0Config maintenance_config;
      maintenance_config.device_dirty_source_limit = device_dirty_source_limit_;
      maintenance_config.range_task_active_gate = range_task_active_gate_;
      maintenance_config.range_task_capacity = range_task_capacity_;
      maintenance_config.range_task_payload_budget = range_task_payload_budget_;
      maintenance_config.fallback_replay_threshold = fallback_replay_threshold_;
      maintenance_config.memory_request_window = memory_request_window_;
      maintenance_config.reader_edge_pipeline_depth =
          reader_edge_pipeline_depth_;
      maintenance_config.reader_edge_response_capacity =
          reader_edge_response_capacity_;
      maintenance_config.maintenance_count_scan_ii = maintenance_count_scan_ii_;
      maintenance_config.maintenance_count_scan_tail_cycles =
          maintenance_count_scan_tail_cycles_;
      maintenance_config.maintenance_l0_write_scan_ii =
          maintenance_l0_write_scan_ii_;
      maintenance_config.maintenance_l0_write_scan_tail_cycles =
          maintenance_l0_write_scan_tail_cycles_;
      maintenance_config.maintenance_scan_response_capacity =
          maintenance_scan_response_capacity_;
      if (!hot_vertices_text_.empty()) {
        std::istringstream vertices(hot_vertices_text_);
        std::string item;
        while (std::getline(vertices, item, ',')) {
          if (item.empty()) {
            output_.fatal(CALL_INFO, -1, "empty hot vertex token\n");
          }
          maintenance_config.hot_vertices.push_back(
              static_cast<std::uint32_t>(std::stoul(item)));
        }
      }
      SpineL0State initial_state;
      initial_state.hot_vertices.insert(maintenance_config.hot_vertices.begin(),
                                        maintenance_config.hot_vertices.end());
      initial_state.hot_enabled = !initial_state.hot_vertices.empty();
      const auto add_expected = [&](const SpineEdgeRecord &edge) {
        if (edge.src == source_vertex_ && edge.diff > 0) {
          const auto found = expected_distances_.find(edge.dst);
          if (found == expected_distances_.end()) {
            expected_distances_.emplace(edge.dst, edge.weight);
          } else {
            found->second = std::min<std::uint32_t>(found->second, edge.weight);
          }
        }
      };
      if (!preload_path_.empty()) {
        SpineEdgeSlice preload = load_spine_edge_slice(preload_path_);
        if (preload.vertices != workload.vertices) {
          output_.fatal(CALL_INFO, -1,
                        "preload and update workloads disagree on vertices\n");
        }
        spine_preload_edges_ = preload.edges.size();
        for (const SpineEdgeRecord &edge : preload.edges) {
          const bool hot = initial_state.hot_vertices.contains(edge.dst);
          const std::size_t family =
              hot ? spine_hot_shard(edge.dst)
                  : std::min<std::size_t>(
                        edge.dst / maintenance_config.vertex_partition_size,
                        15);
          auto &level = hot ? initial_state.hot_levels[family][0]
                            : initial_state.cold_levels[family][0];
          level.push_back(edge);
          add_expected(edge);
        }
      }
      for (const SpineEdgeRecord &edge : workload.edges) {
        add_expected(edge);
      }
      spine_system_ = std::make_unique<SpineVerticalSliceSystem>(
          scheduler_, core, *backend_, std::move(workload), source_vertex_,
          4096, std::move(maintenance_config), std::move(initial_state),
          spine_axi_profile_, compute_memory_request_window_,
          compute_writeonly_request_window_, compute_on_chip_profile_);
      spine_system_->register_components();
      scheduler_.add_component(*backend_);
      return;
    }

    requests_ = std::make_unique<Fifo<AxiRequest>>("axi-requests", core, 32);
    responses_ = std::make_unique<Fifo<AxiResponse>>("axi-responses", core, 32);
    axi_ = std::make_unique<AxiMaster>("axi-master", core,
                                       AxiConfig{
                                           .initiator_id = 0,
                                           .data_width_bytes = 64,
                                           .max_burst_beats = 16,
                                           .channels = channels_,
                                           .channel_interleave_bytes = 64,
                                           .max_pending_requests = 32,
                                           .max_outstanding_bursts = 32,
                                           .address_accepts_per_cycle = 1,
                                           .beat_issues_per_cycle = 1,
                                           .response_beats_per_cycle = 4,
                                           .fixed_channel = std::nullopt,
                                       },
                                       *requests_, *responses_, *backend_);
    if (mode_ == "payload_roundtrip") {
      payload_round_trip_ =
          std::make_unique<PayloadRoundTrip>(core, *requests_, *responses_);
      scheduler_.add_component(*payload_round_trip_);
    } else {
      source_ = std::make_unique<ProbeSource>(
          core, *requests_, request_count_, request_bytes_, stride_bytes_,
          channel_capacity_bytes_ * channels_, write_percent_);
      sink_ = std::make_unique<ProbeSink>(core, *responses_);
      scheduler_.add_component(*source_);
      scheduler_.add_component(*sink_);
    }
    scheduler_.add_component(*requests_);
    scheduler_.add_component(*axi_);
    scheduler_.add_component(*backend_);
    scheduler_.add_component(*responses_);
  }

  void finish() override {
    if (!result_written_) {
      write_result(false);
    }
  }

  bool clock_tick(SST::Cycle_t) {
    scheduler_.step();
    if (mode_ == "grasu_regraph_sssp") {
      if (grasu_update_system_->failed()) {
        write_result(false);
        primaryComponentOKToEndSim();
        return true;
      }
      if (grasu_compute_system_ == nullptr && grasu_update_system_->done() &&
          backend_->outstanding() == 0) {
        grasu_update_counters_ = grasu_update_system_->counters();
        grasu_update_counters_captured_ = true;
        grasu_compute_system_ = std::make_unique<GraSuReGraphSsspSystem>(
            scheduler_, 0, *backend_, grasu_layout_, source_vertex_,
            grasu_config_);
        grasu_compute_system_->register_components();
        return false;
      }
      if (grasu_compute_system_ != nullptr &&
          grasu_compute_system_->done() && backend_->outstanding() == 0) {
        write_result(!grasu_compute_system_->failed());
        primaryComponentOKToEndSim();
        return true;
      }
    } else if (mode_ == "spine_pagerank" ||
               mode_ == "spine_residual_pagerank") {
      if (pagerank_system_->done() && pagerank_system_->idle() &&
          backend_->outstanding() == 0) {
        const std::uint64_t now = scheduler_.clock(0).completed_cycles;
        pagerank_iteration_cycles_.push_back(now -
                                             pagerank_iteration_start_cycle_);
        pagerank_frontier_in_sizes_.push_back(
            pagerank_system_->reader_counters().source_requests);
        pagerank_frontier_out_sizes_.push_back(
            pagerank_system_->compute().next_active().size());
        pagerank_compute_requests_per_iteration_.push_back(
            pagerank_system_->compute_counters().memory_requests_issued);
        ++pagerank_completed_iterations_;
        const bool residual_converged =
            mode_ == "spine_residual_pagerank" &&
            pagerank_system_->compute().next_active().empty();
        const std::size_t iteration_limit =
            mode_ == "spine_pagerank" ? pagerank_iterations_
                                      : residual_max_iterations_;
        if (!pagerank_system_->failed() && !residual_converged &&
            pagerank_completed_iterations_ < iteration_limit) {
          pagerank_system_->restart_iteration();
          pagerank_iteration_start_cycle_ = now;
          return false;
        }
        const bool completed =
            mode_ == "spine_pagerank"
                ? pagerank_completed_iterations_ == pagerank_iterations_
                : residual_converged;
        write_result(!pagerank_system_->failed() && completed);
        primaryComponentOKToEndSim();
        return true;
      }
    } else if (mode_ == "spine_compute") {
      if (spine_word_source_->done() && spine_compute_->done() &&
          spine_edge_stream_->empty() && spine_vertex_state_->idle() &&
          spine_active_out_->idle() && spine_active_bitmap_->idle() &&
          spine_compute_result_->idle() && backend_->outstanding() == 0) {
        write_result(!spine_compute_->failed());
        primaryComponentOKToEndSim();
        return true;
      }
    } else if (mode_ == "spine_sssp") {
      if (spine_system_->done() && spine_system_->idle() &&
          backend_->outstanding() == 0) {
        if (!sst_waiting_dirty_ack_ &&
            spine_system_->recoverable_host_handoff()) {
          const std::uint64_t device_end_cycle =
              scheduler_.clock(0).completed_cycles;
          SpineSsspRoundEvidence device_attempt{
              .round = sst_rounds_.size(),
              .active_in = sst_current_frontier_,
              .reader_sources = spine_system_->reader_source_ids(),
              .active_out = spine_system_->compute().next_active(),
              .reader = spine_system_->reader_counters(),
              .compute = spine_system_->compute_counters(),
              .edge_axis = spine_system_->edge_stream_stats(),
              .value_axis = spine_system_->value_stream_stats(),
              .start_cycle = sst_round_start_cycle_,
              .end_cycle = device_end_cycle,
          };
          const std::uint32_t fallback_reason =
              spine_system_->reader_counters().range_task_fallback_reason;
          const std::vector<std::uint32_t> sources =
              spine_system_->restart_device_dirty_host_fallback();
          sst_host_handoffs_.push_back(SpineHostHandoffEvidence{
              .logical_round = sst_rounds_.size(),
              .fallback_reason = fallback_reason,
              .source_count = sources.size(),
              .host_list_read_bytes =
                  ((sources.size() + 3) / 4) * kSpineSortWordBytes,
              .host_control_cycles = 0,
              .host_control_timed = false,
              .device_attempt = std::move(device_attempt),
          });
          sst_current_frontier_ = sources;
          return false;
        }
        if (sst_waiting_dirty_ack_) {
          sst_waiting_dirty_ack_ = false;
          const bool finished =
              spine_system_->failed() || sst_pending_active_out_.empty() ||
              sst_rounds_.size() >= max_rounds_;
          if (finished) {
            if (begin_dynamic_sssp_update()) {
              return false;
            }
            write_result(!spine_system_->failed() &&
                         sst_pending_active_out_.empty());
            primaryComponentOKToEndSim();
            return true;
          }
          spine_system_->restart_read_compute(sst_pending_active_out_);
          sst_current_frontier_ = std::move(sst_pending_active_out_);
          sst_round_start_cycle_ = scheduler_.clock(0).completed_cycles;
          return false;
        }
        const std::vector<std::uint32_t> active_out =
            spine_system_->compute().next_active();
        sst_rounds_.push_back(SpineSsspRoundEvidence{
            .round = sst_rounds_.size(),
            .active_in = sst_current_frontier_,
            .reader_sources = spine_system_->reader_source_ids(),
            .active_out = active_out,
            .reader = spine_system_->reader_counters(),
            .compute = spine_system_->compute_counters(),
            .edge_axis = spine_system_->edge_stream_stats(),
            .value_axis = spine_system_->value_stream_stats(),
            .start_cycle = sst_round_start_cycle_,
            .end_cycle = scheduler_.clock(0).completed_cycles,
        });
        if (sst_rounds_.size() == 1 && !spine_system_->failed()) {
          sst_pending_active_out_ = active_out;
          spine_system_->start_dirty_ack();
          sst_waiting_dirty_ack_ = true;
          return false;
        }
        const bool finished = spine_system_->failed() || active_out.empty() ||
                              sst_rounds_.size() >= max_rounds_;
        if (finished) {
          if (begin_dynamic_sssp_update()) {
            return false;
          }
          write_result(!spine_system_->failed() && active_out.empty());
          primaryComponentOKToEndSim();
          return true;
        }
        spine_system_->restart_read_compute(active_out);
        sst_current_frontier_ = active_out;
        sst_round_start_cycle_ = scheduler_.clock(0).completed_cycles;
      }
    } else if (mode_ == "spine_vertical") {
      if (spine_system_->done() && spine_system_->idle() &&
          backend_->outstanding() == 0) {
        write_result(!spine_system_->failed());
        primaryComponentOKToEndSim();
        return true;
      }
    } else if (mode_ == "payload_roundtrip") {
      if (payload_round_trip_->done() && axi_->idle() && requests_->empty() &&
          responses_->empty() && backend_->outstanding() == 0) {
        write_result(!payload_round_trip_->failed());
        primaryComponentOKToEndSim();
        return true;
      }
    } else if (sink_->completed() == request_count_ && axi_->idle() &&
               requests_->empty() && responses_->empty()) {
      write_result(true);
      primaryComponentOKToEndSim();
      return true;
    }
    if (scheduler_.clock(0).completed_cycles >= max_cycles_) {
      write_result(false);
      output_.fatal(CALL_INFO, -1,
                    "online memory probe exceeded max_cycles=%llu\n",
                    static_cast<unsigned long long>(max_cycles_));
    }
    return false;
  }

  void on_memory_response(SST::Interfaces::StandardMem::Request *request) {
    backend_->on_response(request);
  }

  SST_ELI_REGISTER_COMPONENT(
      OnlineMemoryProbe, "spine_cycle", "OnlineMemoryProbe",
      SST_ELI_ELEMENT_VERSION(1, 0, 0),
      "Execution-driven AXI probe using online SST StandardMem HBM responses",
      COMPONENT_CATEGORY_MEMORY)

  SST_ELI_DOCUMENT_PARAMS(
      {"output", "JSON result path", "sst_memory_probe.json"},
      {"mode",
       "probe, payload_roundtrip, spine_vertical, spine_compute, spine_sssp, or "
       "spine_pagerank/spine_residual_pagerank/grasu_regraph_sssp",
       "probe"},
      {"workload", "Spine .slice workload path", ""},
      {"update_workload", "Optional positive incremental Spine .slice", ""},
      {"preload_workload", "Optional pre-existing Spine L0 .slice", ""},
      {"hot_vertices", "Comma-separated host hot-bitmap vertices", ""},
      {"source_vertex", "Spine SSSP source vertex", "0"},
      {"verbose", "Output verbosity", "0"},
      {"core_clock", "SST core clock", "141MHz"},
      {"core_mhz", "Matching C++ scheduler core frequency", "141.0"},
      {"requests", "Number of execution-driven AXI requests", "256"},
      {"request_bytes", "Bytes per AXI request", "64"},
      {"stride_bytes", "Address stride between requests", "64"},
      {"channels", "Number of HBM channel interfaces", "1"},
      {"channel_capacity_bytes", "Capacity of each HBM channel", "1073741824"},
      {"write_percent", "Deterministic write percentage", "0"},
      {"max_cycles", "Core-cycle timeout", "1000000"},
      {"max_rounds", "Maximum SSSP frontier rounds", "256"},
      {"pagerank_iterations", "Full PageRank iteration count", "1"},
      {"pagerank_damping", "Full PageRank damping factor", "0.85"},
      {"pagerank_epsilon", "Residual PageRank epsilon", "0.000001"},
      {"residual_max_iterations", "Residual PageRank iteration limit", "256"},
      {"pagerank_source_latency", "PageRank source-map latency", "3"},
      {"pagerank_source_ii", "PageRank source-map initiation interval", "1"},
      {"pagerank_source_capacity", "PageRank source-map capacity", "4"},
      {"pagerank_edge_latency", "PageRank edge-map latency", "1"},
      {"pagerank_edge_ii", "PageRank edge-map initiation interval", "1"},
      {"pagerank_edge_capacity", "PageRank edge-map capacity", "4"},
      {"pagerank_reduce_latency", "PageRank reduce latency", "2"},
      {"pagerank_reduce_ii", "PageRank reduce initiation interval", "1"},
      {"pagerank_reduce_capacity", "PageRank reduce capacity", "8"},
      {"pagerank_apply_latency", "PageRank apply latency", "3"},
      {"pagerank_apply_ii", "PageRank apply initiation interval", "1"},
      {"pagerank_apply_capacity", "PageRank apply capacity", "8"},
      {"device_dirty_source_limit", "DEVICE_DIRTY source capacity", "4096"},
      {"range_task_active_gate", "Exact-reader active-record gate", "16384"},
      {"range_task_capacity", "Exact-reader descriptor capacity", "65536"},
      {"range_task_payload_budget", "Exact-reader construction budget",
       "1048576"},
      {"fallback_replay_threshold", "HOST fallback replay threshold", "65536"},
      {"memory_request_window",
       "Coarse producer request window (greater than one is a what-if)", "1"},
      {"compute_memory_request_window",
       "Compute HLS parent-request window", "7"},
      {"compute_writeonly_request_window",
       "Compute HLS write-only parent-request window", "4"},
      {"compute_tiny_bram_read_latency",
       "Compute tiny-edge BRAM read latency", "2"},
      {"compute_vs_uram_read_latency",
       "Compute vertex-tile URAM read latency", "2"},
      {"compute_active_bram_read_latency",
       "Compute active-bitmap BRAM read latency", "2"},
      {"compute_onchip_pipeline_capacity",
       "Compute on-chip read pipeline capacity", "4"},
      {"compute_vs_bypass_depth", "Compute vertex-tile RAW bypass depth", "4"},
      {"reader_edge_pipeline_depth", "II=1 edge-loop in-flight credits", "32"},
      {"reader_edge_response_capacity", "Ordered edge response capacity", "32"},
      {"maintenance_count_scan_ii",
       "HLS count/precount scan initiation interval", "1"},
      {"maintenance_count_scan_tail_cycles",
       "HLS count/precount scan pipeline tail cycles", "19"},
      {"maintenance_l0_write_scan_ii", "Achieved HLS L0-write scan II", "24"},
      {"maintenance_l0_write_scan_tail_cycles",
       "Achieved HLS L0-write scan tail cycles", "42"},
      {"maintenance_scan_response_capacity",
       "Maintenance sorted-edge response/reorder capacity", "32"},
      {"spine_axi_profile",
       "Spine AXI profile: hls_split_9c08763 or legacy_uniform64",
       "hls_split_9c08763"},
      {"grasu_cache_segments_per_half", "GraSU cache segments per PMA half",
       "131072"},
      {"grasu_partition_vertices", "ReGraph destination partition size",
       "65536"},
      {"grasu_source_buffer_vertices", "ReGraph source-cache words", "4096"},
      {"grasu_edge_lanes", "PMA-native edge lanes", "4"},
      {"grasu_gather_banks", "ReGraph gather banks", "4"},
      {"grasu_source_state_channel", "ReGraph primary source-state HBM channel",
       "1"},
      {"grasu_source_state_mirror_channel",
       "ReGraph mirrored source-state HBM channel", "3"},
      {"grasu_apply_state_channel", "ReGraph apply-state HBM channel", "30"},
      {"grasu_axis_fifo_depth", "GraSU/ReGraph AXIS FIFO depth", "16"},
      {"grasu_gather_merger_fifo_depth", "Gather-to-merger AXIS FIFO depth",
       "16"},
      {"grasu_merger_apply_fifo_depth", "Merger-to-apply AXIS FIFO depth",
       "16"},
      {"grasu_apply_wrapper_fifo_depth", "Apply-to-wrapper AXIS FIFO depth",
       "16"},
      {"grasu_reader_buffer_batches", "PMA reader response batches", "32"},
      {"grasu_max_pending_requests", "AXI pending requests per port", "32"},
      {"grasu_max_outstanding_bursts", "AXI outstanding bursts per port",
       "32"},
      {"grasu_apply_request_window", "ReGraph apply AXI request window", "32"},
      {"grasu_apply_pipeline_latency", "ReGraph HLS apply pipeline depth",
       "100"},
      {"grasu_apply_pipeline_capacity", "ReGraph apply in-flight capacity",
       "100"},
      {"grasu_hbm_wrapper_pipeline_latency",
       "ReGraph HBM-wrapper write pipeline latency", "71"},
      {"grasu_hbm_wrapper_pipeline_capacity",
       "ReGraph HBM-wrapper in-flight capacity", "71"})

  SST_ELI_DOCUMENT_SUBCOMPONENT_SLOTS(
      {"memory", "One StandardMem interface per HBM channel",
       "SST::Interfaces::StandardMem"})

 private:
  bool begin_dynamic_sssp_update() {
    if (!dynamic_sssp_enabled_ || dynamic_sssp_started_ ||
        spine_system_->failed()) {
      return false;
    }
    const SsspComparison comparison = compare_sssp_result(
        spine_system_->compute().values(), sst_rounds_, cold_sssp_reference_);
    cold_value_mismatches_ = comparison.value_mismatches;
    cold_frontier_mismatches_ = comparison.frontier_mismatches;
    cold_final_values_ = spine_system_->compute().values();
    cold_rounds_ = sst_rounds_.size();
    cold_round_cycles_.clear();
    cold_round_cycles_.reserve(sst_rounds_.size());
    for (const SpineSsspRoundEvidence &round : sst_rounds_) {
      cold_round_cycles_.push_back(round.end_cycle - round.start_cycle);
    }
    const SpineL0Counters &maintenance =
        spine_system_->maintenance_counters();
    cold_maintenance_cycles_ =
        maintenance.end_cycle - maintenance.start_cycle;
    cold_maintenance_target_level_ = maintenance.target_level;
    cold_dirty_generation_after_ack_ =
        spine_system_->dirty_ack_counters().result.generation;
    cold_cycles_ = scheduler_.clock(0).completed_cycles;
    cold_backend_requests_ = backend_->accepted();

    if (dynamic_full_rebuild_) {
      spine_system_->restart_full_rebuild(dynamic_materialized_snapshot_);
    } else {
      spine_system_->restart_incremental_update(dynamic_update_workload_);
    }
    dynamic_sssp_started_ = true;
    dynamic_update_start_cycle_ = scheduler_.clock(0).completed_cycles;
    sst_rounds_.clear();
    sst_host_handoffs_.clear();
    sst_pending_active_out_.clear();
    sst_current_frontier_ = dynamic_full_rebuild_
                                ? std::vector<std::uint32_t>{source_vertex_}
                                : dynamic_update_sources_;
    sst_round_start_cycle_ = dynamic_update_start_cycle_;
    sst_waiting_dirty_ack_ = false;
    return true;
  }

  void write_result(bool success) {
    if (result_written_) {
      return;
    }
    result_written_ = true;
    std::ofstream result(result_path_);
    if (mode_ == "grasu_regraph_sssp") {
      const bool compute_available = grasu_compute_system_ != nullptr;
      const std::vector<std::uint32_t> distances =
          compute_available ? grasu_compute_system_->distances()
                            : std::vector<std::uint32_t>{};
      std::uint64_t mismatches =
          distances.size() == grasu_sssp_reference_.values.size() ? 0 : 1;
      for (std::size_t vertex = 0;
           vertex < std::min(distances.size(),
                             grasu_sssp_reference_.values.size());
           ++vertex) {
        mismatches +=
            distances[vertex] == grasu_sssp_reference_.values[vertex] ? 0 : 1;
      }
      const GraSuReGraphCounters compute =
          compute_available ? grasu_compute_system_->counters()
                            : GraSuReGraphCounters{};
      const GraSuUpdateCounters update =
          grasu_update_counters_captured_
              ? grasu_update_counters_
              : grasu_update_system_->counters();
      const bool passed = success && compute_available &&
                          !grasu_compute_system_->failed() && mismatches == 0;
      const bool normalized_profile =
          std::fabs(core_mhz_ - 150.0) < 1.0e-9 && channels_ == 32 &&
          grasu_config_.partition_vertices == 65'536 &&
          grasu_config_.edge_lanes == 4 && grasu_config_.gather_banks == 4;
      result << "{\n"
             << "  \"success\": " << (passed ? "true" : "false") << ",\n"
             << "  \"mode\": \"grasu_regraph_sssp\",\n"
             << "  \"claim_class\": \""
             << (normalized_profile ? "normalized_simulation"
                                    : "component_validation_simulation")
             << "\",\n"
             << "  \"timing_evidence\": \"structural_execution_driven\",\n"
             << "  \"backend\": \"sst_memHierarchy_dramsim3\",\n"
             << "  \"cycles\": " << scheduler_.clock(0).completed_cycles
             << ",\n"
             << "  \"update_cycles\": "
             << update.end_cycle - update.start_cycle << ",\n"
             << "  \"compute_cycles\": "
             << compute.end_cycle - compute.start_cycle << ",\n"
             << "  \"initial_edges\": " << grasu_initial_edges_ << ",\n"
             << "  \"updates\": " << grasu_update_edges_ << ",\n"
             << "  \"vertices\": " << grasu_layout_.vertices << ",\n"
             << "  \"partition_vertices\": "
             << grasu_config_.partition_vertices << ",\n"
             << "  \"edge_lanes\": " << grasu_config_.edge_lanes << ",\n"
             << "  \"gather_banks\": " << grasu_config_.gather_banks
             << ",\n"
             << "  \"source_state_channel\": "
             << grasu_config_.source_state_channel << ",\n"
             << "  \"source_state_mirror_channel\": "
             << grasu_config_.source_state_mirror_channel << ",\n"
             << "  \"apply_state_channel\": "
             << grasu_config_.vertex_state_channel << ",\n"
             << "  \"apply_request_window\": "
             << grasu_config_.apply_request_window << ",\n"
             << "  \"apply_pipeline_latency\": "
             << grasu_config_.apply_pipeline_latency << ",\n"
             << "  \"apply_pipeline_capacity\": "
             << grasu_config_.apply_pipeline_capacity << ",\n"
             << "  \"gather_merger_fifo_depth\": "
             << grasu_config_.gather_merger_fifo_depth << ",\n"
             << "  \"merger_apply_fifo_depth\": "
             << grasu_config_.merger_apply_fifo_depth << ",\n"
             << "  \"apply_wrapper_fifo_depth\": "
             << grasu_config_.apply_wrapper_fifo_depth << ",\n"
             << "  \"hbm_wrapper_pipeline_latency\": "
             << grasu_config_.hbm_wrapper_pipeline_latency << ",\n"
             << "  \"hbm_wrapper_pipeline_capacity\": "
             << grasu_config_.hbm_wrapper_pipeline_capacity << ",\n"
             << "  \"correctness_mismatches\": " << mismatches << ",\n"
             << "  \"supersteps\": " << compute.supersteps << ",\n"
             << "  \"update_binary_probes\": " << update.binary_probes
             << ",\n"
             << "  \"update_pma_reads\": " << update.pma_reads << ",\n"
             << "  \"update_pma_writes\": " << update.pma_writes << ",\n"
             << "  \"compute_row_reads\": " << compute.row_reads << ",\n"
             << "  \"compute_source_state_reads\": "
             << compute.source_state_reads << ",\n"
             << "  \"compute_source_state_writes\": "
             << compute.source_state_writes << ",\n"
             << "  \"compute_pma_segment_reads\": "
             << compute.pma_segment_reads << ",\n"
             << "  \"compute_edge_batches\": "
             << compute.edge_batches_scanned << ",\n"
             << "  \"compute_pma_slots\": " << compute.pma_slots_scanned
             << ",\n"
             << "  \"compute_live_edges\": " << compute.live_edges_scanned
             << ",\n"
             << "  \"compute_active_edges\": "
             << compute.active_edges_mapped << ",\n"
             << "  \"gather_reset_cycles\": "
             << compute.gather_reset_cycles << ",\n"
             << "  \"gather_merge_cycles\": "
             << compute.gather_merge_cycles << ",\n"
             << "  \"gather_output_stall_cycles\": "
             << compute.gather_output_stall_cycles << ",\n"
             << "  \"gather_bank_conflict_cycles\": "
             << compute.gather_bank_conflict_cycles << ",\n"
             << "  \"gather_rows_emitted\": "
             << compute.gather_rows_emitted << ",\n"
             << "  \"merger_rows_consumed\": "
             << compute.merger_rows_consumed << ",\n"
             << "  \"merger_bursts_emitted\": "
             << compute.merger_bursts_emitted << ",\n"
             << "  \"merger_output_stall_cycles\": "
             << compute.merger_output_stall_cycles << ",\n"
             << "  \"apply_state_reads\": " << compute.apply_state_reads
             << ",\n"
             << "  \"apply_state_writes\": " << compute.apply_state_writes
             << ",\n"
             << "  \"apply_input_bursts\": " << compute.apply_input_bursts
             << ",\n"
             << "  \"apply_output_stall_cycles\": "
             << compute.apply_output_stall_cycles << ",\n"
             << "  \"apply_read_window_stalls\": "
             << compute.apply_read_window_stalls << ",\n"
             << "  \"apply_pipeline_capacity_stalls\": "
             << compute.apply_pipeline_capacity_stalls << ",\n"
             << "  \"apply_write_window_stalls\": "
             << compute.apply_write_window_stalls << ",\n"
             << "  \"apply_max_reads_inflight\": "
             << compute.apply_max_reads_inflight << ",\n"
             << "  \"apply_max_pipeline_occupancy\": "
             << compute.apply_max_pipeline_occupancy << ",\n"
             << "  \"apply_max_writes_inflight\": "
             << compute.apply_max_writes_inflight << ",\n"
             << "  \"hbm_wrapper_input_bursts\": "
             << compute.hbm_wrapper_input_bursts << ",\n"
             << "  \"hbm_wrapper_pipeline_capacity_stalls\": "
             << compute.hbm_wrapper_pipeline_capacity_stalls << ",\n"
             << "  \"hbm_wrapper_write_window_stalls\": "
             << compute.hbm_wrapper_write_window_stalls << ",\n"
             << "  \"hbm_wrapper_max_pipeline_occupancy\": "
             << compute.hbm_wrapper_max_pipeline_occupancy << ",\n"
             << "  \"hbm_wrapper_max_writes_inflight\": "
             << compute.hbm_wrapper_max_writes_inflight << ",\n"
             << "  \"gather_merger_fifo_max_occupancy\": "
             << compute.gather_merger_fifo_max_occupancy << ",\n"
             << "  \"merger_apply_fifo_max_occupancy\": "
             << compute.merger_apply_fifo_max_occupancy << ",\n"
             << "  \"apply_wrapper_fifo_max_occupancy\": "
             << compute.apply_wrapper_fifo_max_occupancy << ",\n"
             << "  \"update_read_bytes\": "
             << update.update_read_bytes + update.row_read_bytes +
                    update.binary_read_bytes + update.pma_read_bytes
             << ",\n"
             << "  \"update_write_bytes\": " << update.pma_write_bytes
             << ",\n"
             << "  \"compute_read_bytes\": "
             << compute.row_read_bytes + compute.source_state_read_bytes +
                    compute.pma_read_bytes + compute.apply_read_bytes
             << ",\n"
             << "  \"compute_write_bytes\": "
             << compute.apply_write_bytes + compute.source_state_write_bytes
             << ",\n"
             << "  \"axi_backend_stalls\": "
             << update.axi_backend_submit_stalls +
                    compute.axi_backend_submit_stalls
             << ",\n"
             << "  \"axis_push_stalls\": "
             << update.axis_push_stalls + compute.axis_push_stalls << ",\n"
             << "  \"backend_requests\": " << backend_->accepted()
             << ",\n"
             << "  \"backend_submit_stalls\": "
             << backend_->submit_stalls() << ",\n"
             << "  \"backend_response_queue_stalls\": "
             << backend_->response_queue_stalls() << ",\n"
             << "  \"backend_max_outstanding\": "
             << backend_->max_outstanding() << "\n"
             << "}\n";
      output_.output(
          "completed GraSU + PMA-native ReGraph in %llu core cycles -> %s\n",
          static_cast<unsigned long long>(
              scheduler_.clock(0).completed_cycles),
          result_path_.c_str());
      return;
    }
    if (mode_ == "spine_residual_pagerank") {
      std::vector<float> actual_ranks;
      std::vector<float> actual_residuals;
      actual_ranks.reserve(pagerank_system_->compute().rank_words().size());
      actual_residuals.reserve(
          pagerank_system_->compute().residual_words().size());
      float rank_sum = 0.0F;
      float residual_l1 = 0.0F;
      float max_abs_error = 0.0F;
      std::uint64_t mismatches = 0;
      for (std::size_t vertex = 0;
           vertex < pagerank_system_->compute().rank_words().size(); ++vertex) {
        const float rank = GraphAlgorithmPolicy::word_to_float(
            pagerank_system_->compute().rank_words()[vertex]);
        const float residual = GraphAlgorithmPolicy::word_to_float(
            pagerank_system_->compute().residual_words()[vertex]);
        actual_ranks.push_back(rank);
        actual_residuals.push_back(residual);
        rank_sum += rank;
        residual_l1 += std::fabs(residual);
        if (vertex >= residual_pagerank_reference_.ranks.size()) {
          ++mismatches;
          continue;
        }
        const float rank_error =
            std::fabs(rank - residual_pagerank_reference_.ranks[vertex]);
        const float residual_error = std::fabs(
            residual - residual_pagerank_reference_.residuals[vertex]);
        max_abs_error =
            std::max({max_abs_error, rank_error, residual_error});
        if (rank_error > 1.0e-5F || residual_error > 1.0e-5F) {
          ++mismatches;
        }
      }
      const auto &maintenance = pagerank_system_->maintenance_counters();
      const auto &reader = pagerank_system_->reader_counters();
      const auto &compute = pagerank_system_->compute_counters();
      const auto &pipeline = pagerank_system_->compute().pipeline_counters();
      const bool frontier_match =
          pagerank_frontier_in_sizes_ ==
              residual_pagerank_reference_.frontier_in_sizes &&
          pagerank_frontier_out_sizes_ ==
              residual_pagerank_reference_.frontier_out_sizes;
      bool memory_ledger_match =
          pagerank_compute_requests_per_iteration_.size() ==
          pagerank_frontier_in_sizes_.size();
      for (std::size_t round = 0;
           memory_ledger_match &&
           round < pagerank_compute_requests_per_iteration_.size(); ++round) {
        memory_ledger_match =
            pagerank_compute_requests_per_iteration_[round] ==
            5 * pagerank_frontier_in_sizes_[round] + 2 * actual_ranks.size();
      }
      const bool converged = pagerank_system_->compute().next_active().empty();
      const bool passed = success && residual_pagerank_reference_.converged &&
                          converged && frontier_match && memory_ledger_match &&
                          mismatches == 0 && max_abs_error <= 1.0e-5F;
      result
          << "{\n"
          << "  \"success\": " << (passed ? "true" : "false") << ",\n"
          << "  \"mode\": \"spine_residual_pagerank\",\n"
          << "  \"backend\": \"sst_memHierarchy_dramsim3\",\n"
          << "  \"spine_axi_profile\": \"" << spine_axi_profile_id_ << "\",\n"
          << "  \"timing_evidence\": \"provisional_algorithm_pipeline\",\n"
          << "  \"cycles\": " << scheduler_.clock(0).completed_cycles << ",\n"
          << "  \"input_edges\": " << spine_expected_edges_ << ",\n"
          << "  \"vertices\": " << actual_ranks.size() << ",\n"
          << "  \"converged\": " << (converged ? "true" : "false") << ",\n"
          << "  \"iterations\": " << pagerank_completed_iterations_ << ",\n"
          << "  \"pagerank_damping\": " << pagerank_damping_ << ",\n"
          << "  \"pagerank_epsilon\": " << pagerank_epsilon_ << ",\n"
          << "  \"residual_max_iterations\": " << residual_max_iterations_
          << ",\n"
          << "  \"pagerank_source_latency\": "
          << pagerank_pipeline_config_.source_map.latency_cycles << ",\n"
          << "  \"pagerank_source_ii\": "
          << pagerank_pipeline_config_.source_map.initiation_interval << ",\n"
          << "  \"pagerank_source_capacity\": "
          << pagerank_pipeline_config_.source_map.capacity << ",\n"
          << "  \"pagerank_edge_latency\": "
          << pagerank_pipeline_config_.edge_map.latency_cycles << ",\n"
          << "  \"pagerank_edge_ii\": "
          << pagerank_pipeline_config_.edge_map.initiation_interval << ",\n"
          << "  \"pagerank_edge_capacity\": "
          << pagerank_pipeline_config_.edge_map.capacity << ",\n"
          << "  \"pagerank_reduce_latency\": "
          << pagerank_pipeline_config_.reduce.latency_cycles << ",\n"
          << "  \"pagerank_reduce_ii\": "
          << pagerank_pipeline_config_.reduce.initiation_interval << ",\n"
          << "  \"pagerank_reduce_capacity\": "
          << pagerank_pipeline_config_.reduce.capacity << ",\n"
          << "  \"pagerank_apply_latency\": "
          << pagerank_pipeline_config_.apply.latency_cycles << ",\n"
          << "  \"pagerank_apply_ii\": "
          << pagerank_pipeline_config_.apply.initiation_interval << ",\n"
          << "  \"pagerank_apply_capacity\": "
          << pagerank_pipeline_config_.apply.capacity << ",\n"
          << "  \"compute_memory_request_window\": "
          << compute_memory_request_window_ << ",\n"
          << "  \"maintenance_count_scan_ii\": " << maintenance_count_scan_ii_
          << ",\n"
          << "  \"maintenance_count_scan_tail_cycles\": "
          << maintenance_count_scan_tail_cycles_ << ",\n"
          << "  \"maintenance_l0_write_scan_ii\": "
          << maintenance_l0_write_scan_ii_ << ",\n"
          << "  \"maintenance_l0_write_scan_tail_cycles\": "
          << maintenance_l0_write_scan_tail_cycles_ << ",\n"
          << "  \"maintenance_scan_response_capacity\": "
          << maintenance_scan_response_capacity_ << ",\n"
          << "  \"correctness_mismatches\": " << mismatches << ",\n"
          << "  \"frontier_match\": "
          << (frontier_match ? "true" : "false") << ",\n"
          << "  \"memory_ledger_match\": "
          << (memory_ledger_match ? "true" : "false") << ",\n"
          << "  \"max_abs_error\": " << max_abs_error << ",\n"
          << "  \"rank_sum\": " << rank_sum << ",\n"
          << "  \"residual_l1\": " << residual_l1 << ",\n"
          << "  \"final_active\": "
          << pagerank_system_->compute().next_active().size() << ",\n"
          << "  \"maintenance_cycles\": "
          << maintenance.end_cycle - maintenance.start_cycle << ",\n"
          << "  \"maintenance_persisted_edges\": "
          << maintenance.persisted_edges << ",\n"
          << "  \"reader_edges\": " << reader.edges_emitted << ",\n"
          << "  \"reader_source_requests\": " << reader.source_requests
          << ",\n"
          << "  \"reader_source_responses\": " << reader.source_responses
          << ",\n"
          << "  \"reader_protocol_status\": "
          << reader.source_protocol_status << ",\n"
          << "  \"compute_edges\": " << compute.edges_received << ",\n"
          << "  \"compute_vertices_applied\": " << compute.vertices_applied
          << ",\n"
          << "  \"compute_vertices_activated\": "
          << compute.vertices_activated << ",\n"
          << "  \"compute_memory_requests\": "
          << compute.memory_requests_issued << ",\n"
          << "  \"compute_primary_read_bytes\": "
          << compute.primary_read_bytes << ",\n"
          << "  \"compute_primary_write_bytes\": "
          << compute.primary_write_bytes << ",\n"
          << "  \"compute_auxiliary_read_bytes\": "
          << compute.auxiliary_read_bytes << ",\n"
          << "  \"compute_auxiliary_write_bytes\": "
          << compute.auxiliary_write_bytes << ",\n"
          << "  \"compute_degree_read_bytes\": "
          << compute.degree_read_bytes << ",\n"
          << "  \"source_map_operations\": " << pipeline.source_map.completed
          << ",\n"
          << "  \"reduce_operations\": " << pipeline.reduce.completed << ",\n"
          << "  \"apply_operations\": " << pipeline.apply.completed << ",\n"
          << "  \"backend_requests\": " << backend_->accepted() << ",\n"
          << "  \"backend_submit_stalls\": " << backend_->submit_stalls()
          << ",\n"
          << "  \"backend_response_queue_stalls\": "
          << backend_->response_queue_stalls() << ",\n"
          << "  \"backend_max_outstanding\": " << backend_->max_outstanding()
          << ",\n"
          << "  \"iteration_cycles\": ";
      write_json_array(result, pagerank_iteration_cycles_);
      result << ",\n  \"frontier_in_sizes\": ";
      write_json_array(result, pagerank_frontier_in_sizes_);
      result << ",\n  \"frontier_out_sizes\": ";
      write_json_array(result, pagerank_frontier_out_sizes_);
      result << ",\n  \"compute_requests_per_iteration\": ";
      write_json_array(result, pagerank_compute_requests_per_iteration_);
      result << ",\n  \"ranks\": ";
      write_json_array(result, actual_ranks);
      result << ",\n  \"residuals\": ";
      write_json_array(result, actual_residuals);
      result << "\n}\n";
      output_.output(
          "completed %zu SST residual PageRank rounds in %llu cycles -> %s\n",
          pagerank_completed_iterations_,
          static_cast<unsigned long long>(scheduler_.clock(0).completed_cycles),
          result_path_.c_str());
      return;
    }
    if (mode_ == "spine_pagerank") {
      std::vector<float> actual;
      actual.reserve(pagerank_system_->compute().rank_words().size());
      float rank_sum = 0.0F;
      float max_abs_error = 0.0F;
      std::uint64_t mismatches = 0;
      for (std::size_t vertex = 0;
           vertex < pagerank_system_->compute().rank_words().size(); ++vertex) {
        const float rank = GraphAlgorithmPolicy::word_to_float(
            pagerank_system_->compute().rank_words()[vertex]);
        actual.push_back(rank);
        rank_sum += rank;
        if (vertex >= pagerank_reference_.size()) {
          ++mismatches;
          continue;
        }
        const float error = std::fabs(rank - pagerank_reference_[vertex]);
        max_abs_error = std::max(max_abs_error, error);
        if (error > 1.0e-5F) {
          ++mismatches;
        }
      }
      const auto &maintenance = pagerank_system_->maintenance_counters();
      const auto &reader = pagerank_system_->reader_counters();
      const auto &compute = pagerank_system_->compute_counters();
      const auto &pipeline = pagerank_system_->compute().pipeline_counters();
      const bool passed = success &&
                          actual.size() == pagerank_reference_.size() &&
                          mismatches == 0 && max_abs_error <= 1.0e-5F;
      result
          << "{\n"
          << "  \"success\": " << (passed ? "true" : "false") << ",\n"
          << "  \"mode\": \"spine_pagerank\",\n"
          << "  \"backend\": \"sst_memHierarchy_dramsim3\",\n"
          << "  \"spine_axi_profile\": \"" << spine_axi_profile_id_ << "\",\n"
          << "  \"timing_evidence\": \"provisional_algorithm_pipeline\",\n"
          << "  \"cycles\": " << scheduler_.clock(0).completed_cycles << ",\n"
          << "  \"input_edges\": " << spine_expected_edges_ << ",\n"
          << "  \"vertices\": " << actual.size() << ",\n"
          << "  \"pagerank_iterations\": " << pagerank_iterations_ << ",\n"
          << "  \"pagerank_completed_iterations\": "
          << pagerank_completed_iterations_ << ",\n"
          << "  \"pagerank_damping\": " << pagerank_damping_ << ",\n"
          << "  \"pagerank_source_latency\": "
          << pagerank_pipeline_config_.source_map.latency_cycles << ",\n"
          << "  \"pagerank_source_ii\": "
          << pagerank_pipeline_config_.source_map.initiation_interval << ",\n"
          << "  \"pagerank_source_capacity\": "
          << pagerank_pipeline_config_.source_map.capacity << ",\n"
          << "  \"pagerank_edge_latency\": "
          << pagerank_pipeline_config_.edge_map.latency_cycles << ",\n"
          << "  \"pagerank_edge_ii\": "
          << pagerank_pipeline_config_.edge_map.initiation_interval << ",\n"
          << "  \"pagerank_edge_capacity\": "
          << pagerank_pipeline_config_.edge_map.capacity << ",\n"
          << "  \"pagerank_reduce_latency\": "
          << pagerank_pipeline_config_.reduce.latency_cycles << ",\n"
          << "  \"pagerank_reduce_ii\": "
          << pagerank_pipeline_config_.reduce.initiation_interval << ",\n"
          << "  \"pagerank_reduce_capacity\": "
          << pagerank_pipeline_config_.reduce.capacity << ",\n"
          << "  \"pagerank_apply_latency\": "
          << pagerank_pipeline_config_.apply.latency_cycles << ",\n"
          << "  \"pagerank_apply_ii\": "
          << pagerank_pipeline_config_.apply.initiation_interval << ",\n"
          << "  \"pagerank_apply_capacity\": "
          << pagerank_pipeline_config_.apply.capacity << ",\n"
          << "  \"compute_memory_request_window\": "
          << compute_memory_request_window_ << ",\n"
          << "  \"maintenance_count_scan_ii\": " << maintenance_count_scan_ii_
          << ",\n"
          << "  \"maintenance_count_scan_tail_cycles\": "
          << maintenance_count_scan_tail_cycles_ << ",\n"
          << "  \"maintenance_l0_write_scan_ii\": "
          << maintenance_l0_write_scan_ii_ << ",\n"
          << "  \"maintenance_l0_write_scan_tail_cycles\": "
          << maintenance_l0_write_scan_tail_cycles_ << ",\n"
          << "  \"maintenance_scan_response_capacity\": "
          << maintenance_scan_response_capacity_ << ",\n"
          << "  \"correctness_mismatches\": " << mismatches << ",\n"
          << "  \"max_abs_error\": " << max_abs_error << ",\n"
          << "  \"rank_sum\": " << rank_sum << ",\n"
          << "  \"maintenance_cycles\": "
          << maintenance.end_cycle - maintenance.start_cycle << ",\n"
          << "  \"maintenance_persisted_edges\": "
          << maintenance.persisted_edges << ",\n"
          << "  \"reader_edges\": " << reader.edges_emitted << ",\n"
          << "  \"reader_graph_payload_bytes\": "
          << reader.graph_edge_payload_read_bytes << ",\n"
          << "  \"reader_source_requests\": " << reader.source_requests << ",\n"
          << "  \"reader_source_responses\": " << reader.source_responses
          << ",\n"
          << "  \"reader_source_windows\": " << reader.source_request_windows
          << ",\n"
          << "  \"reader_protocol_status\": " << reader.source_protocol_status
          << ",\n"
          << "  \"compute_edges\": " << compute.edges_received << ",\n"
          << "  \"compute_vertices_applied\": " << compute.vertices_applied
          << ",\n"
          << "  \"compute_memory_requests\": " << compute.memory_requests_issued
          << ",\n"
          << "  \"compute_primary_read_bytes\": " << compute.primary_read_bytes
          << ",\n"
          << "  \"compute_primary_write_bytes\": "
          << compute.primary_write_bytes << ",\n"
          << "  \"compute_degree_read_bytes\": " << compute.degree_read_bytes
          << ",\n"
          << "  \"source_map_operations\": " << pipeline.source_map.completed
          << ",\n"
          << "  \"reduce_operations\": " << pipeline.reduce.completed << ",\n"
          << "  \"apply_operations\": " << pipeline.apply.completed << ",\n"
          << "  \"edge_axis_transfers\": "
          << pagerank_system_->edge_stream_stats().pushes << ",\n"
          << "  \"edge_axis_push_stalls\": "
          << pagerank_system_->edge_stream_stats().push_stalls << ",\n"
          << "  \"value_axis_transfers\": "
          << pagerank_system_->value_stream_stats().pushes << ",\n"
          << "  \"dangling_mass\": "
          << pagerank_system_->compute().dangling_mass() << ",\n"
          << "  \"dangling_share\": "
          << pagerank_system_->compute().dangling_share() << ",\n"
          << "  \"iteration_error\": "
          << pagerank_system_->compute().iteration_error() << ",\n"
          << "  \"backend_requests\": " << backend_->accepted() << ",\n"
          << "  \"backend_submit_stalls\": " << backend_->submit_stalls()
          << ",\n"
          << "  \"backend_response_queue_stalls\": "
          << backend_->response_queue_stalls() << ",\n"
          << "  \"backend_max_outstanding\": " << backend_->max_outstanding()
          << ",\n"
          << "  \"iteration_cycles\": ";
      write_json_array(result, pagerank_iteration_cycles_);
      result << ",\n  \"ranks\": ";
      write_json_array(result, actual);
      result << ",\n  \"reference_ranks\": ";
      write_json_array(result, pagerank_reference_);
      result << "\n}\n";
      output_.output(
          "completed %zu SST Full PageRank iteration(s) in %llu cycles -> %s\n",
          pagerank_completed_iterations_,
          static_cast<unsigned long long>(scheduler_.clock(0).completed_cycles),
          result_path_.c_str());
      return;
    }
    if (mode_ == "payload_roundtrip") {
      const auto &stats = axi_->stats();
      const bool passed = success && !payload_round_trip_->failed() &&
                          stats.zero_filled_write_bytes == 0;
      result << "{\n"
             << "  \"success\": " << (passed ? "true" : "false") << ",\n"
             << "  \"mode\": \"payload_roundtrip\",\n"
             << "  \"backend\": \"sst_memHierarchy_dramsim3\",\n"
             << "  \"cycles\": " << scheduler_.clock(0).completed_cycles
             << ",\n"
             << "  \"payload_bytes\": " << payload_round_trip_->bytes() << ",\n"
             << "  \"axi_bursts\": " << stats.bursts_accepted << ",\n"
             << "  \"axi_beats\": " << stats.beats_issued << ",\n"
             << "  \"axi_read_bytes\": " << stats.read_bytes << ",\n"
             << "  \"axi_write_bytes\": " << stats.write_bytes << ",\n"
             << "  \"zero_filled_write_bytes\": "
             << stats.zero_filled_write_bytes << ",\n"
             << "  \"backend_requests\": " << backend_->accepted() << "\n"
             << "}\n";
      output_.output(
          "completed SST payload round trip in %llu cycles -> %s\n",
          static_cast<unsigned long long>(scheduler_.clock(0).completed_cycles),
          result_path_.c_str());
      return;
    }
    if (mode_ == "spine_compute") {
      std::uint64_t mismatches = 0;
      std::unordered_set<std::uint32_t> expected_frontier;
      for (const auto &[vertex, expected] : expected_distances_) {
        if (spine_compute_->values().at(vertex) != expected) {
          ++mismatches;
        }
        const std::uint32_t initial =
            vertex == source_vertex_ ? 0 : SpineSplitSsspCompute::kInfinity;
        if (expected < initial) {
          expected_frontier.insert(vertex);
        }
      }
      const std::unordered_set<std::uint32_t> actual_frontier(
          spine_compute_->next_active().begin(),
          spine_compute_->next_active().end());
      std::uint64_t frontier_mismatches = 0;
      for (const std::uint32_t vertex : expected_frontier) {
        if (!actual_frontier.contains(vertex)) {
          ++frontier_mismatches;
        }
      }
      for (const std::uint32_t vertex : actual_frontier) {
        if (!expected_frontier.contains(vertex)) {
          ++frontier_mismatches;
        }
      }
      const bool passed =
          success && mismatches == 0 && frontier_mismatches == 0 &&
          actual_frontier.size() == spine_compute_->next_active().size();
      const auto &compute = spine_compute_->counters();
      const auto &axis = spine_edge_stream_->stats();
      result << "{\n"
             << "  \"success\": " << (passed ? "true" : "false") << ",\n"
             << "  \"mode\": \"spine_compute\",\n"
             << "  \"backend\": \"sst_memHierarchy_dramsim3\",\n"
             << "  \"spine_axi_profile\": \"" << spine_axi_profile_id_
             << "\",\n"
             << "  \"axi_vertex_state_data_width_bytes\": "
             << spine_axi_profile_.vertex_state_bytes << ",\n"
             << "  \"axi_active_out_data_width_bytes\": "
             << spine_axi_profile_.active_out_bytes << ",\n"
             << "  \"axi_active_bitmap_data_width_bytes\": "
             << spine_axi_profile_.active_bitmap_bytes << ",\n"
             << "  \"cycles\": " << scheduler_.clock(0).completed_cycles
             << ",\n"
             << "  \"input_edges\": " << spine_expected_edges_ << ",\n"
             << "  \"correctness_mismatches\": " << mismatches << ",\n"
             << "  \"frontier_mismatches\": " << frontier_mismatches << ",\n"
             << "  \"expected_frontier\": " << expected_frontier.size() << ",\n"
             << "  \"next_active\": " << spine_compute_->next_active().size()
             << ",\n"
             << "  \"compute_fast_tiles\": " << compute.fast_path_tiles << ",\n"
             << "  \"compute_full_tiles\": " << compute.full_path_tiles << ",\n"
             << "  \"compute_processed_edges\": " << compute.processed_edges
             << ",\n"
             << "  \"compute_gathered_words\": "
             << compute.gathered_vertex_words << ",\n"
             << "  \"compute_swept_words\": " << compute.swept_vertex_words
             << ",\n"
             << "  \"compute_scattered_words\": "
             << compute.scattered_vertex_words << ",\n"
             << "  \"compute_tiny_buffer_writes\": "
             << compute.tiny_buffer_writes << ",\n"
             << "  \"compute_tiny_buffer_reads\": "
             << compute.tiny_buffer_reads << ",\n"
             << "  \"compute_vs_tile_reads\": " << compute.vs_tile_reads
             << ",\n"
             << "  \"compute_vs_tile_writes\": " << compute.vs_tile_writes
             << ",\n"
             << "  \"compute_tile_active_clear_words\": "
             << compute.tile_active_clear_words << ",\n"
             << "  \"compute_tile_active_clear_lane_writes\": "
             << compute.tile_active_clear_lane_writes << ",\n"
             << "  \"compute_tile_active_mark_writes\": "
             << compute.tile_active_mark_writes << ",\n"
             << "  \"compute_sparse_store_scan_words\": "
             << compute.sparse_store_scan_words << ",\n"
             << "  \"compute_sparse_store_lane_reads\": "
             << compute.sparse_store_lane_reads << ",\n"
             << "  \"compute_sparse_store_bit_cycles\": "
             << compute.sparse_store_bit_cycles << ",\n"
             << "  \"compute_active_emit_scan_words\": "
             << compute.active_emit_scan_words << ",\n"
             << "  \"compute_active_emit_lane_reads\": "
             << compute.active_emit_lane_reads << ",\n"
             << "  \"compute_active_emit_lane_writes\": "
             << compute.active_emit_lane_writes << ",\n"
             << "  \"compute_active_emit_bit_cycles\": "
             << compute.active_emit_bit_cycles << ",\n"
             << "  \"compute_on_chip_controller_cycles\": "
             << compute.on_chip_controller_cycles << ",\n"
             << "  \"compute_memory_request_window\": "
             << compute_memory_request_window_ << ",\n"
             << "  \"compute_writeonly_request_window\": "
             << compute_writeonly_request_window_ << ",\n"
             << "  \"compute_tiny_bram_read_latency\": "
             << compute_on_chip_profile_.tiny_bram_read_latency << ",\n"
             << "  \"compute_vs_uram_read_latency\": "
             << compute_on_chip_profile_.vs_uram_read_latency << ",\n"
             << "  \"compute_active_bram_read_latency\": "
             << compute_on_chip_profile_.active_bram_read_latency << ",\n"
             << "  \"compute_onchip_pipeline_capacity\": "
             << compute_on_chip_profile_.pipeline_capacity << ",\n"
             << "  \"compute_vs_bypass_depth\": "
             << compute_on_chip_profile_.vs_bypass_depth << ",\n"
             << "  \"compute_memory_requests_issued\": "
             << compute.memory_requests_issued << ",\n"
             << "  \"compute_memory_requests_completed\": "
             << compute.memory_requests_completed << ",\n"
             << "  \"compute_memory_window_stall_cycles\": "
             << compute.memory_window_stall_cycles << ",\n"
             << "  \"compute_memory_dependency_stall_cycles\": "
             << compute.memory_dependency_stall_cycles << ",\n"
             << "  \"compute_memory_request_fifo_stall_cycles\": "
             << compute.memory_request_fifo_stall_cycles << ",\n"
             << "  \"compute_max_memory_requests_inflight\": "
             << compute.max_memory_requests_inflight << ",\n"
             << "  \"compute_max_vertex_requests_inflight\": "
             << compute.max_vertex_requests_inflight << ",\n"
             << "  \"compute_max_active_out_requests_inflight\": "
             << compute.max_active_out_requests_inflight << ",\n"
             << "  \"compute_max_active_memory_ports\": "
             << compute.max_active_memory_ports << ",\n"
             << "  \"compute_memory_cross_port_overlap_cycles\": "
             << compute.memory_cross_port_overlap_cycles << ",\n"
             << "  \"compute_max_memory_responses_per_cycle\": "
             << compute.max_memory_responses_completed_per_cycle << ",\n"
             << "  \"compute_multi_port_response_cycles\": "
             << compute.multi_port_response_cycles << ",\n"
             << "  \"compute_controller_memory_overlap_cycles\": "
             << compute.controller_memory_overlap_cycles << ",\n"
             << "  \"compute_controller_memory_stall_cycles\": "
             << compute.controller_memory_stall_cycles << ",\n"
             << "  \"compute_sparse_store_writes_generated\": "
             << compute.sparse_store_writes_generated << ",\n"
             << "  \"compute_active_emit_writes_generated\": "
             << compute.active_emit_writes_generated << ",\n"
             << "  \"compute_tiny_bram_read_requests\": "
             << compute.tiny_bram_read_requests << ",\n"
             << "  \"compute_tiny_bram_write_requests\": "
             << compute.tiny_bram_write_requests << ",\n"
             << "  \"compute_vs_uram_read_requests\": "
             << compute.vs_uram_read_requests << ",\n"
             << "  \"compute_vs_uram_write_requests\": "
             << compute.vs_uram_write_requests << ",\n"
             << "  \"compute_active_bram_read_requests\": "
             << compute.active_bram_read_requests << ",\n"
             << "  \"compute_active_bram_write_requests\": "
             << compute.active_bram_write_requests << ",\n"
             << "  \"compute_on_chip_read_wait_cycles\": "
             << compute.on_chip_read_wait_cycles << ",\n"
             << "  \"compute_on_chip_pipeline_stall_cycles\": "
             << compute.on_chip_pipeline_stall_cycles << ",\n"
             << "  \"compute_vs_bypass_hits\": "
             << compute.vs_bypass_hits << ",\n"
             << "  \"compute_vs_bypass_misses\": "
             << compute.vs_bypass_misses << ",\n"
             << "  \"compute_max_tiny_reads_inflight\": "
             << compute.max_tiny_reads_inflight << ",\n"
             << "  \"compute_max_vs_reads_inflight\": "
             << compute.max_vs_reads_inflight << ",\n"
             << "  \"compute_full_tile_read_beats\": "
             << compute.full_tile_read_beats << ",\n"
             << "  \"compute_full_tile_read_words\": "
             << compute.full_tile_read_words << ",\n"
             << "  \"compute_full_tile_read_wait_cycles\": "
             << compute.full_tile_read_wait_cycles << ",\n"
             << "  \"compute_full_tile_stream_errors\": "
             << compute.full_tile_stream_error_count << ",\n"
             << "  \"compute_cross_tile_write_overlap_cycles\": "
             << compute.cross_tile_write_overlap_cycles << ",\n"
             << "  \"compute_max_cross_tile_writes_inflight\": "
             << compute.max_cross_tile_writes_inflight << ",\n"
             << "  \"compute_full_buffer_replay_edges\": "
             << compute.full_buffer_replay_edges << ",\n"
             << "  \"compute_full_overflow_edges\": "
             << compute.full_overflow_edges << ",\n"
             << "  \"compute_full_stream_edges\": " << compute.full_stream_edges
             << ",\n"
             << "  \"compute_vertex_read_bytes\": " << compute.vertex_read_bytes
             << ",\n"
             << "  \"compute_vertex_write_bytes\": "
             << compute.vertex_write_bytes << ",\n"
             << "  \"compute_vertex_payload_read_bytes\": "
             << compute.vertex_payload_read_bytes << ",\n"
             << "  \"compute_vertex_payload_write_bytes\": "
             << compute.vertex_payload_write_bytes << ",\n"
             << "  \"compute_active_out_write_bytes\": "
             << compute.active_out_write_bytes << ",\n"
             << "  \"edge_axis_transfers\": " << axis.pushes << ",\n"
             << "  \"edge_axis_max_occupancy\": " << axis.max_occupancy << ",\n"
             << "  \"edge_axis_push_stalls\": " << axis.push_stalls << ",\n"
             << "  \"backend_requests\": " << backend_->accepted() << ",\n"
             << "  \"backend_submit_stalls\": " << backend_->submit_stalls()
             << ",\n"
             << "  \"backend_response_queue_stalls\": "
             << backend_->response_queue_stalls() << ",\n"
             << "  \"backend_max_outstanding\": " << backend_->max_outstanding()
             << "\n"
             << "}\n";
      output_.output(
          "completed Spine compute microbenchmark in %llu core cycles -> %s\n",
          static_cast<unsigned long long>(scheduler_.clock(0).completed_cycles),
          result_path_.c_str());
      return;
    }
    if (mode_ == "spine_sssp") {
      const auto &actual_values = spine_system_->compute().values();
      const SsspReference &execution_reference =
          dynamic_sssp_started_ && !dynamic_full_rebuild_
              ? dynamic_sssp_reference_
              : sssp_reference_;
      const SsspComparison comparison =
          compare_sssp_result(actual_values, sst_rounds_, execution_reference);
      const std::uint64_t mismatches = comparison.value_mismatches;
      const std::uint64_t frontier_mismatches =
          comparison.frontier_mismatches;
      const std::uint64_t full_recompute_mismatches =
          dynamic_sssp_started_
              ? compare_sssp_result(actual_values, {}, sssp_reference_)
                    .value_mismatches
              : mismatches;
      const bool converged =
          !sst_rounds_.empty() && sst_rounds_.back().active_out.empty();
      const bool passed =
          success && converged && mismatches == 0 &&
          full_recompute_mismatches == 0 && frontier_mismatches == 0 &&
          (!dynamic_sssp_enabled_ ||
           (dynamic_sssp_started_ && cold_value_mismatches_ == 0 &&
            cold_frontier_mismatches_ == 0));
      std::vector<std::size_t> frontier_in_sizes;
      std::vector<std::size_t> frontier_out_sizes;
      std::vector<std::uint64_t> processed_edges;
      std::vector<std::uint64_t> round_cycles;
      std::vector<std::uint64_t> reader_graph_bytes;
      std::vector<std::uint64_t> reader_graph_index_payload_bytes;
      std::vector<std::uint64_t> reader_graph_payload_bytes;
      std::vector<std::uint64_t> reader_construction_payload_bytes;
      std::vector<std::uint64_t> reader_replay_payload_bytes;
      std::vector<std::uint64_t> reader_graph_index_bitmap_misses;
      std::vector<std::uint64_t> reader_range_tasks;
      std::vector<std::uint64_t> reader_range_row_lookups;
      std::vector<std::uint64_t> reader_range_level_checks;
      std::vector<std::uint64_t> reader_range_construction_payloads;
      std::vector<std::uint64_t> reader_range_replay_payloads;
      std::vector<std::uint64_t> reader_range_active_records;
      std::vector<std::uint64_t> reader_range_family_probes;
      std::vector<std::uint64_t> reader_range_family_skips;
      std::vector<std::uint64_t> reader_fallback_partitions;
      std::vector<std::uint64_t> reader_fallback_forced_dense_partitions;
      std::vector<std::uint64_t> reader_fallback_active_record_reads;
      std::vector<std::uint64_t> reader_fallback_row_lookups;
      std::vector<std::uint64_t> reader_fallback_replay_edges;
      std::vector<std::uint32_t> reader_range_paths;
      std::vector<std::uint32_t> reader_range_fallback_reasons;
      std::vector<std::uint32_t> reader_range_errors;
      std::vector<std::uint64_t> reader_metadata_bytes;
      std::vector<std::uint64_t> reader_metadata_write_bytes;
      std::vector<std::uint64_t> reader_result_write_bytes;
      std::vector<std::uint64_t> reader_active_bin_bytes;
      std::vector<std::uint64_t> reader_dirty_list_bytes;
      std::vector<std::uint64_t> reader_dirty_bitmap_bytes;
      std::vector<std::uint64_t> reader_memory_requests_issued;
      std::vector<std::uint64_t> reader_memory_requests_completed;
      std::vector<std::uint64_t> reader_memory_window_stalls;
      std::vector<std::uint64_t> reader_memory_dependency_stalls;
      std::vector<std::uint64_t> reader_memory_request_fifo_stalls;
      std::vector<std::size_t> reader_max_memory_requests_inflight;
      std::vector<std::uint64_t> reader_construction_pipeline_requests;
      std::vector<std::uint64_t> reader_construction_pipeline_retires;
      std::vector<std::uint64_t> reader_replay_pipeline_requests;
      std::vector<std::uint64_t> reader_replay_pipeline_retires;
      std::vector<std::uint64_t> reader_edge_pipeline_credit_stalls;
      std::vector<std::uint64_t> reader_edge_pipeline_request_fifo_stalls;
      std::vector<std::uint64_t> reader_edge_pipeline_axis_stalls;
      std::vector<std::size_t> reader_edge_pipeline_max_inflight;
      std::vector<std::size_t> reader_edge_pipeline_max_buffered;
      std::vector<std::uint64_t> reader_source_requests;
      std::vector<std::uint64_t> reader_source_responses;
      std::vector<std::uint64_t> reader_source_windows;
      std::vector<std::uint64_t> reader_protocol_markers;
      std::vector<std::uint64_t> reader_protocol_acks;
      std::vector<std::uint32_t> reader_protocol_status;
      std::vector<std::uint32_t> reader_dirty_status;
      std::vector<std::uint32_t> reader_dirty_counts;
      std::vector<std::uint32_t> reader_dirty_generations;
      std::vector<std::uint32_t> reader_ack_eligible;
      std::vector<std::uint32_t> reader_host_coverage_match;
      std::vector<std::uint32_t> compute_protocol_status;
      std::vector<std::uint64_t> reader_diagnostic_words;
      std::vector<std::uint64_t> reader_done_words;
      std::vector<std::uint32_t> reader_done_overflow;
      std::vector<std::uint64_t> compute_diagnostic_words;
      std::vector<std::uint64_t> compute_done_words;
      std::vector<std::uint32_t> compute_done_overflow;
      std::vector<std::uint32_t> compute_range_paths;
      std::vector<std::uint32_t> compute_range_fallback_reasons;
      std::vector<std::uint32_t> compute_range_errors;
      std::vector<std::uint64_t> compute_range_tasks;
      std::vector<std::uint64_t> compute_range_row_lookups;
      std::vector<std::uint64_t> compute_range_construction_payloads;
      std::vector<std::uint64_t> compute_range_replay_payloads;
      std::vector<std::uint64_t> compute_range_active_records;
      std::vector<std::uint64_t> compute_range_family_probes;
      std::vector<std::uint64_t> compute_range_family_skips;
      std::vector<std::uint32_t> compute_dirty_counts;
      std::vector<std::uint32_t> compute_dirty_generations;
      std::vector<std::uint64_t> reader_epoch_misses;
      std::vector<std::size_t> reader_source_sizes;
      std::vector<std::uint64_t> fast_tiles;
      std::vector<std::uint64_t> full_tiles;
      std::vector<std::uint64_t> compute_tiny_buffer_writes;
      std::vector<std::uint64_t> compute_tiny_buffer_reads;
      std::vector<std::uint64_t> compute_tile_active_clear_words;
      std::vector<std::uint64_t> compute_sparse_store_scan_words;
      std::vector<std::uint64_t> compute_sparse_store_bit_cycles;
      std::vector<std::uint64_t> compute_active_emit_scan_words;
      std::vector<std::uint64_t> compute_active_emit_bit_cycles;
      std::vector<std::uint64_t> compute_on_chip_controller_cycles;
      std::vector<std::uint64_t> compute_memory_requests_issued;
      std::vector<std::uint64_t> compute_memory_requests_completed;
      std::vector<std::uint64_t> compute_memory_window_stall_cycles;
      std::vector<std::size_t> compute_max_vertex_requests_inflight;
      std::vector<std::size_t> compute_max_active_out_requests_inflight;
      std::vector<std::size_t> compute_max_active_memory_ports;
      std::vector<std::uint64_t> compute_memory_cross_port_overlap_cycles;
      std::vector<std::size_t> compute_max_memory_responses_per_cycle;
      std::vector<std::uint64_t> compute_multi_port_response_cycles;
      std::vector<std::uint64_t> compute_controller_memory_overlap_cycles;
      std::vector<std::uint64_t> compute_controller_memory_stall_cycles;
      std::vector<std::uint64_t> compute_sparse_store_writes_generated;
      std::vector<std::uint64_t> compute_active_emit_writes_generated;
      std::vector<std::uint64_t> compute_tiny_bram_read_requests;
      std::vector<std::uint64_t> compute_tiny_bram_write_requests;
      std::vector<std::uint64_t> compute_vs_uram_read_requests;
      std::vector<std::uint64_t> compute_vs_uram_write_requests;
      std::vector<std::uint64_t> compute_active_bram_read_requests;
      std::vector<std::uint64_t> compute_active_bram_write_requests;
      std::vector<std::uint64_t> compute_on_chip_read_wait_cycles;
      std::vector<std::uint64_t> compute_on_chip_pipeline_stall_cycles;
      std::vector<std::uint64_t> compute_vs_bypass_hits;
      std::vector<std::uint64_t> compute_vs_bypass_misses;
      std::vector<std::size_t> compute_max_tiny_reads_inflight;
      std::vector<std::size_t> compute_max_vs_reads_inflight;
      std::vector<std::uint64_t> compute_full_tile_read_beats;
      std::vector<std::uint64_t> compute_full_tile_read_words;
      std::vector<std::uint64_t> compute_full_tile_read_wait_cycles;
      std::vector<std::uint64_t> compute_full_tile_stream_errors;
      std::vector<std::uint64_t> compute_cross_tile_write_overlap_cycles;
      std::vector<std::size_t> compute_max_cross_tile_writes_inflight;
      std::vector<std::size_t> edge_axis_max_occupancy;
      std::vector<std::uint64_t> edge_axis_push_stalls;
      std::vector<std::uint64_t> edge_axis_transfers;
      std::vector<std::uint64_t> value_axis_transfers;
      std::vector<std::size_t> value_axis_max_occupancy;
      for (const SpineSsspRoundEvidence &round : sst_rounds_) {
        frontier_in_sizes.push_back(round.active_in.size());
        frontier_out_sizes.push_back(round.active_out.size());
        processed_edges.push_back(round.compute.processed_edges);
        round_cycles.push_back(round.end_cycle - round.start_cycle);
        reader_graph_bytes.push_back(round.reader.graph_read_bytes);
        reader_graph_index_payload_bytes.push_back(
            round.reader.graph_index_payload_read_bytes);
        reader_graph_payload_bytes.push_back(
            round.reader.graph_edge_payload_read_bytes);
        reader_construction_payload_bytes.push_back(
            round.reader.graph_construction_payload_read_bytes);
        reader_replay_payload_bytes.push_back(
            round.reader.graph_replay_payload_read_bytes);
        reader_graph_index_bitmap_misses.push_back(
            round.reader.graph_index_bitmap_misses);
        reader_range_tasks.push_back(round.reader.range_task_count);
        reader_range_row_lookups.push_back(round.reader.range_task_row_lookups);
        reader_range_level_checks.push_back(
            round.reader.range_task_level_checks);
        reader_range_construction_payloads.push_back(
            round.reader.range_task_construction_payloads);
        reader_range_replay_payloads.push_back(
            round.reader.range_task_replay_payloads);
        reader_range_active_records.push_back(
            round.reader.range_task_active_records);
        reader_range_family_probes.push_back(
            round.reader.range_task_family_probes);
        reader_range_family_skips.push_back(
            round.reader.range_task_family_skips);
        reader_fallback_partitions.push_back(round.reader.fallback_partitions);
        reader_fallback_forced_dense_partitions.push_back(
            round.reader.fallback_forced_dense_partitions);
        reader_fallback_active_record_reads.push_back(
            round.reader.fallback_active_record_reads);
        reader_fallback_row_lookups.push_back(
            round.reader.fallback_row_lookups);
        reader_fallback_replay_edges.push_back(
            round.reader.fallback_replay_edges);
        reader_range_paths.push_back(round.reader.range_task_path);
        reader_range_fallback_reasons.push_back(
            round.reader.range_task_fallback_reason);
        reader_range_errors.push_back(round.reader.range_task_error);
        reader_metadata_bytes.push_back(round.reader.metadata_read_bytes);
        reader_metadata_write_bytes.push_back(
            round.reader.metadata_write_bytes);
        reader_result_write_bytes.push_back(round.reader.result_write_bytes);
        reader_active_bin_bytes.push_back(round.reader.active_bin_read_bytes);
        reader_dirty_list_bytes.push_back(round.reader.dirty_list_read_bytes);
        reader_dirty_bitmap_bytes.push_back(
            round.reader.dirty_bitmap_read_bytes);
        reader_memory_requests_issued.push_back(
            round.reader.memory_requests_issued);
        reader_memory_requests_completed.push_back(
            round.reader.memory_requests_completed);
        reader_memory_window_stalls.push_back(
            round.reader.memory_window_stall_cycles);
        reader_memory_dependency_stalls.push_back(
            round.reader.memory_dependency_stall_cycles);
        reader_memory_request_fifo_stalls.push_back(
            round.reader.memory_request_fifo_stall_cycles);
        reader_max_memory_requests_inflight.push_back(
            round.reader.max_memory_requests_inflight);
        reader_construction_pipeline_requests.push_back(
            round.reader.construction_pipeline_requests);
        reader_construction_pipeline_retires.push_back(
            round.reader.construction_pipeline_retires);
        reader_replay_pipeline_requests.push_back(
            round.reader.replay_pipeline_requests);
        reader_replay_pipeline_retires.push_back(
            round.reader.replay_pipeline_retires);
        reader_edge_pipeline_credit_stalls.push_back(
            round.reader.edge_pipeline_credit_stall_cycles);
        reader_edge_pipeline_request_fifo_stalls.push_back(
            round.reader.edge_pipeline_request_fifo_stall_cycles);
        reader_edge_pipeline_axis_stalls.push_back(
            round.reader.edge_pipeline_axis_stall_cycles);
        reader_edge_pipeline_max_inflight.push_back(
            round.reader.edge_pipeline_max_inflight);
        reader_edge_pipeline_max_buffered.push_back(
            round.reader.edge_pipeline_max_buffered);
        reader_source_requests.push_back(round.reader.source_requests);
        reader_source_responses.push_back(round.reader.source_responses);
        reader_source_windows.push_back(round.reader.source_request_windows);
        reader_protocol_markers.push_back(
            round.reader.source_protocol_markers);
        reader_protocol_acks.push_back(round.reader.source_protocol_acks);
        reader_protocol_status.push_back(round.reader.source_protocol_status);
        reader_dirty_status.push_back(round.reader.dirty_status);
        reader_dirty_counts.push_back(round.reader.dirty_count);
        reader_dirty_generations.push_back(round.reader.dirty_generation);
        reader_ack_eligible.push_back(
            round.reader.acknowledgement_eligible ? 1U : 0U);
        reader_host_coverage_match.push_back(
            round.reader.host_coverage_match ? 1U : 0U);
        compute_protocol_status.push_back(
            round.compute.source_protocol_status);
        reader_diagnostic_words.push_back(round.reader.diagnostic_words);
        reader_done_words.push_back(round.reader.done_words);
        reader_done_overflow.push_back(round.reader.done_overflow ? 1U : 0U);
        compute_diagnostic_words.push_back(round.compute.diagnostic_words);
        compute_done_words.push_back(round.compute.done_words);
        compute_done_overflow.push_back(round.compute.done_overflow ? 1U : 0U);
        compute_range_paths.push_back(round.compute.range_task_path);
        compute_range_fallback_reasons.push_back(
            round.compute.range_task_fallback_reason);
        compute_range_errors.push_back(round.compute.range_task_error);
        compute_range_tasks.push_back(round.compute.range_task_count);
        compute_range_row_lookups.push_back(
            round.compute.range_task_row_lookups);
        compute_range_construction_payloads.push_back(
            round.compute.range_task_construction_payloads);
        compute_range_replay_payloads.push_back(
            round.compute.range_task_replay_payloads);
        compute_range_active_records.push_back(
            round.compute.range_task_active_records);
        compute_range_family_probes.push_back(
            round.compute.range_task_family_probes);
        compute_range_family_skips.push_back(
            round.compute.range_task_family_skips);
        compute_dirty_counts.push_back(round.compute.dirty_count);
        compute_dirty_generations.push_back(round.compute.dirty_generation);
        reader_epoch_misses.push_back(round.reader.graph_index_epoch_misses);
        reader_source_sizes.push_back(round.reader_sources.size());
        fast_tiles.push_back(round.compute.fast_path_tiles);
        full_tiles.push_back(round.compute.full_path_tiles);
        compute_tiny_buffer_writes.push_back(
            round.compute.tiny_buffer_writes);
        compute_tiny_buffer_reads.push_back(round.compute.tiny_buffer_reads);
        compute_tile_active_clear_words.push_back(
            round.compute.tile_active_clear_words);
        compute_sparse_store_scan_words.push_back(
            round.compute.sparse_store_scan_words);
        compute_sparse_store_bit_cycles.push_back(
            round.compute.sparse_store_bit_cycles);
        compute_active_emit_scan_words.push_back(
            round.compute.active_emit_scan_words);
        compute_active_emit_bit_cycles.push_back(
            round.compute.active_emit_bit_cycles);
        compute_on_chip_controller_cycles.push_back(
            round.compute.on_chip_controller_cycles);
        compute_memory_requests_issued.push_back(
            round.compute.memory_requests_issued);
        compute_memory_requests_completed.push_back(
            round.compute.memory_requests_completed);
        compute_memory_window_stall_cycles.push_back(
            round.compute.memory_window_stall_cycles);
        compute_max_vertex_requests_inflight.push_back(
            round.compute.max_vertex_requests_inflight);
        compute_max_active_out_requests_inflight.push_back(
            round.compute.max_active_out_requests_inflight);
        compute_max_active_memory_ports.push_back(
            round.compute.max_active_memory_ports);
        compute_memory_cross_port_overlap_cycles.push_back(
            round.compute.memory_cross_port_overlap_cycles);
        compute_max_memory_responses_per_cycle.push_back(
            round.compute.max_memory_responses_completed_per_cycle);
        compute_multi_port_response_cycles.push_back(
            round.compute.multi_port_response_cycles);
        compute_controller_memory_overlap_cycles.push_back(
            round.compute.controller_memory_overlap_cycles);
        compute_controller_memory_stall_cycles.push_back(
            round.compute.controller_memory_stall_cycles);
        compute_sparse_store_writes_generated.push_back(
            round.compute.sparse_store_writes_generated);
        compute_active_emit_writes_generated.push_back(
            round.compute.active_emit_writes_generated);
        compute_tiny_bram_read_requests.push_back(
            round.compute.tiny_bram_read_requests);
        compute_tiny_bram_write_requests.push_back(
            round.compute.tiny_bram_write_requests);
        compute_vs_uram_read_requests.push_back(
            round.compute.vs_uram_read_requests);
        compute_vs_uram_write_requests.push_back(
            round.compute.vs_uram_write_requests);
        compute_active_bram_read_requests.push_back(
            round.compute.active_bram_read_requests);
        compute_active_bram_write_requests.push_back(
            round.compute.active_bram_write_requests);
        compute_on_chip_read_wait_cycles.push_back(
            round.compute.on_chip_read_wait_cycles);
        compute_on_chip_pipeline_stall_cycles.push_back(
            round.compute.on_chip_pipeline_stall_cycles);
        compute_vs_bypass_hits.push_back(round.compute.vs_bypass_hits);
        compute_vs_bypass_misses.push_back(round.compute.vs_bypass_misses);
        compute_max_tiny_reads_inflight.push_back(
            round.compute.max_tiny_reads_inflight);
        compute_max_vs_reads_inflight.push_back(
            round.compute.max_vs_reads_inflight);
        compute_full_tile_read_beats.push_back(
            round.compute.full_tile_read_beats);
        compute_full_tile_read_words.push_back(
            round.compute.full_tile_read_words);
        compute_full_tile_read_wait_cycles.push_back(
            round.compute.full_tile_read_wait_cycles);
        compute_full_tile_stream_errors.push_back(
            round.compute.full_tile_stream_error_count);
        compute_cross_tile_write_overlap_cycles.push_back(
            round.compute.cross_tile_write_overlap_cycles);
        compute_max_cross_tile_writes_inflight.push_back(
            round.compute.max_cross_tile_writes_inflight);
        edge_axis_max_occupancy.push_back(round.edge_axis.max_occupancy);
        edge_axis_push_stalls.push_back(round.edge_axis.push_stalls);
        edge_axis_transfers.push_back(round.edge_axis.pushes);
        value_axis_transfers.push_back(round.value_axis.pushes);
        value_axis_max_occupancy.push_back(round.value_axis.max_occupancy);
      }
      std::vector<std::size_t> handoff_logical_rounds;
      std::vector<std::uint32_t> handoff_reasons;
      std::vector<std::size_t> handoff_source_counts;
      std::vector<std::uint64_t> handoff_host_list_read_bytes;
      std::vector<std::uint64_t> handoff_host_control_cycles;
      std::vector<std::uint32_t> handoff_host_control_timed;
      std::vector<std::uint64_t> handoff_device_attempt_cycles;
      std::vector<std::uint32_t> handoff_device_reader_overflow;
      std::vector<std::uint32_t> handoff_device_compute_overflow;
      for (const SpineHostHandoffEvidence &handoff : sst_host_handoffs_) {
        handoff_logical_rounds.push_back(handoff.logical_round);
        handoff_reasons.push_back(handoff.fallback_reason);
        handoff_source_counts.push_back(handoff.source_count);
        handoff_host_list_read_bytes.push_back(handoff.host_list_read_bytes);
        handoff_host_control_cycles.push_back(handoff.host_control_cycles);
        handoff_host_control_timed.push_back(handoff.host_control_timed ? 1U
                                                                        : 0U);
        handoff_device_attempt_cycles.push_back(
            handoff.device_attempt.end_cycle -
            handoff.device_attempt.start_cycle);
        handoff_device_reader_overflow.push_back(
            handoff.device_attempt.reader.done_overflow ? 1U : 0U);
        handoff_device_compute_overflow.push_back(
            handoff.device_attempt.compute.done_overflow ? 1U : 0U);
      }
      const auto &maintenance = spine_system_->maintenance_counters();
      const auto &sorted_axi =
          spine_system_->axi_stats(SpineAxiPortKind::kSortedEdges);
      const auto &dirty_ack = spine_system_->dirty_ack_counters();
      result
          << "{\n"
          << "  \"success\": " << (passed ? "true" : "false") << ",\n"
          << "  \"mode\": \"spine_sssp\",\n"
          << "  \"backend\": \"sst_memHierarchy_dramsim3\",\n"
          << "  \"spine_axi_profile\": \"" << spine_axi_profile_id_ << "\",\n"
          << "  \"axi_graph_data_width_bytes\": "
          << spine_axi_profile_.graph_bytes << ",\n"
          << "  \"axi_sorted_data_width_bytes\": "
          << spine_axi_profile_.sorted_edge_bytes << ",\n"
          << "  \"axi_active_bin_data_width_bytes\": "
          << spine_axi_profile_.active_bin_bytes << ",\n"
          << "  \"axi_metadata_data_width_bytes\": "
          << spine_axi_profile_.metadata_bytes << ",\n"
          << "  \"axi_max_burst_beats\": " << spine_axi_profile_.max_burst_beats
          << ",\n"
          << "  \"axi_max_outstanding_bursts\": "
          << spine_axi_profile_.max_outstanding_bursts << ",\n"
          << "  \"cycles\": " << scheduler_.clock(0).completed_cycles << ",\n"
          << "  \"maintenance_start_cycle\": " << maintenance.start_cycle
          << ",\n"
          << "  \"maintenance_end_cycle\": " << maintenance.end_cycle
          << ",\n"
          << "  \"maintenance_cycles\": "
          << maintenance.end_cycle - maintenance.start_cycle << ",\n"
          << "  \"maintenance_target_level\": "
          << maintenance.target_level << ",\n"
          << "  \"maintenance_persisted_edges\": "
          << maintenance.persisted_edges << ",\n"
          << "  \"input_edges\": " << spine_expected_edges_ << ",\n"
          << "  \"rounds\": " << sst_rounds_.size() << ",\n"
          << "  \"host_handoffs\": " << sst_host_handoffs_.size() << ",\n"
          << "  \"dynamic_update\": "
          << (dynamic_sssp_enabled_ ? "true" : "false") << ",\n";
      if (dynamic_sssp_enabled_) {
        result
            << "  \"update_edges\": "
            << dynamic_update_workload_.edges.size() << ",\n"
            << "  \"dynamic_update_path\": \""
            << (dynamic_full_rebuild_ ? "full_rebuild"
                                      : "incremental_relax")
            << "\",\n"
            << "  \"materialized_snapshot_edges\": "
            << dynamic_materialized_snapshot_.edges.size() << ",\n"
            << "  \"cold_cycles\": " << cold_cycles_ << ",\n"
            << "  \"update_cycles\": "
            << scheduler_.clock(0).completed_cycles -
                   dynamic_update_start_cycle_
            << ",\n"
            << "  \"cold_rounds\": " << cold_rounds_ << ",\n"
            << "  \"cold_maintenance_cycles\": "
            << cold_maintenance_cycles_ << ",\n"
            << "  \"cold_maintenance_target_level\": "
            << cold_maintenance_target_level_ << ",\n"
            << "  \"cold_dirty_generation_after_ack\": "
            << cold_dirty_generation_after_ack_ << ",\n"
            << "  \"cold_backend_requests\": "
            << cold_backend_requests_ << ",\n"
            << "  \"update_backend_requests\": "
            << backend_->accepted() - cold_backend_requests_ << ",\n"
            << "  \"cold_correctness_mismatches\": "
            << cold_value_mismatches_ << ",\n"
            << "  \"cold_frontier_mismatches\": "
            << cold_frontier_mismatches_ << ",\n"
            << "  \"full_recompute_correctness_mismatches\": "
            << full_recompute_mismatches << ",\n"
            << "  \"cold_final_values\": ";
        write_json_array(result, cold_final_values_);
        result << ",\n  \"cold_round_cycles\": ";
        write_json_array(result, cold_round_cycles_);
        result << ",\n";
      }
      result
          << "  \"range_task_capacity\": " << range_task_capacity_ << ",\n"
          << "  \"range_task_payload_budget\": " << range_task_payload_budget_
          << ",\n"
          << "  \"memory_request_window\": " << memory_request_window_ << ",\n"
          << "  \"reader_edge_pipeline_depth\": " << reader_edge_pipeline_depth_
          << ",\n"
          << "  \"reader_edge_response_capacity\": "
          << reader_edge_response_capacity_ << ",\n"
          << "  \"maintenance_count_scan_ii\": " << maintenance_count_scan_ii_
          << ",\n"
          << "  \"maintenance_count_scan_tail_cycles\": "
          << maintenance_count_scan_tail_cycles_ << ",\n"
          << "  \"maintenance_l0_write_scan_ii\": "
          << maintenance_l0_write_scan_ii_ << ",\n"
          << "  \"maintenance_l0_write_scan_tail_cycles\": "
          << maintenance_l0_write_scan_tail_cycles_ << ",\n"
          << "  \"maintenance_scan_response_capacity\": "
          << maintenance_scan_response_capacity_ << ",\n"
          << "  \"converged\": " << (converged ? "true" : "false") << ",\n"
          << "  \"correctness_mismatches\": " << mismatches << ",\n"
          << "  \"frontier_mismatches\": " << frontier_mismatches << ",\n"
          << "  \"maintenance_scan_passes\": " << maintenance.sorted_scan_passes
          << ",\n"
          << "  \"maintenance_full_rebuild_clear_cycles\": "
          << maintenance.full_rebuild_clear_cycles << ",\n"
          << "  \"maintenance_full_rebuild_clear_requests\": "
          << maintenance.full_rebuild_clear_requests << ",\n"
          << "  \"maintenance_full_rebuild_clear_bytes\": "
          << maintenance.full_rebuild_clear_bytes << ",\n"
          << "  \"maintenance_edge_visits\": " << maintenance.sorted_edge_visits
          << ",\n"
          << "  \"maintenance_sorted_bytes\": " << maintenance.sorted_read_bytes
          << ",\n"
          << "  \"maintenance_sorted_payload_read_bytes\": "
          << maintenance.sorted_payload_read_bytes << ",\n"
          << "  \"maintenance_sorted_read_beats\": "
          << maintenance.sorted_read_beats_received << ",\n"
          << "  \"maintenance_carry_new_batch_reads\": "
          << maintenance.carry_new_batch_reads << ",\n"
          << "  \"maintenance_carry_new_batch_read_bytes\": "
          << maintenance.carry_new_batch_read_bytes << ",\n"
          << "  \"maintenance_scan_response_stall_cycles\": "
          << maintenance.sorted_scan_response_stall_cycles << ",\n"
          << "  \"maintenance_scan_reorder_full_stall_cycles\": "
          << maintenance.sorted_scan_reorder_full_stall_cycles << ",\n"
          << "  \"maintenance_scan_ii_stall_cycles\": "
          << maintenance.sorted_scan_ii_stall_cycles << ",\n"
          << "  \"maintenance_scan_tail_cycles\": "
          << maintenance.sorted_scan_tail_cycles << ",\n"
          << "  \"maintenance_max_scan_buffered_edges\": "
          << maintenance.max_sorted_scan_buffered_edges << ",\n"
          << "  \"maintenance_sorted_axi_read_beat_fifo_stall_cycles\": "
          << sorted_axi.read_beat_queue_stalls << ",\n"
          << "  \"maintenance_sorted_axi_read_reorder_stall_cycles\": "
          << sorted_axi.read_reorder_stalls << ",\n"
          << "  \"maintenance_sorted_axi_read_beats_streamed\": "
          << sorted_axi.read_beats_streamed << ",\n"
          << "  \"maintenance_dirty_validate_visits\": "
          << maintenance.dirty_validate_edge_visits << ",\n"
          << "  \"maintenance_dirty_mark_visits\": "
          << maintenance.dirty_mark_edge_visits << ",\n"
          << "  \"maintenance_dirty_unique_sources\": "
          << maintenance.unique_sources << ",\n"
          << "  \"maintenance_dirty_bitmap_reads\": "
          << maintenance.dirty_bitmap_reads << ",\n"
          << "  \"maintenance_dirty_bitmap_writes\": "
          << maintenance.dirty_bitmap_writes << ",\n"
          << "  \"maintenance_dirty_list_reads\": "
          << maintenance.dirty_list_reads << ",\n"
          << "  \"maintenance_dirty_list_appends\": "
          << maintenance.dirty_list_appends << ",\n"
          << "  \"maintenance_dirty_duplicates_suppressed\": "
          << maintenance.dirty_duplicates_suppressed << ",\n"
          << "  \"maintenance_dirty_generation_advances\": "
          << maintenance.dirty_generation_advances << ",\n"
          << "  \"maintenance_dirty_count\": " << maintenance.dirty_count
          << ",\n"
          << "  \"maintenance_dirty_generation\": "
          << maintenance.dirty_generation << ",\n"
          << "  \"maintenance_dirty_hash_sum\": "
          << maintenance.dirty_hash_sum << ",\n"
          << "  \"maintenance_dirty_hash_xor\": "
          << maintenance.dirty_hash_xor << ",\n"
          << "  \"maintenance_hot_cold_count_visits\": "
          << maintenance.hot_cold_count_edge_visits << ",\n"
          << "  \"maintenance_family_precount_visits\": "
          << maintenance.family_precount_edge_visits << ",\n"
          << "  \"maintenance_l0_write_visits\": "
          << maintenance.l0_write_edge_visits << ",\n"
          << "  \"maintenance_target_selector_invocations\": "
          << maintenance.target_selector_invocations << ",\n"
          << "  \"maintenance_target_selector_levels_scanned\": "
          << maintenance.target_selector_levels_scanned << ",\n"
          << "  \"maintenance_target_selector_family_iterations\": "
          << maintenance.target_selector_family_iterations << ",\n"
          << "  \"maintenance_target_selector_metadata_reads\": "
          << maintenance.target_selector_metadata_reads << ",\n"
          << "  \"maintenance_target_selector_payload_read_bytes\": "
          << maintenance.target_selector_payload_read_bytes << ",\n"
          << "  \"maintenance_target_selector_responses\": "
          << maintenance.target_selector_responses << ",\n"
          << "  \"maintenance_target_selector_cycles\": "
          << maintenance.target_selector_cycles << ",\n"
          << "  \"maintenance_target_selector_min_padding_cycles\": "
          << maintenance.target_selector_min_padding_cycles << ",\n"
          << "  \"maintenance_target_selector_validation_failures\": "
          << maintenance.target_selector_validation_failures << ",\n"
          << "  \"maintenance_target_selector_max_inflight\": "
          << maintenance.target_selector_max_inflight << ",\n"
          << "  \"maintenance_metadata_control_reads\": "
          << maintenance.metadata_control_reads << ",\n"
          << "  \"maintenance_metadata_control_payload_read_bytes\": "
          << maintenance.metadata_control_payload_read_bytes << ",\n"
          << "  \"maintenance_hot_bitmap_reads\": "
          << maintenance.hot_bitmap_reads << ",\n"
          << "  \"maintenance_hot_bitmap_scan_reads\": "
          << maintenance.hot_bitmap_scan_reads << ",\n"
          << "  \"maintenance_hot_bitmap_carry_reads\": "
          << maintenance.hot_bitmap_carry_reads << ",\n"
          << "  \"maintenance_hot_bitmap_responses\": "
          << maintenance.hot_bitmap_responses << ",\n"
          << "  \"maintenance_hot_bitmap_payload_read_bytes\": "
          << maintenance.hot_bitmap_payload_read_bytes << ",\n"
          << "  \"maintenance_hot_bitmap_scan_wait_cycles\": "
          << maintenance.hot_bitmap_scan_wait_cycles << ",\n"
          << "  \"maintenance_hot_bitmap_validation_failures\": "
          << maintenance.hot_bitmap_validation_failures << ",\n"
          << "  \"maintenance_hot_bitmap_max_inflight\": "
          << maintenance.hot_bitmap_max_inflight << ",\n"
          << "  \"maintenance_result_metadata_reads\": "
          << maintenance.result_metadata_reads << ",\n"
          << "  \"maintenance_result_metadata_responses\": "
          << maintenance.result_metadata_responses << ",\n"
          << "  \"maintenance_result_metadata_payload_read_bytes\": "
          << maintenance.result_metadata_payload_read_bytes << ",\n"
          << "  \"maintenance_result_metadata_max_inflight\": "
          << maintenance.result_metadata_max_inflight << ",\n"
          << "  \"maintenance_result_payload_write_bytes\": "
          << maintenance.result_payload_write_bytes << ",\n"
          << "  \"maintenance_result_write_responses\": "
          << maintenance.result_write_responses << ",\n"
          << "  \"maintenance_result_validation_failures\": "
          << maintenance.result_validation_failures << ",\n"
          << "  \"maintenance_logical_overflow_events\": "
          << maintenance.logical_overflow_events << ",\n"
          << "  \"maintenance_slice_epoch_reads\": "
          << maintenance.slice_epoch_reads << ",\n"
          << "  \"maintenance_slice_epoch_responses\": "
          << maintenance.slice_epoch_responses << ",\n"
          << "  \"maintenance_slice_epoch_payload_read_bytes\": "
          << maintenance.slice_epoch_payload_read_bytes << ",\n"
          << "  \"maintenance_slice_epoch_validation_failures\": "
          << maintenance.slice_epoch_validation_failures << ",\n"
          << "  \"maintenance_epoch_full_clear_fallbacks\": "
          << maintenance.epoch_full_clear_fallbacks << ",\n"
          << "  \"maintenance_epoch_wrap_events\": "
          << maintenance.epoch_wrap_events << ",\n"
          << "  \"maintenance_epoch_commit_failures\": "
          << maintenance.epoch_commit_failures << ",\n"
          << "  \"maintenance_epoch_clear_parent_writes\": "
          << maintenance.epoch_clear_parent_writes << ",\n"
          << "  \"maintenance_epoch_clear_word_writes\": "
          << maintenance.epoch_clear_word_writes << ",\n"
          << "  \"maintenance_epoch_clear_payload_write_bytes\": "
          << maintenance.epoch_clear_payload_write_bytes << ",\n"
          << "  \"maintenance_epoch_clear_write_responses\": "
          << maintenance.epoch_clear_write_responses << ",\n"
          << "  \"maintenance_epoch_clear_wait_cycles\": "
          << maintenance.epoch_clear_wait_cycles << ",\n"
          << "  \"maintenance_epoch_retire_writes\": "
          << maintenance.epoch_retire_writes << ",\n"
          << "  \"maintenance_epoch_retire_write_responses\": "
          << maintenance.epoch_retire_write_responses << ",\n"
          << "  \"maintenance_carry_cursor_metadata_read_bytes\": "
          << maintenance.carry_cursor_metadata_read_bytes << ",\n"
          << "  \"maintenance_carry_cursor_page_ids\": "
          << maintenance.carry_cursor_page_ids << ",\n"
          << "  \"maintenance_carry_cursor_pages_visited\": "
          << maintenance.carry_cursor_pages_visited << ",\n"
          << "  \"maintenance_carry_cursor_bitmap_words\": "
          << maintenance.carry_cursor_bitmap_words << ",\n"
          << "  \"maintenance_carry_cursor_bits_inspected\": "
          << maintenance.carry_cursor_bits_inspected << ",\n"
          << "  \"maintenance_carry_cursor_refill_cycles\": "
          << maintenance.carry_cursor_refill_cycles << ",\n"
          << "  \"maintenance_carry_cursor_rows_entered\": "
          << maintenance.carry_cursor_rows_entered << ",\n"
          << "  \"maintenance_carry_cursor_row_offset_reads\": "
          << maintenance.carry_cursor_row_offset_reads << ",\n"
          << "  \"maintenance_carry_cursor_validation_failures\": "
          << maintenance.carry_cursor_validation_failures << ",\n"
          << "  \"maintenance_carry_writer_groups_seen\": "
          << maintenance.carry_writer_groups_seen << ",\n"
          << "  \"maintenance_carry_writer_groups_emitted\": "
          << maintenance.carry_writer_groups_emitted << ",\n"
          << "  \"maintenance_carry_writer_groups_cancelled\": "
          << maintenance.carry_writer_groups_cancelled << ",\n"
          << "  \"maintenance_carry_writer_edge_word_writes\": "
          << maintenance.carry_writer_edge_word_writes << ",\n"
          << "  \"maintenance_carry_writer_row_word_writes\": "
          << maintenance.carry_writer_row_word_writes << ",\n"
          << "  \"maintenance_carry_writer_mask_word_writes\": "
          << maintenance.carry_writer_mask_word_writes << ",\n"
          << "  \"maintenance_carry_writer_page_base_word_writes\": "
          << maintenance.carry_writer_page_base_word_writes << ",\n"
          << "  \"maintenance_carry_writer_bitmap_page_writes\": "
          << maintenance.carry_writer_bitmap_page_writes << ",\n"
          << "  \"maintenance_carry_writer_page_list_word_writes\": "
          << maintenance.carry_writer_page_list_word_writes << ",\n"
          << "  \"maintenance_carry_writer_page_epoch_word_writes\": "
          << maintenance.carry_writer_page_epoch_word_writes << ",\n"
          << "  \"maintenance_carry_writer_memory_wait_cycles\": "
          << maintenance.carry_writer_memory_wait_cycles << ",\n"
          << "  \"maintenance_l0_writer_groups_seen\": "
          << maintenance.l0_writer_groups_seen << ",\n"
          << "  \"maintenance_l0_writer_groups_emitted\": "
          << maintenance.l0_writer_groups_emitted << ",\n"
          << "  \"maintenance_l0_writer_groups_cancelled\": "
          << maintenance.l0_writer_groups_cancelled << ",\n"
          << "  \"maintenance_l0_writer_edge_word_writes\": "
          << maintenance.l0_writer_edge_word_writes << ",\n"
          << "  \"maintenance_l0_writer_row_word_writes\": "
          << maintenance.l0_writer_row_word_writes << ",\n"
          << "  \"maintenance_l0_writer_mask_word_writes\": "
          << maintenance.l0_writer_mask_word_writes << ",\n"
          << "  \"maintenance_l0_writer_page_base_word_writes\": "
          << maintenance.l0_writer_page_base_word_writes << ",\n"
          << "  \"maintenance_l0_writer_bitmap_page_writes\": "
          << maintenance.l0_writer_bitmap_page_writes << ",\n"
          << "  \"maintenance_l0_writer_page_list_word_writes\": "
          << maintenance.l0_writer_page_list_word_writes << ",\n"
          << "  \"maintenance_l0_writer_page_epoch_word_writes\": "
          << maintenance.l0_writer_page_epoch_word_writes << ",\n"
          << "  \"maintenance_l0_writer_memory_wait_cycles\": "
          << maintenance.l0_writer_memory_wait_cycles << ",\n"
          << "  \"maintenance_l0_writer_memory_overlap_cycles\": "
          << maintenance.l0_writer_memory_overlap_cycles << ",\n"
          << "  \"maintenance_l0_writer_backpressure_stall_cycles\": "
          << maintenance.l0_writer_backpressure_stall_cycles << ",\n"
          << "  \"maintenance_l0_writer_validation_failures\": "
          << maintenance.l0_writer_validation_failures << ",\n"
          << "  \"maintenance_l0_writer_max_pending_tasks\": "
          << maintenance.l0_writer_max_pending_tasks << ",\n"
          << "  \"maintenance_l0_writer_max_pending_tasks_per_port\": "
          << maintenance.l0_writer_max_pending_tasks_per_port << ",\n"
          << "  \"maintenance_graph_index_payload_write_bytes\": "
          << maintenance.graph_index_payload_write_bytes << ",\n"
          << "  \"maintenance_graph_payload_write_bytes\": "
          << maintenance.graph_edge_payload_write_bytes << ",\n"
          << "  \"maintenance_page_list_payload_write_bytes\": "
          << maintenance.page_list_payload_write_bytes << ",\n"
          << "  \"maintenance_page_list_count_write_bytes\": "
          << maintenance.page_list_count_write_bytes << ",\n"
          << "  \"maintenance_memory_requests_issued\": "
          << maintenance.memory_requests_issued << ",\n"
          << "  \"maintenance_memory_requests_completed\": "
          << maintenance.memory_requests_completed << ",\n"
          << "  \"maintenance_memory_window_stall_cycles\": "
          << maintenance.memory_window_stall_cycles << ",\n"
          << "  \"maintenance_memory_dependency_stall_cycles\": "
          << maintenance.memory_dependency_stall_cycles << ",\n"
          << "  \"maintenance_memory_request_fifo_stall_cycles\": "
          << maintenance.memory_request_fifo_stall_cycles << ",\n"
          << "  \"maintenance_max_memory_requests_issued_per_cycle\": "
          << maintenance.max_memory_requests_issued_per_cycle << ",\n"
          << "  \"maintenance_max_memory_responses_completed_per_cycle\": "
          << maintenance.max_memory_responses_completed_per_cycle << ",\n"
          << "  \"maintenance_multi_port_issue_cycles\": "
          << maintenance.multi_port_issue_cycles << ",\n"
          << "  \"maintenance_multi_port_response_cycles\": "
          << maintenance.multi_port_response_cycles << ",\n"
          << "  \"maintenance_max_memory_requests_inflight\": "
          << maintenance.max_memory_requests_inflight << ",\n"
          << "  \"maintenance_max_memory_requests_inflight_per_port\": "
          << maintenance.max_memory_requests_inflight_per_port << ",\n"
          << "  \"maintenance_max_non_target_memory_requests_inflight_per_port\": "
          << maintenance.max_non_target_memory_requests_inflight_per_port
          << ",\n"
          << "  \"maintenance_max_active_memory_ports\": "
          << maintenance.max_active_memory_ports << ",\n"
          << "  \"maintenance_memory_cross_port_overlap_cycles\": "
          << maintenance.memory_cross_port_overlap_cycles << ",\n"
          << "  \"dirty_ack_started\": "
          << (spine_system_->dirty_ack_started() ? 1 : 0) << ",\n"
          << "  \"dirty_ack_status\": " << dirty_ack.status << ",\n"
          << "  \"dirty_ack_cycles\": "
          << (dirty_ack.end_cycle - dirty_ack.start_cycle) << ",\n"
          << "  \"dirty_ack_captured_count\": " << dirty_ack.captured.count
          << ",\n"
          << "  \"dirty_ack_captured_generation\": "
          << dirty_ack.captured.generation << ",\n"
          << "  \"dirty_ack_result_count\": " << dirty_ack.result.count << ",\n"
          << "  \"dirty_ack_result_generation\": "
          << dirty_ack.result.generation << ",\n"
          << "  \"dirty_ack_candidate_write_bytes\": "
          << dirty_ack.candidate_write_bytes << ",\n"
          << "  \"dirty_ack_metadata_read_bytes\": "
          << dirty_ack.metadata_read_bytes << ",\n"
          << "  \"dirty_ack_metadata_write_bytes\": "
          << dirty_ack.metadata_write_bytes << ",\n"
          << "  \"dirty_ack_list_read_bytes\": " << dirty_ack.list_read_bytes
          << ",\n"
          << "  \"dirty_ack_bitmap_read_bytes\": "
          << dirty_ack.bitmap_read_bytes << ",\n"
          << "  \"dirty_ack_bitmap_write_bytes\": "
          << dirty_ack.bitmap_write_bytes << ",\n"
          << "  \"dirty_ack_validated_sources\": "
          << dirty_ack.validated_sources << ",\n"
          << "  \"dirty_ack_cleared_sources\": " << dirty_ack.cleared_sources
          << ",\n"
          << "  \"dirty_ack_generation_advances\": "
          << dirty_ack.generation_advances << ",\n"
          << "  \"final_values\": ";
      write_json_array(result, actual_values);
      result << ",\n  \"frontier_in_sizes\": ";
      write_json_array(result, frontier_in_sizes);
      result << ",\n  \"frontier_out_sizes\": ";
      write_json_array(result, frontier_out_sizes);
      result << ",\n  \"processed_edges_per_round\": ";
      write_json_array(result, processed_edges);
      result << ",\n  \"round_cycles\": ";
      write_json_array(result, round_cycles);
      result << ",\n  \"reader_graph_bytes_per_round\": ";
      write_json_array(result, reader_graph_bytes);
      result << ",\n  \"reader_graph_index_payload_bytes_per_round\": ";
      write_json_array(result, reader_graph_index_payload_bytes);
      result << ",\n  \"reader_graph_payload_bytes_per_round\": ";
      write_json_array(result, reader_graph_payload_bytes);
      result << ",\n  \"reader_construction_payload_bytes_per_round\": ";
      write_json_array(result, reader_construction_payload_bytes);
      result << ",\n  \"reader_replay_payload_bytes_per_round\": ";
      write_json_array(result, reader_replay_payload_bytes);
      result << ",\n  \"reader_graph_index_bitmap_misses_per_round\": ";
      write_json_array(result, reader_graph_index_bitmap_misses);
      result << ",\n  \"reader_range_tasks_per_round\": ";
      write_json_array(result, reader_range_tasks);
      result << ",\n  \"reader_range_row_lookups_per_round\": ";
      write_json_array(result, reader_range_row_lookups);
      result << ",\n  \"reader_range_level_checks_per_round\": ";
      write_json_array(result, reader_range_level_checks);
      result << ",\n  \"reader_range_construction_payloads_per_round\": ";
      write_json_array(result, reader_range_construction_payloads);
      result << ",\n  \"reader_range_replay_payloads_per_round\": ";
      write_json_array(result, reader_range_replay_payloads);
      result << ",\n  \"reader_range_active_records_per_round\": ";
      write_json_array(result, reader_range_active_records);
      result << ",\n  \"reader_range_family_probes_per_round\": ";
      write_json_array(result, reader_range_family_probes);
      result << ",\n  \"reader_range_family_skips_per_round\": ";
      write_json_array(result, reader_range_family_skips);
      result << ",\n  \"reader_fallback_partitions_per_round\": ";
      write_json_array(result, reader_fallback_partitions);
      result << ",\n  \"reader_fallback_forced_dense_partitions_per_round\": ";
      write_json_array(result, reader_fallback_forced_dense_partitions);
      result << ",\n  \"reader_fallback_active_record_reads_per_round\": ";
      write_json_array(result, reader_fallback_active_record_reads);
      result << ",\n  \"reader_fallback_row_lookups_per_round\": ";
      write_json_array(result, reader_fallback_row_lookups);
      result << ",\n  \"reader_fallback_replay_edges_per_round\": ";
      write_json_array(result, reader_fallback_replay_edges);
      result << ",\n  \"reader_range_paths_per_round\": ";
      write_json_array(result, reader_range_paths);
      result << ",\n  \"reader_range_fallback_reasons_per_round\": ";
      write_json_array(result, reader_range_fallback_reasons);
      result << ",\n  \"reader_range_errors_per_round\": ";
      write_json_array(result, reader_range_errors);
      result << ",\n  \"reader_metadata_bytes_per_round\": ";
      write_json_array(result, reader_metadata_bytes);
      result << ",\n  \"reader_metadata_write_bytes_per_round\": ";
      write_json_array(result, reader_metadata_write_bytes);
      result << ",\n  \"reader_result_write_bytes_per_round\": ";
      write_json_array(result, reader_result_write_bytes);
      result << ",\n  \"reader_active_bin_bytes_per_round\": ";
      write_json_array(result, reader_active_bin_bytes);
      result << ",\n  \"reader_dirty_list_bytes_per_round\": ";
      write_json_array(result, reader_dirty_list_bytes);
      result << ",\n  \"reader_dirty_bitmap_bytes_per_round\": ";
      write_json_array(result, reader_dirty_bitmap_bytes);
      result << ",\n  \"reader_memory_requests_issued_per_round\": ";
      write_json_array(result, reader_memory_requests_issued);
      result << ",\n  \"reader_memory_requests_completed_per_round\": ";
      write_json_array(result, reader_memory_requests_completed);
      result << ",\n  \"reader_memory_window_stall_cycles_per_round\": ";
      write_json_array(result, reader_memory_window_stalls);
      result << ",\n  \"reader_memory_dependency_stall_cycles_per_round\": ";
      write_json_array(result, reader_memory_dependency_stalls);
      result << ",\n  \"reader_memory_request_fifo_stall_cycles_per_round\": ";
      write_json_array(result, reader_memory_request_fifo_stalls);
      result << ",\n  \"reader_max_memory_requests_inflight_per_round\": ";
      write_json_array(result, reader_max_memory_requests_inflight);
      result << ",\n  \"reader_construction_pipeline_requests_per_round\": ";
      write_json_array(result, reader_construction_pipeline_requests);
      result << ",\n  \"reader_construction_pipeline_retires_per_round\": ";
      write_json_array(result, reader_construction_pipeline_retires);
      result << ",\n  \"reader_replay_pipeline_requests_per_round\": ";
      write_json_array(result, reader_replay_pipeline_requests);
      result << ",\n  \"reader_replay_pipeline_retires_per_round\": ";
      write_json_array(result, reader_replay_pipeline_retires);
      result << ",\n  \"reader_edge_pipeline_credit_stall_cycles_per_round\": ";
      write_json_array(result, reader_edge_pipeline_credit_stalls);
      result
          << ",\n  "
             "\"reader_edge_pipeline_request_fifo_stall_cycles_per_round\": ";
      write_json_array(result, reader_edge_pipeline_request_fifo_stalls);
      result << ",\n  \"reader_edge_pipeline_axis_stall_cycles_per_round\": ";
      write_json_array(result, reader_edge_pipeline_axis_stalls);
      result << ",\n  \"reader_edge_pipeline_max_inflight_per_round\": ";
      write_json_array(result, reader_edge_pipeline_max_inflight);
      result << ",\n  \"reader_edge_pipeline_max_buffered_per_round\": ";
      write_json_array(result, reader_edge_pipeline_max_buffered);
      result << ",\n  \"reader_source_requests_per_round\": ";
      write_json_array(result, reader_source_requests);
      result << ",\n  \"reader_source_responses_per_round\": ";
      write_json_array(result, reader_source_responses);
      result << ",\n  \"reader_source_windows_per_round\": ";
      write_json_array(result, reader_source_windows);
      result << ",\n  \"reader_protocol_markers_per_round\": ";
      write_json_array(result, reader_protocol_markers);
      result << ",\n  \"reader_protocol_acks_per_round\": ";
      write_json_array(result, reader_protocol_acks);
      result << ",\n  \"reader_protocol_status_per_round\": ";
      write_json_array(result, reader_protocol_status);
      result << ",\n  \"reader_dirty_status_per_round\": ";
      write_json_array(result, reader_dirty_status);
      result << ",\n  \"reader_dirty_counts_per_round\": ";
      write_json_array(result, reader_dirty_counts);
      result << ",\n  \"reader_dirty_generations_per_round\": ";
      write_json_array(result, reader_dirty_generations);
      result << ",\n  \"reader_ack_eligible_per_round\": ";
      write_json_array(result, reader_ack_eligible);
      result << ",\n  \"reader_host_coverage_match_per_round\": ";
      write_json_array(result, reader_host_coverage_match);
      result << ",\n  \"compute_protocol_status_per_round\": ";
      write_json_array(result, compute_protocol_status);
      result << ",\n  \"reader_diagnostic_words_per_round\": ";
      write_json_array(result, reader_diagnostic_words);
      result << ",\n  \"reader_done_words_per_round\": ";
      write_json_array(result, reader_done_words);
      result << ",\n  \"reader_done_overflow_per_round\": ";
      write_json_array(result, reader_done_overflow);
      result << ",\n  \"compute_diagnostic_words_per_round\": ";
      write_json_array(result, compute_diagnostic_words);
      result << ",\n  \"compute_done_words_per_round\": ";
      write_json_array(result, compute_done_words);
      result << ",\n  \"compute_done_overflow_per_round\": ";
      write_json_array(result, compute_done_overflow);
      result << ",\n  \"compute_range_paths_per_round\": ";
      write_json_array(result, compute_range_paths);
      result << ",\n  \"compute_range_fallback_reasons_per_round\": ";
      write_json_array(result, compute_range_fallback_reasons);
      result << ",\n  \"compute_range_errors_per_round\": ";
      write_json_array(result, compute_range_errors);
      result << ",\n  \"compute_range_tasks_per_round\": ";
      write_json_array(result, compute_range_tasks);
      result << ",\n  \"compute_range_row_lookups_per_round\": ";
      write_json_array(result, compute_range_row_lookups);
      result << ",\n  \"compute_range_construction_payloads_per_round\": ";
      write_json_array(result, compute_range_construction_payloads);
      result << ",\n  \"compute_range_replay_payloads_per_round\": ";
      write_json_array(result, compute_range_replay_payloads);
      result << ",\n  \"compute_range_active_records_per_round\": ";
      write_json_array(result, compute_range_active_records);
      result << ",\n  \"compute_range_family_probes_per_round\": ";
      write_json_array(result, compute_range_family_probes);
      result << ",\n  \"compute_range_family_skips_per_round\": ";
      write_json_array(result, compute_range_family_skips);
      result << ",\n  \"compute_dirty_counts_per_round\": ";
      write_json_array(result, compute_dirty_counts);
      result << ",\n  \"compute_dirty_generations_per_round\": ";
      write_json_array(result, compute_dirty_generations);
      result << ",\n  \"reader_epoch_misses_per_round\": ";
      write_json_array(result, reader_epoch_misses);
      result << ",\n  \"reader_source_sizes_per_round\": ";
      write_json_array(result, reader_source_sizes);
      result << ",\n  \"fast_tiles_per_round\": ";
      write_json_array(result, fast_tiles);
      result << ",\n  \"full_tiles_per_round\": ";
      write_json_array(result, full_tiles);
      result << ",\n  \"compute_tiny_buffer_writes_per_round\": ";
      write_json_array(result, compute_tiny_buffer_writes);
      result << ",\n  \"compute_tiny_buffer_reads_per_round\": ";
      write_json_array(result, compute_tiny_buffer_reads);
      result << ",\n  \"compute_tile_active_clear_words_per_round\": ";
      write_json_array(result, compute_tile_active_clear_words);
      result << ",\n  \"compute_sparse_store_scan_words_per_round\": ";
      write_json_array(result, compute_sparse_store_scan_words);
      result << ",\n  \"compute_sparse_store_bit_cycles_per_round\": ";
      write_json_array(result, compute_sparse_store_bit_cycles);
      result << ",\n  \"compute_active_emit_scan_words_per_round\": ";
      write_json_array(result, compute_active_emit_scan_words);
      result << ",\n  \"compute_active_emit_bit_cycles_per_round\": ";
      write_json_array(result, compute_active_emit_bit_cycles);
      result << ",\n  \"compute_on_chip_controller_cycles_per_round\": ";
      write_json_array(result, compute_on_chip_controller_cycles);
      result << ",\n  \"compute_memory_request_window\": "
             << compute_memory_request_window_;
      result << ",\n  \"compute_writeonly_request_window\": "
             << compute_writeonly_request_window_;
      result << ",\n  \"compute_tiny_bram_read_latency\": "
             << compute_on_chip_profile_.tiny_bram_read_latency;
      result << ",\n  \"compute_vs_uram_read_latency\": "
             << compute_on_chip_profile_.vs_uram_read_latency;
      result << ",\n  \"compute_active_bram_read_latency\": "
             << compute_on_chip_profile_.active_bram_read_latency;
      result << ",\n  \"compute_onchip_pipeline_capacity\": "
             << compute_on_chip_profile_.pipeline_capacity;
      result << ",\n  \"compute_vs_bypass_depth\": "
             << compute_on_chip_profile_.vs_bypass_depth;
      result << ",\n  \"compute_memory_requests_issued_per_round\": ";
      write_json_array(result, compute_memory_requests_issued);
      result << ",\n  \"compute_memory_requests_completed_per_round\": ";
      write_json_array(result, compute_memory_requests_completed);
      result << ",\n  \"compute_memory_window_stall_cycles_per_round\": ";
      write_json_array(result, compute_memory_window_stall_cycles);
      result << ",\n  \"compute_max_vertex_requests_inflight_per_round\": ";
      write_json_array(result, compute_max_vertex_requests_inflight);
      result << ",\n  \"compute_max_active_out_requests_inflight_per_round\": ";
      write_json_array(result, compute_max_active_out_requests_inflight);
      result << ",\n  \"compute_max_active_memory_ports_per_round\": ";
      write_json_array(result, compute_max_active_memory_ports);
      result << ",\n  \"compute_memory_cross_port_overlap_cycles_per_round\": ";
      write_json_array(result, compute_memory_cross_port_overlap_cycles);
      result << ",\n  \"compute_max_memory_responses_per_cycle_per_round\": ";
      write_json_array(result, compute_max_memory_responses_per_cycle);
      result << ",\n  \"compute_multi_port_response_cycles_per_round\": ";
      write_json_array(result, compute_multi_port_response_cycles);
      result << ",\n  \"compute_controller_memory_overlap_cycles_per_round\": ";
      write_json_array(result, compute_controller_memory_overlap_cycles);
      result << ",\n  \"compute_controller_memory_stall_cycles_per_round\": ";
      write_json_array(result, compute_controller_memory_stall_cycles);
      result << ",\n  \"compute_sparse_store_writes_generated_per_round\": ";
      write_json_array(result, compute_sparse_store_writes_generated);
      result << ",\n  \"compute_active_emit_writes_generated_per_round\": ";
      write_json_array(result, compute_active_emit_writes_generated);
      result << ",\n  \"compute_tiny_bram_read_requests_per_round\": ";
      write_json_array(result, compute_tiny_bram_read_requests);
      result << ",\n  \"compute_tiny_bram_write_requests_per_round\": ";
      write_json_array(result, compute_tiny_bram_write_requests);
      result << ",\n  \"compute_vs_uram_read_requests_per_round\": ";
      write_json_array(result, compute_vs_uram_read_requests);
      result << ",\n  \"compute_vs_uram_write_requests_per_round\": ";
      write_json_array(result, compute_vs_uram_write_requests);
      result << ",\n  \"compute_active_bram_read_requests_per_round\": ";
      write_json_array(result, compute_active_bram_read_requests);
      result << ",\n  \"compute_active_bram_write_requests_per_round\": ";
      write_json_array(result, compute_active_bram_write_requests);
      result << ",\n  \"compute_on_chip_read_wait_cycles_per_round\": ";
      write_json_array(result, compute_on_chip_read_wait_cycles);
      result << ",\n  \"compute_on_chip_pipeline_stall_cycles_per_round\": ";
      write_json_array(result, compute_on_chip_pipeline_stall_cycles);
      result << ",\n  \"compute_vs_bypass_hits_per_round\": ";
      write_json_array(result, compute_vs_bypass_hits);
      result << ",\n  \"compute_vs_bypass_misses_per_round\": ";
      write_json_array(result, compute_vs_bypass_misses);
      result << ",\n  \"compute_max_tiny_reads_inflight_per_round\": ";
      write_json_array(result, compute_max_tiny_reads_inflight);
      result << ",\n  \"compute_max_vs_reads_inflight_per_round\": ";
      write_json_array(result, compute_max_vs_reads_inflight);
      result << ",\n  \"compute_full_tile_read_beats_per_round\": ";
      write_json_array(result, compute_full_tile_read_beats);
      result << ",\n  \"compute_full_tile_read_words_per_round\": ";
      write_json_array(result, compute_full_tile_read_words);
      result << ",\n  \"compute_full_tile_read_wait_cycles_per_round\": ";
      write_json_array(result, compute_full_tile_read_wait_cycles);
      result << ",\n  \"compute_full_tile_stream_errors_per_round\": ";
      write_json_array(result, compute_full_tile_stream_errors);
      result << ",\n  \"compute_cross_tile_write_overlap_cycles_per_round\": ";
      write_json_array(result, compute_cross_tile_write_overlap_cycles);
      result << ",\n  \"compute_max_cross_tile_writes_inflight_per_round\": ";
      write_json_array(result, compute_max_cross_tile_writes_inflight);
      result << ",\n  \"edge_axis_max_occupancy_per_round\": ";
      write_json_array(result, edge_axis_max_occupancy);
      result << ",\n  \"edge_axis_push_stalls_per_round\": ";
      write_json_array(result, edge_axis_push_stalls);
      result << ",\n  \"edge_axis_transfers_per_round\": ";
      write_json_array(result, edge_axis_transfers);
      result << ",\n  \"value_axis_transfers_per_round\": ";
      write_json_array(result, value_axis_transfers);
      result << ",\n  \"value_axis_max_occupancy_per_round\": ";
      write_json_array(result, value_axis_max_occupancy);
      result << ",\n  \"host_handoff_logical_rounds\": ";
      write_json_array(result, handoff_logical_rounds);
      result << ",\n  \"host_handoff_reasons\": ";
      write_json_array(result, handoff_reasons);
      result << ",\n  \"host_handoff_source_counts\": ";
      write_json_array(result, handoff_source_counts);
      result << ",\n  \"host_handoff_list_read_bytes\": ";
      write_json_array(result, handoff_host_list_read_bytes);
      result << ",\n  \"host_handoff_control_cycles\": ";
      write_json_array(result, handoff_host_control_cycles);
      result << ",\n  \"host_handoff_control_timed\": ";
      write_json_array(result, handoff_host_control_timed);
      result << ",\n  \"host_handoff_device_attempt_cycles\": ";
      write_json_array(result, handoff_device_attempt_cycles);
      result << ",\n  \"host_handoff_device_reader_overflow\": ";
      write_json_array(result, handoff_device_reader_overflow);
      result << ",\n  \"host_handoff_device_compute_overflow\": ";
      write_json_array(result, handoff_device_compute_overflow);
      const SpineComputeCounters first_compute =
          sst_rounds_.empty() ? SpineComputeCounters{}
                              : sst_rounds_.front().compute;
      result << ",\n"
             << "  \"compute_full_recompute_reset_cycles\": "
             << first_compute.full_recompute_reset_cycles << ",\n"
             << "  \"compute_full_recompute_reset_words\": "
             << first_compute.full_recompute_reset_words << ",\n"
             << "  \"compute_full_recompute_reset_write_bytes\": "
             << first_compute.full_recompute_reset_write_bytes << ",\n"
             << "  \"backend_requests\": " << backend_->accepted() << ",\n"
             << "  \"backend_submit_stalls\": " << backend_->submit_stalls()
             << ",\n"
             << "  \"backend_response_queue_stalls\": "
             << backend_->response_queue_stalls() << ",\n"
             << "  \"backend_max_outstanding\": " << backend_->max_outstanding()
             << "\n"
             << "}\n";
      output_.output(
          "completed Spine multi-round SSSP in %zu rounds and %llu core cycles "
          "-> %s\n",
          sst_rounds_.size(),
          static_cast<unsigned long long>(scheduler_.clock(0).completed_cycles),
          result_path_.c_str());
      return;
    }
    if (mode_ == "spine_vertical") {
      std::uint64_t mismatches = 0;
      for (const auto &[vertex, expected] : expected_distances_) {
        if (spine_system_->compute().values().at(vertex) != expected) {
          ++mismatches;
        }
      }
      const std::unordered_set<std::uint32_t> actual_frontier(
          spine_system_->compute().next_active().begin(),
          spine_system_->compute().next_active().end());
      std::uint64_t frontier_mismatches = 0;
      for (const auto &[vertex, expected] : expected_distances_) {
        (void)expected;
        if (!actual_frontier.contains(vertex)) {
          ++frontier_mismatches;
        }
      }
      for (const std::uint32_t vertex : actual_frontier) {
        if (!expected_distances_.contains(vertex)) {
          ++frontier_mismatches;
        }
      }
      const bool passed = success && mismatches == 0 &&
                          frontier_mismatches == 0 &&
                          spine_system_->compute().next_active().size() ==
                              actual_frontier.size();
      const auto &maintenance = spine_system_->maintenance_counters();
      const auto &sorted_axi =
          spine_system_->axi_stats(SpineAxiPortKind::kSortedEdges);
      const auto &reader = spine_system_->reader_counters();
      const auto &compute = spine_system_->compute_counters();
      result
          << "{\n"
          << "  \"success\": " << (passed ? "true" : "false") << ",\n"
          << "  \"mode\": \"spine_vertical\",\n"
          << "  \"backend\": \"sst_memHierarchy_dramsim3\",\n"
          << "  \"spine_axi_profile\": \"" << spine_axi_profile_id_ << "\",\n"
          << "  \"axi_graph_data_width_bytes\": "
          << spine_axi_profile_.graph_bytes << ",\n"
          << "  \"axi_sorted_data_width_bytes\": "
          << spine_axi_profile_.sorted_edge_bytes << ",\n"
          << "  \"axi_active_bin_data_width_bytes\": "
          << spine_axi_profile_.active_bin_bytes << ",\n"
          << "  \"axi_metadata_data_width_bytes\": "
          << spine_axi_profile_.metadata_bytes << ",\n"
          << "  \"axi_max_burst_beats\": " << spine_axi_profile_.max_burst_beats
          << ",\n"
          << "  \"axi_max_outstanding_bursts\": "
          << spine_axi_profile_.max_outstanding_bursts << ",\n"
          << "  \"cycles\": " << scheduler_.clock(0).completed_cycles << ",\n"
          << "  \"maintenance_start_cycle\": " << maintenance.start_cycle
          << ",\n"
          << "  \"maintenance_end_cycle\": " << maintenance.end_cycle
          << ",\n"
          << "  \"maintenance_cycles\": "
          << maintenance.end_cycle - maintenance.start_cycle << ",\n"
          << "  \"sim_time_fs\": "
          << scheduler_.clock(0).next_edge_fs - scheduler_.clock(0).phase_fs
          << ",\n"
          << "  \"input_edges\": " << spine_expected_edges_ << ",\n"
          << "  \"preload_edges\": " << spine_preload_edges_ << ",\n"
          << "  \"memory_request_window\": " << memory_request_window_ << ",\n"
          << "  \"reader_edge_pipeline_depth\": " << reader_edge_pipeline_depth_
          << ",\n"
          << "  \"reader_edge_response_capacity\": "
          << reader_edge_response_capacity_ << ",\n"
          << "  \"maintenance_count_scan_ii\": " << maintenance_count_scan_ii_
          << ",\n"
          << "  \"maintenance_count_scan_tail_cycles\": "
          << maintenance_count_scan_tail_cycles_ << ",\n"
          << "  \"maintenance_l0_write_scan_ii\": "
          << maintenance_l0_write_scan_ii_ << ",\n"
          << "  \"maintenance_l0_write_scan_tail_cycles\": "
          << maintenance_l0_write_scan_tail_cycles_ << ",\n"
          << "  \"maintenance_scan_response_capacity\": "
          << maintenance_scan_response_capacity_ << ",\n"
          << "  \"correctness_mismatches\": " << mismatches << ",\n"
          << "  \"frontier_mismatches\": " << frontier_mismatches << ",\n"
          << "  \"next_active\": "
          << spine_system_->compute().next_active().size() << ",\n"
          << "  \"maintenance_scan_passes\": " << maintenance.sorted_scan_passes
          << ",\n"
          << "  \"maintenance_edge_visits\": " << maintenance.sorted_edge_visits
          << ",\n"
          << "  \"maintenance_sorted_bytes\": " << maintenance.sorted_read_bytes
          << ",\n"
          << "  \"maintenance_sorted_payload_read_bytes\": "
          << maintenance.sorted_payload_read_bytes << ",\n"
          << "  \"maintenance_sorted_read_beats\": "
          << maintenance.sorted_read_beats_received << ",\n"
          << "  \"maintenance_scan_response_stall_cycles\": "
          << maintenance.sorted_scan_response_stall_cycles << ",\n"
          << "  \"maintenance_scan_reorder_full_stall_cycles\": "
          << maintenance.sorted_scan_reorder_full_stall_cycles << ",\n"
          << "  \"maintenance_scan_ii_stall_cycles\": "
          << maintenance.sorted_scan_ii_stall_cycles << ",\n"
          << "  \"maintenance_scan_tail_cycles\": "
          << maintenance.sorted_scan_tail_cycles << ",\n"
          << "  \"maintenance_max_scan_buffered_edges\": "
          << maintenance.max_sorted_scan_buffered_edges << ",\n"
          << "  \"maintenance_sorted_axi_read_beat_fifo_stall_cycles\": "
          << sorted_axi.read_beat_queue_stalls << ",\n"
          << "  \"maintenance_sorted_axi_read_reorder_stall_cycles\": "
          << sorted_axi.read_reorder_stalls << ",\n"
          << "  \"maintenance_sorted_axi_read_beats_streamed\": "
          << sorted_axi.read_beats_streamed << ",\n"
          << "  \"maintenance_dirty_validate_visits\": "
          << maintenance.dirty_validate_edge_visits << ",\n"
          << "  \"maintenance_dirty_mark_visits\": "
          << maintenance.dirty_mark_edge_visits << ",\n"
          << "  \"maintenance_dirty_unique_sources\": "
          << maintenance.unique_sources << ",\n"
          << "  \"maintenance_dirty_bitmap_reads\": "
          << maintenance.dirty_bitmap_reads << ",\n"
          << "  \"maintenance_dirty_bitmap_writes\": "
          << maintenance.dirty_bitmap_writes << ",\n"
          << "  \"maintenance_dirty_list_reads\": "
          << maintenance.dirty_list_reads << ",\n"
          << "  \"maintenance_dirty_list_appends\": "
          << maintenance.dirty_list_appends << ",\n"
          << "  \"maintenance_dirty_duplicates_suppressed\": "
          << maintenance.dirty_duplicates_suppressed << ",\n"
          << "  \"maintenance_dirty_generation_advances\": "
          << maintenance.dirty_generation_advances << ",\n"
          << "  \"maintenance_dirty_count\": " << maintenance.dirty_count
          << ",\n"
          << "  \"maintenance_dirty_generation\": "
          << maintenance.dirty_generation << ",\n"
          << "  \"maintenance_dirty_hash_sum\": "
          << maintenance.dirty_hash_sum << ",\n"
          << "  \"maintenance_dirty_hash_xor\": "
          << maintenance.dirty_hash_xor << ",\n"
          << "  \"maintenance_hot_cold_count_visits\": "
          << maintenance.hot_cold_count_edge_visits << ",\n"
          << "  \"maintenance_family_precount_visits\": "
          << maintenance.family_precount_edge_visits << ",\n"
          << "  \"maintenance_l0_write_visits\": "
          << maintenance.l0_write_edge_visits << ",\n"
          << "  \"maintenance_target_selector_invocations\": "
          << maintenance.target_selector_invocations << ",\n"
          << "  \"maintenance_target_selector_levels_scanned\": "
          << maintenance.target_selector_levels_scanned << ",\n"
          << "  \"maintenance_target_selector_family_iterations\": "
          << maintenance.target_selector_family_iterations << ",\n"
          << "  \"maintenance_target_selector_metadata_reads\": "
          << maintenance.target_selector_metadata_reads << ",\n"
          << "  \"maintenance_target_selector_payload_read_bytes\": "
          << maintenance.target_selector_payload_read_bytes << ",\n"
          << "  \"maintenance_target_selector_responses\": "
          << maintenance.target_selector_responses << ",\n"
          << "  \"maintenance_target_selector_cycles\": "
          << maintenance.target_selector_cycles << ",\n"
          << "  \"maintenance_target_selector_min_padding_cycles\": "
          << maintenance.target_selector_min_padding_cycles << ",\n"
          << "  \"maintenance_target_selector_validation_failures\": "
          << maintenance.target_selector_validation_failures << ",\n"
          << "  \"maintenance_target_selector_max_inflight\": "
          << maintenance.target_selector_max_inflight << ",\n"
          << "  \"maintenance_metadata_control_reads\": "
          << maintenance.metadata_control_reads << ",\n"
          << "  \"maintenance_metadata_control_payload_read_bytes\": "
          << maintenance.metadata_control_payload_read_bytes << ",\n"
          << "  \"maintenance_hot_bitmap_reads\": "
          << maintenance.hot_bitmap_reads << ",\n"
          << "  \"maintenance_hot_bitmap_scan_reads\": "
          << maintenance.hot_bitmap_scan_reads << ",\n"
          << "  \"maintenance_hot_bitmap_carry_reads\": "
          << maintenance.hot_bitmap_carry_reads << ",\n"
          << "  \"maintenance_hot_bitmap_responses\": "
          << maintenance.hot_bitmap_responses << ",\n"
          << "  \"maintenance_hot_bitmap_payload_read_bytes\": "
          << maintenance.hot_bitmap_payload_read_bytes << ",\n"
          << "  \"maintenance_hot_bitmap_scan_wait_cycles\": "
          << maintenance.hot_bitmap_scan_wait_cycles << ",\n"
          << "  \"maintenance_hot_bitmap_validation_failures\": "
          << maintenance.hot_bitmap_validation_failures << ",\n"
          << "  \"maintenance_hot_bitmap_max_inflight\": "
          << maintenance.hot_bitmap_max_inflight << ",\n"
          << "  \"maintenance_result_metadata_reads\": "
          << maintenance.result_metadata_reads << ",\n"
          << "  \"maintenance_result_metadata_responses\": "
          << maintenance.result_metadata_responses << ",\n"
          << "  \"maintenance_result_metadata_payload_read_bytes\": "
          << maintenance.result_metadata_payload_read_bytes << ",\n"
          << "  \"maintenance_result_metadata_max_inflight\": "
          << maintenance.result_metadata_max_inflight << ",\n"
          << "  \"maintenance_result_payload_write_bytes\": "
          << maintenance.result_payload_write_bytes << ",\n"
          << "  \"maintenance_result_write_responses\": "
          << maintenance.result_write_responses << ",\n"
          << "  \"maintenance_result_validation_failures\": "
          << maintenance.result_validation_failures << ",\n"
          << "  \"maintenance_logical_overflow_events\": "
          << maintenance.logical_overflow_events << ",\n"
          << "  \"maintenance_slice_epoch_reads\": "
          << maintenance.slice_epoch_reads << ",\n"
          << "  \"maintenance_slice_epoch_responses\": "
          << maintenance.slice_epoch_responses << ",\n"
          << "  \"maintenance_slice_epoch_payload_read_bytes\": "
          << maintenance.slice_epoch_payload_read_bytes << ",\n"
          << "  \"maintenance_slice_epoch_validation_failures\": "
          << maintenance.slice_epoch_validation_failures << ",\n"
          << "  \"maintenance_epoch_full_clear_fallbacks\": "
          << maintenance.epoch_full_clear_fallbacks << ",\n"
          << "  \"maintenance_epoch_wrap_events\": "
          << maintenance.epoch_wrap_events << ",\n"
          << "  \"maintenance_epoch_commit_failures\": "
          << maintenance.epoch_commit_failures << ",\n"
          << "  \"maintenance_epoch_clear_parent_writes\": "
          << maintenance.epoch_clear_parent_writes << ",\n"
          << "  \"maintenance_epoch_clear_word_writes\": "
          << maintenance.epoch_clear_word_writes << ",\n"
          << "  \"maintenance_epoch_clear_payload_write_bytes\": "
          << maintenance.epoch_clear_payload_write_bytes << ",\n"
          << "  \"maintenance_epoch_clear_write_responses\": "
          << maintenance.epoch_clear_write_responses << ",\n"
          << "  \"maintenance_epoch_clear_wait_cycles\": "
          << maintenance.epoch_clear_wait_cycles << ",\n"
          << "  \"maintenance_epoch_retire_writes\": "
          << maintenance.epoch_retire_writes << ",\n"
          << "  \"maintenance_epoch_retire_write_responses\": "
          << maintenance.epoch_retire_write_responses << ",\n"
          << "  \"maintenance_target_level\": " << maintenance.target_level
          << ",\n"
          << "  \"maintenance_hot_target_level\": "
          << maintenance.hot_target_level << ",\n"
          << "  \"maintenance_cold_input_edges\": "
          << maintenance.cold_input_edges << ",\n"
          << "  \"maintenance_hot_input_edges\": "
          << maintenance.hot_input_edges << ",\n"
          << "  \"maintenance_carry_payload_reads\": "
          << maintenance.carry_level_payload_reads << ",\n"
          << "  \"maintenance_carry_payload_read_bytes\": "
          << maintenance.carry_level_payload_read_bytes << ",\n"
          << "  \"maintenance_carry_new_batch_reads\": "
          << maintenance.carry_new_batch_reads << ",\n"
          << "  \"maintenance_carry_new_batch_read_bytes\": "
          << maintenance.carry_new_batch_read_bytes << ",\n"
          << "  \"maintenance_carry_refill_wait_cycles\": "
          << maintenance.carry_refill_wait_cycles << ",\n"
          << "  \"maintenance_carry_cursor_metadata_read_bytes\": "
          << maintenance.carry_cursor_metadata_read_bytes << ",\n"
          << "  \"maintenance_carry_cursor_page_ids\": "
          << maintenance.carry_cursor_page_ids << ",\n"
          << "  \"maintenance_carry_cursor_pages_visited\": "
          << maintenance.carry_cursor_pages_visited << ",\n"
          << "  \"maintenance_carry_cursor_bitmap_words\": "
          << maintenance.carry_cursor_bitmap_words << ",\n"
          << "  \"maintenance_carry_cursor_bits_inspected\": "
          << maintenance.carry_cursor_bits_inspected << ",\n"
          << "  \"maintenance_carry_cursor_refill_cycles\": "
          << maintenance.carry_cursor_refill_cycles << ",\n"
          << "  \"maintenance_carry_cursor_rows_entered\": "
          << maintenance.carry_cursor_rows_entered << ",\n"
          << "  \"maintenance_carry_cursor_row_offset_reads\": "
          << maintenance.carry_cursor_row_offset_reads << ",\n"
          << "  \"maintenance_carry_cursor_validation_failures\": "
          << maintenance.carry_cursor_validation_failures << ",\n"
          << "  \"maintenance_carry_writer_groups_seen\": "
          << maintenance.carry_writer_groups_seen << ",\n"
          << "  \"maintenance_carry_writer_groups_emitted\": "
          << maintenance.carry_writer_groups_emitted << ",\n"
          << "  \"maintenance_carry_writer_groups_cancelled\": "
          << maintenance.carry_writer_groups_cancelled << ",\n"
          << "  \"maintenance_carry_writer_edge_word_writes\": "
          << maintenance.carry_writer_edge_word_writes << ",\n"
          << "  \"maintenance_carry_writer_row_word_writes\": "
          << maintenance.carry_writer_row_word_writes << ",\n"
          << "  \"maintenance_carry_writer_mask_word_writes\": "
          << maintenance.carry_writer_mask_word_writes << ",\n"
          << "  \"maintenance_carry_writer_page_base_word_writes\": "
          << maintenance.carry_writer_page_base_word_writes << ",\n"
          << "  \"maintenance_carry_writer_bitmap_page_writes\": "
          << maintenance.carry_writer_bitmap_page_writes << ",\n"
          << "  \"maintenance_carry_writer_page_list_word_writes\": "
          << maintenance.carry_writer_page_list_word_writes << ",\n"
          << "  \"maintenance_carry_writer_page_epoch_word_writes\": "
          << maintenance.carry_writer_page_epoch_word_writes << ",\n"
          << "  \"maintenance_carry_writer_memory_wait_cycles\": "
          << maintenance.carry_writer_memory_wait_cycles << ",\n"
          << "  \"maintenance_l0_writer_groups_seen\": "
          << maintenance.l0_writer_groups_seen << ",\n"
          << "  \"maintenance_l0_writer_groups_emitted\": "
          << maintenance.l0_writer_groups_emitted << ",\n"
          << "  \"maintenance_l0_writer_groups_cancelled\": "
          << maintenance.l0_writer_groups_cancelled << ",\n"
          << "  \"maintenance_l0_writer_edge_word_writes\": "
          << maintenance.l0_writer_edge_word_writes << ",\n"
          << "  \"maintenance_l0_writer_row_word_writes\": "
          << maintenance.l0_writer_row_word_writes << ",\n"
          << "  \"maintenance_l0_writer_mask_word_writes\": "
          << maintenance.l0_writer_mask_word_writes << ",\n"
          << "  \"maintenance_l0_writer_page_base_word_writes\": "
          << maintenance.l0_writer_page_base_word_writes << ",\n"
          << "  \"maintenance_l0_writer_bitmap_page_writes\": "
          << maintenance.l0_writer_bitmap_page_writes << ",\n"
          << "  \"maintenance_l0_writer_page_list_word_writes\": "
          << maintenance.l0_writer_page_list_word_writes << ",\n"
          << "  \"maintenance_l0_writer_page_epoch_word_writes\": "
          << maintenance.l0_writer_page_epoch_word_writes << ",\n"
          << "  \"maintenance_l0_writer_memory_wait_cycles\": "
          << maintenance.l0_writer_memory_wait_cycles << ",\n"
          << "  \"maintenance_l0_writer_memory_overlap_cycles\": "
          << maintenance.l0_writer_memory_overlap_cycles << ",\n"
          << "  \"maintenance_l0_writer_backpressure_stall_cycles\": "
          << maintenance.l0_writer_backpressure_stall_cycles << ",\n"
          << "  \"maintenance_l0_writer_validation_failures\": "
          << maintenance.l0_writer_validation_failures << ",\n"
          << "  \"maintenance_l0_writer_max_pending_tasks\": "
          << maintenance.l0_writer_max_pending_tasks << ",\n"
          << "  \"maintenance_l0_writer_max_pending_tasks_per_port\": "
          << maintenance.l0_writer_max_pending_tasks_per_port << ",\n"
          << "  \"maintenance_carry_max_buffered_heads\": "
          << maintenance.carry_max_buffered_heads << ",\n"
          << "  \"maintenance_carry_merge_inputs\": "
          << maintenance.carry_merge_inputs << ",\n"
          << "  \"maintenance_carry_outputs\": " << maintenance.carry_outputs
          << ",\n"
          << "  \"maintenance_graph_index_payload_write_bytes\": "
          << maintenance.graph_index_payload_write_bytes << ",\n"
          << "  \"maintenance_graph_payload_write_bytes\": "
          << maintenance.graph_edge_payload_write_bytes << ",\n"
          << "  \"maintenance_page_list_payload_write_bytes\": "
          << maintenance.page_list_payload_write_bytes << ",\n"
          << "  \"maintenance_page_list_count_write_bytes\": "
          << maintenance.page_list_count_write_bytes << ",\n"
          << "  \"maintenance_memory_requests_issued\": "
          << maintenance.memory_requests_issued << ",\n"
          << "  \"maintenance_memory_requests_completed\": "
          << maintenance.memory_requests_completed << ",\n"
          << "  \"maintenance_memory_window_stall_cycles\": "
          << maintenance.memory_window_stall_cycles << ",\n"
          << "  \"maintenance_memory_dependency_stall_cycles\": "
          << maintenance.memory_dependency_stall_cycles << ",\n"
          << "  \"maintenance_memory_request_fifo_stall_cycles\": "
          << maintenance.memory_request_fifo_stall_cycles << ",\n"
          << "  \"maintenance_max_memory_requests_issued_per_cycle\": "
          << maintenance.max_memory_requests_issued_per_cycle << ",\n"
          << "  \"maintenance_max_memory_responses_completed_per_cycle\": "
          << maintenance.max_memory_responses_completed_per_cycle << ",\n"
          << "  \"maintenance_multi_port_issue_cycles\": "
          << maintenance.multi_port_issue_cycles << ",\n"
          << "  \"maintenance_multi_port_response_cycles\": "
          << maintenance.multi_port_response_cycles << ",\n"
          << "  \"maintenance_max_memory_requests_inflight\": "
          << maintenance.max_memory_requests_inflight << ",\n"
          << "  \"maintenance_max_memory_requests_inflight_per_port\": "
          << maintenance.max_memory_requests_inflight_per_port << ",\n"
          << "  \"maintenance_max_non_target_memory_requests_inflight_per_port\": "
          << maintenance.max_non_target_memory_requests_inflight_per_port
          << ",\n"
          << "  \"maintenance_max_active_memory_ports\": "
          << maintenance.max_active_memory_ports << ",\n"
          << "  \"maintenance_memory_cross_port_overlap_cycles\": "
          << maintenance.memory_cross_port_overlap_cycles << ",\n"
          << "  \"reader_tiles\": " << reader.tiles_emitted << ",\n"
          << "  \"reader_edges\": " << reader.edges_emitted << ",\n"
          << "  \"reader_graph_bytes\": " << reader.graph_read_bytes << ",\n"
          << "  \"reader_graph_index_payload_bytes\": "
          << reader.graph_index_payload_read_bytes << ",\n"
          << "  \"reader_graph_payload_bytes\": "
          << reader.graph_edge_payload_read_bytes << ",\n"
          << "  \"reader_construction_payload_bytes\": "
          << reader.graph_construction_payload_read_bytes << ",\n"
          << "  \"reader_replay_payload_bytes\": "
          << reader.graph_replay_payload_read_bytes << ",\n"
          << "  \"reader_graph_index_bitmap_misses\": "
          << reader.graph_index_bitmap_misses << ",\n"
          << "  \"reader_graph_index_bitmap_words\": "
          << reader.graph_index_bitmap_words << ",\n"
          << "  \"reader_range_active_records\": "
          << reader.range_task_active_records << ",\n"
          << "  \"reader_range_family_probes\": "
          << reader.range_task_family_probes << ",\n"
          << "  \"reader_range_family_skips\": "
          << reader.range_task_family_skips << ",\n"
          << "  \"reader_range_level_checks\": "
          << reader.range_task_level_checks << ",\n"
          << "  \"reader_range_row_lookups\": " << reader.range_task_row_lookups
          << ",\n"
          << "  \"reader_range_construction_payloads\": "
          << reader.range_task_construction_payloads << ",\n"
          << "  \"reader_range_tasks\": " << reader.range_task_count << ",\n"
          << "  \"reader_range_replay_payloads\": "
          << reader.range_task_replay_payloads << ",\n"
          << "  \"reader_range_clear_cycles\": "
          << reader.range_task_clear_cycles << ",\n"
          << "  \"reader_range_prefix_cycles\": "
          << reader.range_task_prefix_cycles << ",\n"
          << "  \"reader_range_scatter_cycles\": "
          << reader.range_task_scatter_cycles << ",\n"
          << "  \"reader_range_verify_cycles\": "
          << reader.range_task_verify_cycles << ",\n"
          << "  \"reader_range_path\": " << reader.range_task_path << ",\n"
          << "  \"reader_range_fallback_reason\": "
          << reader.range_task_fallback_reason << ",\n"
          << "  \"reader_range_error\": " << reader.range_task_error << ",\n"
          << "  \"reader_metadata_bytes\": " << reader.metadata_read_bytes
          << ",\n"
          << "  \"reader_metadata_write_bytes\": "
          << reader.metadata_write_bytes << ",\n"
          << "  \"reader_result_write_bytes\": " << reader.result_write_bytes
          << ",\n"
          << "  \"reader_active_bin_bytes\": " << reader.active_bin_read_bytes
          << ",\n"
          << "  \"reader_dirty_list_bytes\": " << reader.dirty_list_read_bytes
          << ",\n"
          << "  \"reader_dirty_bitmap_bytes\": "
          << reader.dirty_bitmap_read_bytes << ",\n"
          << "  \"reader_memory_requests_issued\": "
          << reader.memory_requests_issued << ",\n"
          << "  \"reader_memory_requests_completed\": "
          << reader.memory_requests_completed << ",\n"
          << "  \"reader_memory_window_stall_cycles\": "
          << reader.memory_window_stall_cycles << ",\n"
          << "  \"reader_memory_dependency_stall_cycles\": "
          << reader.memory_dependency_stall_cycles << ",\n"
          << "  \"reader_memory_request_fifo_stall_cycles\": "
          << reader.memory_request_fifo_stall_cycles << ",\n"
          << "  \"reader_max_memory_requests_inflight\": "
          << reader.max_memory_requests_inflight << ",\n"
          << "  \"reader_max_memory_requests_inflight_per_port\": "
          << reader.max_memory_requests_inflight_per_port << ",\n"
          << "  \"reader_max_active_memory_ports\": "
          << reader.max_active_memory_ports << ",\n"
          << "  \"reader_memory_cross_port_overlap_cycles\": "
          << reader.memory_cross_port_overlap_cycles << ",\n"
          << "  \"reader_construction_pipeline_requests\": "
          << reader.construction_pipeline_requests << ",\n"
          << "  \"reader_construction_pipeline_retires\": "
          << reader.construction_pipeline_retires << ",\n"
          << "  \"reader_replay_pipeline_requests\": "
          << reader.replay_pipeline_requests << ",\n"
          << "  \"reader_replay_pipeline_retires\": "
          << reader.replay_pipeline_retires << ",\n"
          << "  \"reader_edge_pipeline_credit_stall_cycles\": "
          << reader.edge_pipeline_credit_stall_cycles << ",\n"
          << "  \"reader_edge_pipeline_request_fifo_stall_cycles\": "
          << reader.edge_pipeline_request_fifo_stall_cycles << ",\n"
          << "  \"reader_edge_pipeline_axis_stall_cycles\": "
          << reader.edge_pipeline_axis_stall_cycles << ",\n"
          << "  \"reader_edge_pipeline_max_inflight\": "
          << reader.edge_pipeline_max_inflight << ",\n"
          << "  \"reader_edge_pipeline_max_buffered\": "
          << reader.edge_pipeline_max_buffered << ",\n"
          << "  \"reader_source_requests\": " << reader.source_requests << ",\n"
          << "  \"reader_source_responses\": " << reader.source_responses
          << ",\n"
          << "  \"reader_source_windows\": " << reader.source_request_windows
          << ",\n"
          << "  \"reader_protocol_markers\": " << reader.source_protocol_markers
          << ",\n"
          << "  \"reader_protocol_acks\": " << reader.source_protocol_acks
          << ",\n"
          << "  \"reader_protocol_status\": " << reader.source_protocol_status
          << ",\n"
          << "  \"reader_dirty_status\": " << reader.dirty_status << ",\n"
          << "  \"reader_dirty_count\": " << reader.dirty_count << ",\n"
          << "  \"reader_dirty_generation\": " << reader.dirty_generation
          << ",\n"
          << "  \"reader_ack_eligible\": "
          << (reader.acknowledgement_eligible ? 1 : 0) << ",\n"
          << "  \"reader_host_coverage_match\": "
          << (reader.host_coverage_match ? 1 : 0) << ",\n"
          << "  \"reader_diagnostic_words\": " << reader.diagnostic_words
          << ",\n"
          << "  \"reader_done_words\": " << reader.done_words << ",\n"
          << "  \"reader_done_overflow\": " << (reader.done_overflow ? 1 : 0)
          << ",\n"
          << "  \"compute_protocol_markers\": "
          << compute.source_protocol_markers << ",\n"
          << "  \"compute_protocol_acks\": " << compute.source_protocol_acks
          << ",\n"
          << "  \"compute_protocol_status\": " << compute.source_protocol_status
          << ",\n"
          << "  \"compute_diagnostic_words\": " << compute.diagnostic_words
          << ",\n"
          << "  \"compute_done_words\": " << compute.done_words << ",\n"
          << "  \"compute_done_overflow\": " << (compute.done_overflow ? 1 : 0)
          << ",\n"
          << "  \"compute_range_path\": " << compute.range_task_path << ",\n"
          << "  \"compute_range_fallback_reason\": "
          << compute.range_task_fallback_reason << ",\n"
          << "  \"compute_range_error\": " << compute.range_task_error << ",\n"
          << "  \"compute_range_tasks\": " << compute.range_task_count << ",\n"
          << "  \"compute_range_row_lookups\": "
          << compute.range_task_row_lookups << ",\n"
          << "  \"compute_range_construction_payloads\": "
          << compute.range_task_construction_payloads << ",\n"
          << "  \"compute_range_replay_payloads\": "
          << compute.range_task_replay_payloads << ",\n"
          << "  \"compute_range_active_records\": "
          << compute.range_task_active_records << ",\n"
          << "  \"compute_range_family_probes\": "
          << compute.range_task_family_probes << ",\n"
          << "  \"compute_range_family_skips\": "
          << compute.range_task_family_skips << ",\n"
          << "  \"compute_dirty_count\": " << compute.dirty_count << ",\n"
          << "  \"compute_dirty_generation\": " << compute.dirty_generation
          << ",\n"
          << "  \"reader_page_epoch_misses\": "
          << reader.graph_index_epoch_misses << ",\n"
          << "  \"reader_occupied_levels\": " << reader.occupied_levels << ",\n"
          << "  \"reader_cold_edges\": " << reader.cold_edges_emitted << ",\n"
          << "  \"reader_hot_edges\": " << reader.hot_edges_emitted << ",\n"
          << "  \"compute_fast_tiles\": " << compute.fast_path_tiles << ",\n"
          << "  \"compute_full_tiles\": " << compute.full_path_tiles << ",\n"
          << "  \"compute_processed_edges\": " << compute.processed_edges
          << ",\n"
          << "  \"compute_gathered_words\": " << compute.gathered_vertex_words
          << ",\n"
          << "  \"compute_swept_words\": " << compute.swept_vertex_words
          << ",\n"
          << "  \"compute_scattered_words\": " << compute.scattered_vertex_words
          << ",\n"
          << "  \"compute_tiny_buffer_writes\": "
          << compute.tiny_buffer_writes << ",\n"
          << "  \"compute_tiny_buffer_reads\": " << compute.tiny_buffer_reads
          << ",\n"
          << "  \"compute_vs_tile_reads\": " << compute.vs_tile_reads
          << ",\n"
          << "  \"compute_vs_tile_writes\": " << compute.vs_tile_writes
          << ",\n"
          << "  \"compute_tile_active_clear_words\": "
          << compute.tile_active_clear_words << ",\n"
          << "  \"compute_tile_active_clear_lane_writes\": "
          << compute.tile_active_clear_lane_writes << ",\n"
          << "  \"compute_tile_active_mark_writes\": "
          << compute.tile_active_mark_writes << ",\n"
          << "  \"compute_sparse_store_scan_words\": "
          << compute.sparse_store_scan_words << ",\n"
          << "  \"compute_sparse_store_lane_reads\": "
          << compute.sparse_store_lane_reads << ",\n"
          << "  \"compute_sparse_store_bit_cycles\": "
          << compute.sparse_store_bit_cycles << ",\n"
          << "  \"compute_active_emit_scan_words\": "
          << compute.active_emit_scan_words << ",\n"
          << "  \"compute_active_emit_lane_reads\": "
          << compute.active_emit_lane_reads << ",\n"
          << "  \"compute_active_emit_lane_writes\": "
          << compute.active_emit_lane_writes << ",\n"
          << "  \"compute_active_emit_bit_cycles\": "
          << compute.active_emit_bit_cycles << ",\n"
          << "  \"compute_on_chip_controller_cycles\": "
          << compute.on_chip_controller_cycles << ",\n"
          << "  \"compute_memory_request_window\": "
          << compute_memory_request_window_ << ",\n"
          << "  \"compute_writeonly_request_window\": "
          << compute_writeonly_request_window_ << ",\n"
          << "  \"compute_tiny_bram_read_latency\": "
          << compute_on_chip_profile_.tiny_bram_read_latency << ",\n"
          << "  \"compute_vs_uram_read_latency\": "
          << compute_on_chip_profile_.vs_uram_read_latency << ",\n"
          << "  \"compute_active_bram_read_latency\": "
          << compute_on_chip_profile_.active_bram_read_latency << ",\n"
          << "  \"compute_onchip_pipeline_capacity\": "
          << compute_on_chip_profile_.pipeline_capacity << ",\n"
          << "  \"compute_vs_bypass_depth\": "
          << compute_on_chip_profile_.vs_bypass_depth << ",\n"
          << "  \"compute_memory_requests_issued\": "
          << compute.memory_requests_issued << ",\n"
          << "  \"compute_memory_requests_completed\": "
          << compute.memory_requests_completed << ",\n"
          << "  \"compute_memory_window_stall_cycles\": "
          << compute.memory_window_stall_cycles << ",\n"
          << "  \"compute_memory_dependency_stall_cycles\": "
          << compute.memory_dependency_stall_cycles << ",\n"
          << "  \"compute_memory_request_fifo_stall_cycles\": "
          << compute.memory_request_fifo_stall_cycles << ",\n"
          << "  \"compute_max_memory_requests_inflight\": "
          << compute.max_memory_requests_inflight << ",\n"
          << "  \"compute_max_vertex_requests_inflight\": "
          << compute.max_vertex_requests_inflight << ",\n"
          << "  \"compute_max_active_out_requests_inflight\": "
          << compute.max_active_out_requests_inflight << ",\n"
          << "  \"compute_max_active_memory_ports\": "
          << compute.max_active_memory_ports << ",\n"
          << "  \"compute_memory_cross_port_overlap_cycles\": "
          << compute.memory_cross_port_overlap_cycles << ",\n"
          << "  \"compute_max_memory_responses_per_cycle\": "
          << compute.max_memory_responses_completed_per_cycle << ",\n"
          << "  \"compute_multi_port_response_cycles\": "
          << compute.multi_port_response_cycles << ",\n"
          << "  \"compute_controller_memory_overlap_cycles\": "
          << compute.controller_memory_overlap_cycles << ",\n"
          << "  \"compute_controller_memory_stall_cycles\": "
          << compute.controller_memory_stall_cycles << ",\n"
          << "  \"compute_sparse_store_writes_generated\": "
          << compute.sparse_store_writes_generated << ",\n"
          << "  \"compute_active_emit_writes_generated\": "
          << compute.active_emit_writes_generated << ",\n"
          << "  \"compute_tiny_bram_read_requests\": "
          << compute.tiny_bram_read_requests << ",\n"
          << "  \"compute_tiny_bram_write_requests\": "
          << compute.tiny_bram_write_requests << ",\n"
          << "  \"compute_vs_uram_read_requests\": "
          << compute.vs_uram_read_requests << ",\n"
          << "  \"compute_vs_uram_write_requests\": "
          << compute.vs_uram_write_requests << ",\n"
          << "  \"compute_active_bram_read_requests\": "
          << compute.active_bram_read_requests << ",\n"
          << "  \"compute_active_bram_write_requests\": "
          << compute.active_bram_write_requests << ",\n"
          << "  \"compute_on_chip_read_wait_cycles\": "
          << compute.on_chip_read_wait_cycles << ",\n"
          << "  \"compute_on_chip_pipeline_stall_cycles\": "
          << compute.on_chip_pipeline_stall_cycles << ",\n"
          << "  \"compute_vs_bypass_hits\": "
          << compute.vs_bypass_hits << ",\n"
          << "  \"compute_vs_bypass_misses\": "
          << compute.vs_bypass_misses << ",\n"
          << "  \"compute_max_tiny_reads_inflight\": "
          << compute.max_tiny_reads_inflight << ",\n"
          << "  \"compute_max_vs_reads_inflight\": "
          << compute.max_vs_reads_inflight << ",\n"
          << "  \"compute_full_tile_read_beats\": "
          << compute.full_tile_read_beats << ",\n"
          << "  \"compute_full_tile_read_words\": "
          << compute.full_tile_read_words << ",\n"
          << "  \"compute_full_tile_read_wait_cycles\": "
          << compute.full_tile_read_wait_cycles << ",\n"
          << "  \"compute_full_tile_stream_errors\": "
          << compute.full_tile_stream_error_count << ",\n"
          << "  \"compute_cross_tile_write_overlap_cycles\": "
          << compute.cross_tile_write_overlap_cycles << ",\n"
          << "  \"compute_max_cross_tile_writes_inflight\": "
          << compute.max_cross_tile_writes_inflight << ",\n"
          << "  \"compute_full_buffer_replay_edges\": "
          << compute.full_buffer_replay_edges << ",\n"
          << "  \"compute_full_overflow_edges\": "
          << compute.full_overflow_edges << ",\n"
          << "  \"compute_full_stream_edges\": " << compute.full_stream_edges
          << ",\n"
          << "  \"edge_axis_transfers\": "
          << spine_system_->edge_stream_stats().pushes << ",\n"
          << "  \"edge_axis_max_occupancy\": "
          << spine_system_->edge_stream_stats().max_occupancy << ",\n"
          << "  \"value_axis_transfers\": "
          << spine_system_->value_stream_stats().pushes << ",\n"
          << "  \"value_axis_max_occupancy\": "
          << spine_system_->value_stream_stats().max_occupancy << ",\n"
          << "  \"backend_requests\": " << backend_->accepted() << ",\n"
          << "  \"backend_submit_stalls\": " << backend_->submit_stalls()
          << ",\n"
          << "  \"backend_response_queue_stalls\": "
          << backend_->response_queue_stalls() << ",\n"
          << "  \"backend_max_outstanding\": " << backend_->max_outstanding()
          << "\n"
          << "}\n";
      output_.output(
          "completed Spine vertical slice in %llu core cycles -> %s\n",
          static_cast<unsigned long long>(scheduler_.clock(0).completed_cycles),
          result_path_.c_str());
      return;
    }
    const auto &stats = axi_->stats();
    result << "{\n"
           << "  \"success\": " << (success ? "true" : "false") << ",\n"
           << "  \"backend\": \"sst_memHierarchy_dramsim3\",\n"
           << "  \"cycles\": " << scheduler_.clock(0).completed_cycles << ",\n"
           << "  \"sim_time_fs\": "
           << scheduler_.clock(0).next_edge_fs - scheduler_.clock(0).phase_fs
           << ",\n"
           << "  \"requests_issued\": " << source_->issued() << ",\n"
           << "  \"requests_completed\": " << sink_->completed() << ",\n"
           << "  \"requests_failed\": " << sink_->failed() << ",\n"
           << "  \"axi_bursts\": " << stats.bursts_accepted << ",\n"
           << "  \"axi_beats\": " << stats.beats_issued << ",\n"
           << "  \"axi_read_bytes\": " << stats.read_bytes << ",\n"
           << "  \"axi_write_bytes\": " << stats.write_bytes << ",\n"
           << "  \"axi_backend_stalls\": " << stats.backend_submit_stalls
           << ",\n"
           << "  \"backend_requests\": " << backend_->accepted() << ",\n"
           << "  \"backend_submit_stalls\": " << backend_->submit_stalls()
           << ",\n"
           << "  \"backend_response_queue_stalls\": "
           << backend_->response_queue_stalls() << ",\n"
           << "  \"backend_max_outstanding\": " << backend_->max_outstanding()
           << "\n"
           << "}\n";
    output_.output(
        "completed %llu online AXI requests in %llu core cycles -> %s\n",
        static_cast<unsigned long long>(sink_->completed()),
        static_cast<unsigned long long>(scheduler_.clock(0).completed_cycles),
        result_path_.c_str());
  }

  SST::Output output_;
  std::string result_path_;
  std::string mode_;
  std::string workload_path_;
  std::string update_workload_path_;
  std::string preload_path_;
  std::string hot_vertices_text_;
  std::uint32_t source_vertex_{};
  std::string core_clock_;
  double core_mhz_{};
  std::uint64_t request_count_{};
  std::uint64_t request_bytes_{};
  std::uint64_t stride_bytes_{};
  std::size_t channels_{};
  std::uint64_t channel_capacity_bytes_{};
  std::uint32_t write_percent_{};
  std::uint64_t max_cycles_{};
  std::size_t max_rounds_{};
  std::size_t pagerank_iterations_{};
  float pagerank_damping_{};
  float pagerank_epsilon_{};
  std::size_t residual_max_iterations_{};
  AlgorithmPipelineConfig pagerank_pipeline_config_;
  std::size_t device_dirty_source_limit_{};
  std::size_t range_task_active_gate_{};
  std::size_t range_task_capacity_{};
  std::uint64_t range_task_payload_budget_{};
  std::uint64_t fallback_replay_threshold_{};
  std::size_t memory_request_window_{};
  std::size_t compute_memory_request_window_{};
  std::size_t compute_writeonly_request_window_{};
  SpineOnChipMemoryProfile compute_on_chip_profile_;
  std::size_t reader_edge_pipeline_depth_{};
  std::size_t reader_edge_response_capacity_{};
  std::size_t maintenance_count_scan_ii_{};
  std::size_t maintenance_count_scan_tail_cycles_{};
  std::size_t maintenance_l0_write_scan_ii_{};
  std::size_t maintenance_l0_write_scan_tail_cycles_{};
  std::size_t maintenance_scan_response_capacity_{};
  std::string spine_axi_profile_id_;
  SpineAxiInterfaceProfile spine_axi_profile_;
  SST::TimeConverter clock_converter_{};
  std::vector<SST::Interfaces::StandardMem *> interfaces_;

  Scheduler scheduler_;
  std::unique_ptr<Fifo<AxiRequest>> requests_;
  std::unique_ptr<Fifo<AxiResponse>> responses_;
  std::unique_ptr<SstMemoryBackend> backend_;
  std::unique_ptr<AxiMaster> axi_;
  std::unique_ptr<ProbeSource> source_;
  std::unique_ptr<ProbeSink> sink_;
  std::unique_ptr<PayloadRoundTrip> payload_round_trip_;
  std::unique_ptr<SpineVerticalSliceSystem> spine_system_;
  std::unique_ptr<SpinePageRankVerticalSliceSystem> pagerank_system_;
  std::unique_ptr<Fifo<PartConvWord>> spine_edge_stream_;
  std::unique_ptr<Fifo<SourceValueWord>> spine_value_stream_;
  std::unique_ptr<SpineWordSource> spine_word_source_;
  std::unique_ptr<SpineSplitSsspCompute> spine_compute_;
  std::unique_ptr<FixedAxiPort> spine_vertex_state_;
  std::unique_ptr<FixedAxiPort> spine_active_out_;
  std::unique_ptr<FixedAxiPort> spine_active_bitmap_;
  std::unique_ptr<FixedAxiPort> spine_compute_result_;
  GraSuNativeConfig grasu_update_config_;
  GraSuReGraphConfig grasu_config_;
  GraSuPmaLayout grasu_layout_;
  std::unique_ptr<GraSuPmaUpdateSystem> grasu_update_system_;
  std::unique_ptr<GraSuReGraphSsspSystem> grasu_compute_system_;
  GraSuUpdateCounters grasu_update_counters_;
  SsspReference grasu_sssp_reference_;
  std::size_t grasu_initial_edges_{};
  std::size_t grasu_update_edges_{};
  bool grasu_update_counters_captured_{};
  SsspReference sssp_reference_;
  SsspReference cold_sssp_reference_;
  SsspReference dynamic_sssp_reference_;
  SpineEdgeSlice dynamic_update_workload_;
  SpineEdgeSlice dynamic_materialized_snapshot_;
  std::vector<std::uint32_t> dynamic_update_sources_;
  std::vector<std::uint32_t> cold_final_values_;
  std::vector<std::uint64_t> cold_round_cycles_;
  std::uint64_t cold_cycles_{};
  std::uint64_t dynamic_update_start_cycle_{};
  std::uint64_t cold_backend_requests_{};
  std::uint64_t cold_maintenance_cycles_{};
  std::uint64_t cold_value_mismatches_{};
  std::uint64_t cold_frontier_mismatches_{};
  std::size_t cold_rounds_{};
  std::int32_t cold_maintenance_target_level_{-1};
  std::uint32_t cold_dirty_generation_after_ack_{};
  std::vector<float> pagerank_reference_;
  ResidualPageRankReference residual_pagerank_reference_;
  std::vector<std::uint64_t> pagerank_iteration_cycles_;
  std::vector<std::size_t> pagerank_frontier_in_sizes_;
  std::vector<std::size_t> pagerank_frontier_out_sizes_;
  std::vector<std::uint64_t> pagerank_compute_requests_per_iteration_;
  std::uint64_t pagerank_iteration_start_cycle_{};
  std::size_t pagerank_completed_iterations_{};
  std::vector<SpineSsspRoundEvidence> sst_rounds_;
  std::vector<SpineHostHandoffEvidence> sst_host_handoffs_;
  std::vector<std::uint32_t> sst_current_frontier_;
  std::vector<std::uint32_t> sst_pending_active_out_;
  std::uint64_t sst_round_start_cycle_{};
  std::size_t spine_expected_edges_{};
  std::size_t spine_preload_edges_{};
  std::unordered_map<std::uint32_t, std::uint32_t> expected_distances_;
  bool sst_waiting_dirty_ack_{};
  bool dynamic_sssp_enabled_{};
  bool dynamic_sssp_started_{};
  bool dynamic_full_rebuild_{};
  bool result_written_{};
};

}  // namespace spine::sim::sst_adapter
