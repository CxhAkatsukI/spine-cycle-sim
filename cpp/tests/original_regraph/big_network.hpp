#pragma once

#include "network.hpp"
#include "spine_sim/original_regraph/big_merge.hpp"

namespace original_regraph_test {

class BigNetwork {
 public:
  BigNetwork(std::size_t big, bool reverse = false, std::size_t depth_override = 0,
             rg::BigTiming timing = {})
      : clock_(scheduler_.add_clock_mhz("original_big", kClockMHz)) {
    require(big && big <= 14, "invalid Big path count");
    const auto depth = [depth_override](std::size_t source_depth) {
      return depth_override ? depth_override : source_depth;
    };
    std::vector<Fifo<rg::PropertyLine>*> partials;
    for (std::size_t path_index = 0; path_index < big; ++path_index) {
      const auto name = "big" + std::to_string(path_index);
      Path path;
      path.input = make<Fifo<rg::UpdateBurst>>(name + ".input", clock_, depth(16));
      for (unsigned stage = 0; stage < 4; ++stage) {
        for (unsigned lane = 0; lane < 8; ++lane) {
          path.layers[stage][lane] = make<Fifo<rg::RoutedUpdate>>(
              name + ".stage" + std::to_string(stage) + ".lane" + std::to_string(lane), clock_,
              depth(stage ? 2 : 16));
        }
      }
      path.dispatch = make<rg::BigDispatch>(name + ".dispatch", clock_, *path.input, path.layers[0]);
      for (unsigned stage = 0; stage < 3; ++stage) {
        for (unsigned pair = 0; pair < 4; ++pair) {
          path.switches.push_back(make<rg::BigOmegaSwitch>(name + ".switch" + std::to_string(stage * 4 + pair),
              clock_, 2 - stage,
              std::array{path.layers[stage][pair], path.layers[stage][pair + 4]},
              std::array{path.layers[stage + 1][pair * 2], path.layers[stage + 1][pair * 2 + 1]}, depth(2)));
        }
      }
      for (unsigned bank = 0; bank < 8; ++bank) {
        path.rows[bank] = make<Fifo<rg::VertexPair>>(name + ".row" + std::to_string(bank), clock_, depth(4));
        path.banks[bank] = make<rg::BigGatherBank>(name + ".bank" + std::to_string(bank),
            clock_, bank, *path.layers[3][bank], *path.rows[bank], timing);
      }
      path.packed = make<Fifo<rg::PropertyLine>>(name + ".packed", clock_, depth(8));
      path.packer = make<rg::BigResultPacker>(name + ".packer", clock_, path.rows, *path.packed, timing.pack);
      partials.push_back(path.packed);
      paths_.push_back(path);
    }
    output_ = make<Fifo<rg::PropertyLine>>("big.merged", clock_, depth(8));
    merger_ = make<rg::BigGlobalMerge>("big.merge", clock_, partials, *output_, timing.merge);
    if (reverse) {
      for (auto it = owned_.rbegin(); it != owned_.rend(); ++it) scheduler_.add_component(**it);
    } else {
      for (const auto& component : owned_) scheduler_.add_component(*component);
    }
  }

  Observation run(const std::vector<std::vector<rg::UpdateBurst>>& bursts, Options options = {}) {
    require(bursts.size() == paths_.size() && options.source_interval && options.sink_interval, "invalid Big fixture");
    std::vector<std::size_t> sent(paths_.size());
    const auto before = counters();
    for (std::size_t index = 0; index < paths_.size(); ++index) {
      auto& path = paths_[index];
      path.dispatch->begin_partition(bursts[index].size());
      for (auto* sw : path.switches) sw->begin_partition();
      for (auto* bank : path.banks) bank->begin_partition();
      path.packer->begin_partition();
    }
    merger_->begin_partition();
    Observation result;
    for (std::uint64_t cycle = 0; cycle < options.max_cycles; ++cycle) {
      for (std::size_t index = 0; index < paths_.size(); ++index) {
        if (sent[index] < bursts[index].size() && cycle >= index * options.pipeline_start_skew &&
            cycle % options.source_interval == 0 && !paths_[index].input->full()) {
          require(paths_[index].input->try_push(bursts[index][sent[index]++]), "Big source ownership");
        }
      }
      if (cycle >= options.sink_start && cycle % options.sink_interval == 0 && !output_->empty()) {
        rg::PropertyLine line;
        require(output_->try_pop(line), "Big sink ownership");
        result.values.insert(result.values.end(), line.begin(), line.end());
        require(result.values.size() <= rg::kBigVertices, "Big excess output");
      }
      scheduler_.step();
      if (result.values.size() == rg::kBigVertices && drained()) {
        for (std::size_t index = 0; index < paths_.size(); ++index) {
          require(sent[index] == bursts[index].size(), "Big unsubmitted updates");
        }
        verify_queues();
        const auto after = counters();
        result.cycles = cycle + 1;
        result.output_stalls = after.first - before.first;
        result.capacity_stalls = after.second - before.second;
        return result;
      }
    }
    throw std::runtime_error("finite Big network exceeded cycle budget");
  }

  std::vector<std::vector<rg::BigBankCounters>> banks() const {
    std::vector<std::vector<rg::BigBankCounters>> result;
    for (const auto& path : paths_) {
      result.emplace_back();
      for (const auto* bank : path.banks) result.back().push_back(bank->counters());
    }
    return result;
  }

 private:
  struct Path {
    Fifo<rg::UpdateBurst>* input{};
    std::array<rg::RoutedPorts, 4> layers{};
    rg::BigDispatch* dispatch{};
    std::vector<rg::BigOmegaSwitch*> switches;
    std::array<Fifo<rg::VertexPair>*, 8> rows{};
    std::array<rg::BigGatherBank*, 8> banks{};
    Fifo<rg::PropertyLine>* packed{};
    rg::BigResultPacker* packer{};
  };
  template <typename T, typename... Args>
  T* make(Args&&... args) {
    auto value = std::make_unique<T>(std::forward<Args>(args)...);
    auto* pointer = value.get();
    owned_.push_back(std::move(value));
    return pointer;
  }
  bool drained() const {
    if (!merger_->finished() || !output_->empty()) return false;
    for (const auto& path : paths_) {
      if (!path.dispatch->finished() || !path.packer->finished() || !path.input->empty() || !path.packed->empty()) return false;
      for (const auto* sw : path.switches) if (!sw->drained()) return false;
      for (const auto* bank : path.banks) if (!bank->finished()) return false;
      for (const auto& layer : path.layers) for (const auto* q : layer) if (!q->empty()) return false;
      for (const auto* q : path.rows) if (!q->empty()) return false;
    }
    return true;
  }
  template <typename T>
  static void conserved(const Fifo<T>& queue) {
    require(queue.empty() && queue.stats().pushes == queue.stats().pops &&
            queue.stats().max_occupancy <= queue.depth(), "Big FIFO conservation or capacity");
  }
  void verify_queues() const {
    conserved(*output_);
    for (const auto& path : paths_) {
      conserved(*path.input); conserved(*path.packed);
      for (const auto& layer : path.layers) for (const auto* q : layer) conserved(*q);
      for (const auto* q : path.rows) conserved(*q);
      for (const auto* sw : path.switches) {
        const auto& c = sw->counters();
        require(c.sender_tuples == c.receiver_tuples && c.sender_ends * 2 == c.receiver_ends,
                "Big switch data/end conservation");
        for (unsigned index = 0; index < 4; ++index) conserved(sw->route(index));
      }
    }
  }
  std::pair<std::uint64_t, std::uint64_t> counters() const {
    std::uint64_t output_stalls = merger_->counters().output_stalls;
    std::uint64_t capacity_stalls = merger_->counters().capacity_stalls;
    for (const auto& path : paths_) {
      output_stalls += path.dispatch->output_stalls() + path.packer->counters().output_stalls;
      capacity_stalls += path.packer->counters().capacity_stalls;
      for (const auto* sw : path.switches) output_stalls += sw->counters().sender_stalls + sw->counters().receiver_stalls;
      for (const auto* bank : path.banks) {
        output_stalls += bank->drain_pipeline().output_stalls;
        capacity_stalls += bank->gather_pipeline().capacity_stalls + bank->drain_pipeline().capacity_stalls;
      }
    }
    return {output_stalls, capacity_stalls};
  }
  spine::sim::Scheduler scheduler_;
  spine::sim::ClockId clock_;
  std::vector<std::unique_ptr<Component>> owned_;
  std::vector<Path> paths_;
  Fifo<rg::PropertyLine>* output_{};
  rg::BigGlobalMerge* merger_{};
};

inline std::vector<std::vector<rg::UpdateBurst>> big_fixture(unsigned case_id, std::size_t paths = 3) {
  const unsigned bursts = case_id == 1 ? 0 : (case_id == 2 ? 1000 : 257);
  std::vector<std::vector<rg::UpdateBurst>> result(paths, std::vector<rg::UpdateBurst>(bursts));
  for (std::size_t path = 0; path < paths; ++path) {
    for (unsigned burst = 0; burst < bursts; ++burst) {
      for (unsigned lane = 0; lane < 8; ++lane) {
        const unsigned index = burst * 8 + lane;
        auto destination = case_id == 2 ? (index % 2 ? 8u : 0u)
            : static_cast<unsigned>((index * 7919ull + path * 17) % rg::kBigVertices);
        if (case_id != 2 && index % 29 == 0) destination = rg::kBigVertices - 1;
        if (index % 31 == 0) destination = rg::kDummyDestination | (index & 7u);
        result[path][burst][lane] = {destination, index % 17 ? static_cast<unsigned>(17 + (index + path) % 31) : 0};
      }
    }
  }
  return result;
}

inline std::vector<std::uint32_t> big_oracle(const std::vector<std::vector<rg::UpdateBurst>>& inputs) {
  std::vector<std::uint32_t> result(rg::kBigVertices);
  for (const auto& path : inputs) for (const auto& burst : path) for (const auto update : burst) {
    if (!(update.destination & rg::kDummyDestination)) result.at(update.destination) += update.value;
  }
  return result;
}

}  // namespace original_regraph_test
