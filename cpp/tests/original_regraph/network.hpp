#pragma once

#include <algorithm>
#include <memory>
#include <stdexcept>
#include <sstream>
#include <string>
#include <vector>

#include "spine_sim/original_regraph/little_merge.hpp"
#include "spine_sim/scheduler.hpp"

namespace original_regraph_test {

namespace rg = spine::sim::original_regraph;
using spine::sim::Component;
using spine::sim::Fifo;
inline constexpr unsigned kClockMHz = 210;
inline constexpr std::size_t kDefaultFifoDepth = 8;

inline std::string configuration_record() {
  const rg::LittleTiming timing;
  std::ostringstream out;
  out << "MODEL_CONFIG {\"clock_mhz\":" << kClockMHz
      << ",\"partition_vertices\":" << rg::kLittleVertices
      << ",\"gather_lanes\":" << rg::kGatherLanes
      << ",\"default_fifo_depth\":" << kDefaultFifoDepth
      << ",\"uram_write_latency\":" << rg::kUramWriteLatency
      << ",\"forwarding_entries_per_lane\":" << rg::kForwardingEntries
      << ",\"timing\":{";
  const std::array<std::pair<const char*, rg::PipelineTiming>, 4> stages{{
      {"gather", timing.gather}, {"drain", timing.drain},
      {"local_merge", timing.local_merge}, {"global_merge", timing.global_merge}}};
  for (std::size_t index = 0; index < stages.size(); ++index) {
    const auto& [name, value] = stages[index];
    if (index) out << ',';
    out << '"' << name << "\":{\"latency\":" << value.latency
        << ",\"initiation_interval\":" << value.initiation_interval
        << ",\"capacity\":" << value.capacity << '}';
  }
  return out.str() + "}}";
}

inline void require(bool value, const std::string& message) {
  if (!value) throw std::runtime_error(message);
}

struct Options {
  std::uint64_t source_interval{1};
  std::uint64_t pipeline_start_skew{};
  std::uint64_t sink_interval{1};
  std::uint64_t sink_start{};
  std::uint64_t max_cycles{1000000};
};

struct Observation {
  std::vector<std::uint32_t> values;
  std::uint64_t cycles{};
  std::uint64_t output_stalls{};
  std::uint64_t capacity_stalls{};
};

class Network {
 public:
  Network(std::size_t little, std::size_t fifo_depth = kDefaultFifoDepth,
          rg::LittleTiming timing = {}, bool reverse_registration = false)
      : clock_(scheduler_.add_clock_mhz("original_little", kClockMHz)) {
    std::vector<Fifo<rg::VertexPair>*> local_outputs;
    for (std::size_t pipeline = 0; pipeline < little; ++pipeline) {
      const auto prefix = "little" + std::to_string(pipeline);
      Path path;
      path.input = make<Fifo<rg::UpdateBurst>>(prefix + ".updates", clock_, fifo_depth);
      for (std::size_t lane = 0; lane < rg::kGatherLanes; ++lane) {
        path.rows[lane] = make<Fifo<rg::VertexPair>>(
            prefix + ".lane" + std::to_string(lane), clock_, fifo_depth);
      }
      path.local = make<Fifo<rg::VertexPair>>(prefix + ".local", clock_, fifo_depth);
      path.gather = make<rg::LittleGather>(prefix + ".gather", clock_,
                                          *path.input, path.rows, timing);
      path.merge = make<rg::LittleLocalMerge>(prefix + ".merge", clock_,
                                             path.rows, *path.local, timing.local_merge);
      local_outputs.push_back(path.local);
      paths_.push_back(path);
    }
    output_ = make<Fifo<rg::PropertyLine>>("merged", clock_, fifo_depth);
    merger_ = make<rg::LittleGlobalMerge>("global_merge", clock_, local_outputs,
                                         *output_, timing.global_merge);
    if (reverse_registration) {
      for (auto iterator = owned_.rbegin(); iterator != owned_.rend(); ++iterator) {
        scheduler_.add_component(**iterator);
      }
    } else {
      for (const auto& component : owned_) scheduler_.add_component(*component);
    }
  }

  Observation run(const std::vector<std::vector<rg::UpdateBurst>>& bursts,
                  Options options = {}) {
    require(bursts.size() == paths_.size() && options.source_interval &&
            options.sink_interval && options.max_cycles, "invalid fixture shape/options");
    std::vector<std::size_t> sent(paths_.size(), 0);
    std::vector<std::uint64_t> before_bursts;
    std::vector<std::uint64_t> before_drain;
    const auto stalls_before = stall_totals();
    for (std::size_t pipeline = 0; pipeline < paths_.size(); ++pipeline) {
      auto& path = paths_[pipeline];
      path.input->reset_stats();
      path.local->reset_stats();
      for (auto* row : path.rows) row->reset_stats();
      before_bursts.push_back(path.gather->counters().bursts);
      before_drain.push_back(path.gather->counters().drain_read_pairs);
      path.gather->begin_partition(bursts[pipeline].size());
    }
    output_->reset_stats();
    Observation observed;
    const auto start = scheduler_.clock(clock_).completed_cycles;
    for (std::uint64_t cycle = 0; cycle < options.max_cycles; ++cycle) {
      for (std::size_t pipeline = 0; pipeline < paths_.size(); ++pipeline) {
        auto* queue = paths_[pipeline].input;
        if (sent[pipeline] < bursts[pipeline].size() && !queue->full() &&
            cycle >= pipeline * options.pipeline_start_skew &&
            cycle % options.source_interval == 0) {
          require(queue->try_push(bursts[pipeline][sent[pipeline]++]),
                  "fixture producer lost exclusive FIFO ownership");
        }
      }
      if (cycle >= options.sink_start && cycle % options.sink_interval == 0 &&
          !output_->empty()) {
        rg::PropertyLine line;
        require(output_->try_pop(line), "fixture consumer lost FIFO ownership");
        observed.values.insert(observed.values.end(), line.begin(), line.end());
        require(observed.values.size() <= rg::kLittleVertices, "excess output");
      }
      scheduler_.step();
      if (observed.values.size() == rg::kLittleVertices && drained()) {
        observed.cycles = scheduler_.clock(clock_).completed_cycles - start;
        const auto stalls_after = stall_totals();
        observed.output_stalls = stalls_after.first - stalls_before.first;
        observed.capacity_stalls = stalls_after.second - stalls_before.second;
        for (std::size_t pipeline = 0; pipeline < paths_.size(); ++pipeline) {
          const auto& path = paths_[pipeline];
          require(sent[pipeline] == bursts[pipeline].size(), "unsubmitted updates");
          require(path.gather->counters().bursts - before_bursts[pipeline] ==
                  bursts[pipeline].size(), "gather input count mismatch");
          require(path.gather->counters().drain_read_pairs - before_drain[pipeline] ==
                  rg::kLittleRows * rg::kGatherLanes, "incomplete URAM drain");
          conserved(*path.input, bursts[pipeline].size());
          for (const auto* row : path.rows) conserved(*row, rg::kLittleRows);
          conserved(*path.local, rg::kLittleRows);
        }
        conserved(*output_, rg::kLittleVertices / 16);
        return observed;
      }
    }
    throw std::runtime_error("finite Little network exceeded bounded cycle budget");
  }

  const rg::LittleGather& gather(std::size_t index) const { return *paths_.at(index).gather; }

 private:
  struct Path {
    Fifo<rg::UpdateBurst>* input{};
    rg::GatherOutputs rows{};
    Fifo<rg::VertexPair>* local{};
    rg::LittleGather* gather{};
    rg::LittleLocalMerge* merge{};
  };

  template <typename T, typename... Args>
  T* make(Args&&... args) {
    auto component = std::make_unique<T>(std::forward<Args>(args)...);
    auto* pointer = component.get();
    owned_.push_back(std::move(component));
    return pointer;
  }

  template <typename T>
  static void conserved(const Fifo<T>& queue, std::uint64_t expected) {
    require(queue.empty() && queue.stats().pushes == expected &&
            queue.stats().pops == expected && queue.stats().max_occupancy <= queue.depth(),
            queue.name() + " violates FIFO conservation");
  }

  bool drained() const {
    return output_->empty() && merger_->drained() &&
           std::all_of(paths_.begin(), paths_.end(), [](const auto& path) {
             return path.input->empty() && path.gather->finished() && path.merge->drained() &&
                    path.local->empty() && std::all_of(path.rows.begin(), path.rows.end(),
                    [](const auto* queue) { return queue->empty(); });
           });
  }

  std::pair<std::uint64_t, std::uint64_t> stall_totals() const {
    std::pair<std::uint64_t, std::uint64_t> result{
        merger_->counters().output_stalls, merger_->counters().capacity_stalls};
    for (const auto& path : paths_) {
      result.first += path.merge->counters().output_stalls +
                      path.gather->drain_pipeline().output_stalls;
      result.second += path.merge->counters().capacity_stalls +
                       path.gather->drain_pipeline().capacity_stalls +
                       path.gather->gather_pipeline().capacity_stalls;
    }
    return result;
  }

  spine::sim::Scheduler scheduler_;
  spine::sim::ClockId clock_;
  std::vector<std::unique_ptr<Component>> owned_;
  std::vector<Path> paths_;
  Fifo<rg::PropertyLine>* output_{};
  rg::LittleGlobalMerge* merger_{};
};

inline std::vector<std::uint32_t> oracle(
    const std::vector<std::vector<rg::UpdateBurst>>& pipelines) {
  std::vector<std::uint32_t> values(rg::kLittleVertices, 0);
  for (const auto& pipeline : pipelines) {
    for (const auto& burst : pipeline) {
      for (const auto update : burst) {
        if (!(update.destination & rg::kDummyDestination)) {
          values[update.destination & (rg::kLittleVertices - 1)] += update.value;
        }
      }
    }
  }
  return values;
}

inline std::vector<std::vector<rg::UpdateBurst>> stress_fixture(
    std::size_t pipelines, std::size_t bursts) {
  std::vector<std::vector<rg::UpdateBurst>> values(pipelines);
  for (std::size_t pipeline = 0; pipeline < pipelines; ++pipeline) {
    for (std::size_t index = 0; index < bursts; ++index) {
      rg::UpdateBurst burst;
      for (std::size_t lane = 0; lane < rg::kGatherLanes; ++lane) {
        const auto destination = static_cast<std::uint32_t>(
            index % 7 == 0 ? rg::kDummyDestination :
            index % 3 == 0 ? rg::kLittleVertices - 1 :
            index % 23 < 10 ? index % 2 : (index * 13 + lane) % 31);
        burst[lane] = {destination, static_cast<std::uint32_t>(1 + (pipeline + index + lane) % 97)};
      }
      values[pipeline].push_back(burst);
    }
  }
  return values;
}

}  // namespace original_regraph_test
