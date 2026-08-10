#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace spine::sim {

// Drives the same DRAMSim3 model used by SST memHierarchy while replacing
// StandardMem/MemEvent plumbing with an explicit, timestamped transport.
class DirectDramSim3Engine {
 public:
  struct Config {
    std::size_t channels{};
    std::vector<std::size_t> active_channels;
    std::string dram_config_path;
    std::string output_root;
    std::uint64_t ingress_link_ps{1'000};
    std::uint64_t egress_link_ps{1'000};
  };

  struct Completion {
    std::uint64_t token{};
    std::uint64_t visible_time_ps{};
  };

  explicit DirectDramSim3Engine(Config config);
  ~DirectDramSim3Engine();

  DirectDramSim3Engine(const DirectDramSim3Engine &) = delete;
  DirectDramSim3Engine &operator=(const DirectDramSim3Engine &) = delete;

  [[nodiscard]] bool channel_active(std::size_t channel) const noexcept;
  void submit(std::uint64_t token, std::size_t channel,
              std::uint64_t address, bool is_write,
              std::uint64_t submit_time_ps);
  void advance_to(std::uint64_t target_time_ps);
  void take_completions(std::vector<Completion> &output);
  void print_stats();

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace spine::sim
