// clang-format off
#include "sst/core/sst_config.h"
// clang-format on
#include "integrated.hpp"
#include "spine.hpp"
#include "sssp.hpp"
#include "../dram_clock.hpp"
#include "sst/core/component.h"
#include "sst/core/params.h"
#include <numeric>

namespace figure_refresh::multi {
class Refresh final : public SST::Component {
 public:
  Refresh(SST::ComponentId_t id, SST::Params& params) : SST::Component(id), params_(params) {
    registerAsPrimaryComponent(); primaryComponentDoNotEndSim();
  }
  void setup() override {
    try {
      const auto arm = params_.find<std::string>("arm", "");
      require(arm == "spine" || arm == "gr", "invalid multialgorithm arm");
      const auto algorithm = params_.find<std::string>("algorithm", "");
      require(algorithm == "SSSP" || algorithm == "CC" || algorithm == "ResPR", "invalid algorithm");
      const auto output = params_.find<std::string>("output", "");
      Scheduler scheduler;
      const auto clock = scheduler.add_clock_mhz("core", 150);
      std::vector<std::size_t> channels(32); std::iota(channels.begin(), channels.end(), 0);
      auto engine = std::make_unique<DirectDramSim3Engine>(DirectDramSim3Engine::Config{
          .channels = 32, .active_channels = channels,
          .dram_config_path = params_.find<std::string>("dram_config", ""), .output_root = output + "/dram"});
      spine::sim::sst_adapter::SstMemoryBackend backend(clock,
          std::vector<SST::Interfaces::StandardMem*>(32, nullptr), 512ULL << 20, 1, 32, 128,
          "identity", "", 0, 0, 64, std::move(engine));
      DramClock pump(clock, backend); scheduler.add_component(pump);
      const auto maximum = params_.find<std::uint64_t>("maximum", 150000000);
      const auto graph = params_.find<std::string>("graph", "");
      const auto updates = params_.find<std::string>("updates", "");
      if (algorithm == "SSSP") {
        sssp(graph, updates, params_.find<std::uint32_t>("root", 0), output, arm,
             scheduler, clock, backend, maximum);
      } else {
        const auto input = load(graph, updates, algorithm);
        wc::ei::wt::write_words(std::filesystem::path(output) / "old_state.u32le", input.graph.after.initial.primary);
        std::vector<std::uint32_t> expected = input.expected_labels;
        if (input.algorithm.kind == GraphAlgorithmKind::kResidualPageRank)
          for (double value : input.expected_rank) expected.push_back(GraphAlgorithmPolicy::float_to_word(value));
        wc::ei::wt::write_words(std::filesystem::path(output) / "expected.u32le", expected);
        if (arm == "gr") integrated(input, output, scheduler, clock, backend, maximum);
        else spine(input, output, scheduler, clock, backend, maximum);
      }
      backend.print_direct_stats();
      std::ofstream summary(output + "/backend.json"); summary << backend.arbitration_json();
      std::cout << "REFRESH_COMPLETE" << std::endl;
    } catch (const std::exception& error) {
      std::cerr << "REFRESH_FAILED " << error.what() << std::endl;
      throw;
    }
    primaryComponentOKToEndSim();
  }
  SST_ELI_REGISTER_COMPONENT(Refresh, "figure_multi", "Refresh", SST_ELI_ELEMENT_VERSION(1, 0, 0),
      "Three-algorithm figure data, simulator prediction only", COMPONENT_CATEGORY_MEMORY)
  SST_ELI_DOCUMENT_PARAMS({"arm", "gr or spine", ""}, {"algorithm", "SSSP, CC or ResPR", ""},
      {"graph", "Materialized old graph", ""}, {"updates", "Materialized insertion batch", ""},
      {"root", "SSSP source vertex", "0"},
      {"output", "Fresh output directory", ""}, {"dram_config", "DRAMSim3 configuration", ""},
      {"maximum", "Finite cycle budget", "150000000"})
 private:
  SST::Params params_;
};
} // namespace figure_refresh::multi
