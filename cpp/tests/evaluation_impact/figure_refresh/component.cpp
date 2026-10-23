// clang-format off
#include "sst/core/sst_config.h"
// clang-format on
#include "host.hpp"
#include "update.hpp"
#include "dram_clock.hpp"
#include "../warm_comparison/integrated.hpp"
#include "../warm_comparison/spine.hpp"
#include "../../../sst/sst_memory_backend.hpp"
#include "sst/core/component.h"
#include "sst/core/params.h"
#include <numeric>

namespace figure_refresh {
class Refresh final : public SST::Component {
 public:
  Refresh(SST::ComponentId_t id, SST::Params& params) : SST::Component(id), params_(params) {
    registerAsPrimaryComponent(); primaryComponentDoNotEndSim();
  }
  void setup() override {
    try {
      const auto mode = params_.find<std::string>("mode", "");
      const auto arm = params_.find<std::string>("arm", "");
      require((mode == "update" || mode == "propagation" || mode == "host") &&
          (arm == "spine" || arm == "gr"), "invalid refresh mode or arm");
      const auto input = load(params_.find<std::string>("graph", ""),
          params_.find<std::string>("updates", ""), params_.find<std::uint32_t>("root", 0), mode == "propagation");
      const auto output = params_.find<std::string>("output", "");
      if (mode == "host") host(input, arm);
      else {
        Scheduler scheduler;
        const auto clock = scheduler.add_clock_mhz("core", 150);
        std::vector<std::size_t> channels(32); std::iota(channels.begin(), channels.end(), 0);
        auto engine = std::make_unique<DirectDramSim3Engine>(DirectDramSim3Engine::Config{
            .channels = 32, .active_channels = channels,
            .dram_config_path = params_.find<std::string>("dram_config", ""),
            .output_root = output + "/dram"});
        spine::sim::sst_adapter::SstMemoryBackend backend(clock,
            std::vector<SST::Interfaces::StandardMem*>(32, nullptr), 512ULL << 20, 1, 32, 128,
            "identity", "", 0, 0, 64, std::move(engine));
        DramClock pump(clock, backend);
        scheduler.add_component(pump);
        const auto maximum = params_.find<std::uint64_t>("maximum", 150000000);
        if (arm == "gr") wc::integrated_with_backend(input, output, scheduler, clock, backend, false,
                                                     maximum, mode == "update");
        else if (mode == "update") update_spine(input, scheduler, clock, backend, maximum);
        else wc::spine_with_backend(input, output, scheduler, clock, backend, maximum);
        backend.print_direct_stats();
        std::ofstream summary(output + "/backend.json");
        summary << backend.arbitration_json();
      }
      std::cout << "REFRESH_COMPLETE" << std::endl;
    } catch (const std::exception& error) {
      std::cerr << "REFRESH_FAILED " << error.what() << std::endl;
      throw;
    }
    primaryComponentOKToEndSim();
  }
  SST_ELI_REGISTER_COMPONENT(Refresh, "figure_refresh", "Refresh", SST_ELI_ELEMENT_VERSION(1, 0, 0),
      "Pinned simulator-only comparison data refresh", COMPONENT_CATEGORY_MEMORY)
  SST_ELI_DOCUMENT_PARAMS({"mode", "update, propagation or host", ""}, {"arm", "gr or spine", ""},
      {"graph", "Materialized graph", ""}, {"updates", "Materialized batch", ""},
      {"root", "Source vertex", "0"}, {"output", "Fresh output directory", ""},
      {"dram_config", "DRAMSim3 configuration", ""}, {"maximum", "Finite cycle budget", "150000000"})
 private:
  SST::Params params_;
};
} // namespace figure_refresh
