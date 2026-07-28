#include "direct_dramsim3_engine.hpp"

#include <algorithm>
#include <deque>
#include <filesystem>
#include <limits>
#include <stdexcept>
#include <unordered_map>
#include <utility>

#ifdef SPINE_HAVE_DIRECT_DRAMSIM3
#include "dramsim3.h"
#endif

namespace spine::sim {

#ifdef SPINE_HAVE_DIRECT_DRAMSIM3
namespace {

constexpr std::uint64_t kPicosecondsPerNanosecond = 1'000;

}  // namespace

class DirectDramSim3Engine::Impl {
 public:
  explicit Impl(Config config)
      : config_(std::move(config)), channels_(config_.channels),
        work_active_(config_.channels, 0),
        egress_active_(config_.channels, 0) {
    if (config_.channels == 0 || config_.active_channels.empty() ||
        config_.dram_config_path.empty() || config_.output_root.empty() ||
        config_.ingress_link_ps == 0 || config_.egress_link_ps == 0) {
      throw std::invalid_argument("invalid direct DRAMSim3 configuration");
    }
    std::filesystem::create_directories(config_.output_root);
    for (const std::size_t channel : config_.active_channels) {
      if (channel >= channels_.size() || channels_[channel] != nullptr) {
        throw std::invalid_argument(
            "direct DRAMSim3 active channels must be unique and in range");
      }
      const std::filesystem::path output =
          std::filesystem::path(config_.output_root) /
          ("channel" + std::to_string(channel));
      std::filesystem::create_directories(output);
      auto state = std::make_unique<Channel>();
      Channel *raw = state.get();
      state->memory = std::make_unique<dramsim3::MemorySystem>(
          config_.dram_config_path, output.string(),
          [this, channel, raw](std::uint64_t address) {
            complete(channel, *raw, address);
          },
          [this, channel, raw](std::uint64_t address) {
            complete(channel, *raw, address);
          });
      const double tck = state->memory->GetTCK();
      if (!(tck > 0.0) ||
          std::abs(tck * static_cast<double>(kPicosecondsPerNanosecond) -
                   static_cast<double>(kPicosecondsPerNanosecond)) > 1.0e-6) {
        throw std::invalid_argument(
            "direct DRAMSim3 currently requires a 1 ns memory clock");
      }
      channels_[channel] = std::move(state);
    }
  }

  [[nodiscard]] bool channel_active(std::size_t channel) const noexcept {
    return channel < channels_.size() && channels_[channel] != nullptr;
  }

  void submit(std::uint64_t token, std::size_t channel,
              std::uint64_t address, bool is_write,
              std::uint64_t submit_time_ps) {
    if (!channel_active(channel)) {
      throw std::invalid_argument(
          "direct DRAMSim3 request targets an inactive channel");
    }
    if (submit_time_ps >
        std::numeric_limits<std::uint64_t>::max() - config_.ingress_link_ps) {
      throw std::overflow_error("direct DRAMSim3 ingress timestamp overflow");
    }
    Channel &state = *channels_[channel];
    const std::uint64_t arrival_ps = submit_time_ps + config_.ingress_link_ps;
    // The StandardMem link delivers after 1 ns, then reregisterClock() starts
    // the MemController on the following 1 GHz edge. In particular, an event
    // exactly on an edge does not issue through the backend on that edge.
    const std::uint64_t issue_tick =
        arrival_ps / kPicosecondsPerNanosecond + 1;
    if (!state.ingress.empty() &&
        issue_tick < state.ingress.back().issue_tick) {
      throw std::logic_error(
          "direct DRAMSim3 submissions must be timestamp ordered");
    }
    state.ingress.push_back(Pending{
        .token = token,
        .address = address,
        .is_write = is_write,
        .issue_tick = issue_tick,
    });
    activate(channel, work_active_, work_channels_);
  }

  void advance_to(std::uint64_t target_time_ps) {
    if (target_time_ps < current_time_ps_) {
      throw std::invalid_argument(
          "direct DRAMSim3 cannot move backwards in simulated time");
    }
    const std::uint64_t target_tick =
        target_time_ps / kPicosecondsPerNanosecond;
    for (std::size_t index = 0; index < work_channels_.size();) {
      const std::size_t channel = work_channels_[index];
      Channel &state = *channels_[channel];
      advance_channel(channel, state, target_tick);
      if (state.ingress.empty() && state.issued.empty() &&
          state.memory->IsIdle()) {
        work_active_[channel] = 0;
        work_channels_[index] = work_channels_.back();
        work_channels_.pop_back();
      } else {
        ++index;
      }
    }
    current_time_ps_ = target_time_ps;
  }

  void take_completions(std::vector<Completion> &visible) {
    visible.clear();
    for (std::size_t index = 0; index < egress_channels_.size();) {
      const std::size_t channel = egress_channels_[index];
      Channel &state = *channels_[channel];
      // SST clocks (priority 40) run before link events (priority 50) at an
      // equal timestamp. A response landing exactly on a core edge therefore
      // becomes visible to the following core tick, not the current one.
      while (!state.egress.empty() &&
             state.egress.front().visible_time_ps < current_time_ps_) {
        visible.push_back(state.egress.front());
        state.egress.pop_front();
      }
      if (state.egress.empty()) {
        egress_active_[channel] = 0;
        egress_channels_[index] = egress_channels_.back();
        egress_channels_.pop_back();
      } else {
        ++index;
      }
    }
    std::sort(visible.begin(), visible.end(),
              [](const Completion &left, const Completion &right) {
                if (left.visible_time_ps != right.visible_time_ps) {
                  return left.visible_time_ps < right.visible_time_ps;
                }
                return left.token < right.token;
              });
  }

  void print_stats() {
    if (stats_printed_) {
      return;
    }
    const std::uint64_t target_tick =
        current_time_ps_ / kPicosecondsPerNanosecond;
    for (const std::size_t channel : config_.active_channels) {
      advance_channel(channel, *channels_[channel], target_tick);
      channels_[channel]->memory->PrintStats();
    }
    stats_printed_ = true;
  }

 private:
  struct Pending {
    std::uint64_t token{};
    std::uint64_t address{};
    bool is_write{};
    std::uint64_t issue_tick{};
  };

  struct Channel {
    std::unique_ptr<dramsim3::MemorySystem> memory;
    std::deque<Pending> ingress;
    std::unordered_map<std::uint64_t, std::deque<std::uint64_t>> issued;
    std::deque<Completion> egress;
    std::uint64_t clock_tick{};
  };

  void advance_channel(std::size_t channel, Channel &state,
                       std::uint64_t target_tick) {
    while (state.clock_tick < target_tick) {
      const bool no_ready_request =
          state.ingress.empty() ||
          state.ingress.front().issue_tick > state.clock_tick + 1;
      if (no_ready_request && state.issued.empty() && state.memory->IsIdle()) {
        const std::uint64_t next_required_tick =
            state.ingress.empty() ? target_tick
                                  : std::min(target_tick,
                                             state.ingress.front().issue_tick - 1);
        if (next_required_tick > state.clock_tick) {
          const std::uint64_t idle_ticks =
              next_required_tick - state.clock_tick;
          state.memory->AdvanceIdle(idle_ticks);
          state.clock_tick = next_required_tick;
          continue;
        }
      }

      ++state.clock_tick;
      while (!state.ingress.empty() &&
             state.ingress.front().issue_tick <= state.clock_tick) {
        const Pending &pending = state.ingress.front();
        if (!state.memory->WillAcceptTransaction(pending.address,
                                                  pending.is_write)) {
          break;
        }
        if (!state.memory->AddTransaction(pending.address,
                                          pending.is_write)) {
          throw std::logic_error(
              "DRAMSim3 rejected a transaction after accepting it");
        }
        state.issued[pending.address].push_back(pending.token);
        state.ingress.pop_front();
      }
      current_callback_tick_ = state.clock_tick;
      current_callback_channel_ = channel;
      state.memory->ClockTick();
    }
  }

  void complete(std::size_t channel, Channel &state, std::uint64_t address) {
    if (channel != current_callback_channel_) {
      throw std::logic_error("direct DRAMSim3 callback channel mismatch");
    }
    const auto found = state.issued.find(address);
    if (found == state.issued.end() || found->second.empty()) {
      throw std::logic_error("direct DRAMSim3 returned an unknown address");
    }
    const std::uint64_t token = found->second.front();
    found->second.pop_front();
    if (found->second.empty()) {
      state.issued.erase(found);
    }
    const std::uint64_t completion_ps =
        current_callback_tick_ * kPicosecondsPerNanosecond;
    if (completion_ps >
        std::numeric_limits<std::uint64_t>::max() - config_.egress_link_ps) {
      throw std::overflow_error("direct DRAMSim3 egress timestamp overflow");
    }
    const bool was_empty = state.egress.empty();
    state.egress.push_back(Completion{
        .token = token,
        .visible_time_ps = completion_ps + config_.egress_link_ps,
    });
    if (was_empty) {
      activate(channel, egress_active_, egress_channels_);
    }
  }

  static void activate(std::size_t channel, std::vector<std::uint8_t> &active,
                       std::vector<std::size_t> &channels) {
    if (active[channel] == 0) {
      active[channel] = 1;
      channels.push_back(channel);
    }
  }

  Config config_;
  std::vector<std::unique_ptr<Channel>> channels_;
  std::vector<std::uint8_t> work_active_;
  std::vector<std::size_t> work_channels_;
  std::vector<std::uint8_t> egress_active_;
  std::vector<std::size_t> egress_channels_;
  std::uint64_t current_time_ps_{};
  std::uint64_t current_callback_tick_{};
  std::size_t current_callback_channel_{};
  bool stats_printed_{};
};

#else

class DirectDramSim3Engine::Impl {
 public:
  explicit Impl(Config) {
    throw std::runtime_error(
        "direct DRAMSim3 support was not enabled when the SST element was built");
  }
};

#endif

DirectDramSim3Engine::DirectDramSim3Engine(Config config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

DirectDramSim3Engine::~DirectDramSim3Engine() = default;

bool DirectDramSim3Engine::channel_active(std::size_t channel) const noexcept {
#ifdef SPINE_HAVE_DIRECT_DRAMSIM3
  return impl_->channel_active(channel);
#else
  (void)channel;
  return false;
#endif
}

void DirectDramSim3Engine::submit(std::uint64_t token, std::size_t channel,
                                  std::uint64_t address, bool is_write,
                                  std::uint64_t submit_time_ps) {
#ifdef SPINE_HAVE_DIRECT_DRAMSIM3
  impl_->submit(token, channel, address, is_write, submit_time_ps);
#else
  (void)token;
  (void)channel;
  (void)address;
  (void)is_write;
  (void)submit_time_ps;
  throw std::runtime_error("direct DRAMSim3 support is unavailable");
#endif
}

void DirectDramSim3Engine::advance_to(std::uint64_t target_time_ps) {
#ifdef SPINE_HAVE_DIRECT_DRAMSIM3
  impl_->advance_to(target_time_ps);
#else
  (void)target_time_ps;
  throw std::runtime_error("direct DRAMSim3 support is unavailable");
#endif
}

void DirectDramSim3Engine::take_completions(
    std::vector<Completion> &output) {
#ifdef SPINE_HAVE_DIRECT_DRAMSIM3
  impl_->take_completions(output);
#else
  (void)output;
  throw std::runtime_error("direct DRAMSim3 support is unavailable");
#endif
}

void DirectDramSim3Engine::print_stats() {
#ifdef SPINE_HAVE_DIRECT_DRAMSIM3
  impl_->print_stats();
#else
  throw std::runtime_error("direct DRAMSim3 support is unavailable");
#endif
}

}  // namespace spine::sim
