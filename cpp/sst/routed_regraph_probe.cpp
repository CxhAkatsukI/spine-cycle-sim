// clang-format off
#include "sst/core/sst_config.h"
// clang-format on

#include "routed_regraph_report.hpp"
#include "sst/core/component.h"
#include "sst/core/output.h"
#include "sst/core/params.h"
#include "sst/core/timeConverter.h"

#include <fstream>
#include <iostream>
#include <numeric>

namespace spine::sim::sst_adapter {
class RoutedReGraphProbe final : public SST::Component {
public:
  RoutedReGraphProbe(SST::ComponentId_t id, SST::Params &params) : SST::Component(id) {
    fixture_ = load_routed_regraph_fixture(params.find<std::string>("fixture", ""));
    output_path_ = params.find<std::string>("output", "");
    dram_config_ = params.find<std::string>("dram_config", "");
    dram_output_ = params.find<std::string>("dram_output", "");
    max_cycles_ = params.find<std::uint64_t>("max_cycles", 300000000);
    prefetch_ = params.find<bool>("row_prefetch", true);
    stop_ = params.find<bool>("stop_after_last", true);
    profile_id_ = params.find<std::string>("profile_id", "grasu_regraph_routed_sssp_compute_v1");
    independent_ = params.find<bool>("independent_read_write", false);
    routed_stream_depths_ = params.find<bool>("routed_stream_depths", false);
    routed_empty_exit_ = params.find<bool>("routed_empty_exit", false);
    row_line_model_ = params.find<bool>("row_line_model", false);
    row_line_read_ = params.find<bool>("row_line_read", false);
    cross_row_model_ = params.find<bool>("cross_row_model", false);
    cross_row_pipeline_ = params.find<bool>("cross_row_pipeline", false);
    const auto expected_profile = cross_row_model_ ? "grasu_regraph_cross_row_sssp_compute_v1" :
        row_line_model_ ? "grasu_regraph_row_line_sssp_compute_v1" :
        routed_empty_exit_ ? "grasu_regraph_routed_sssp_compute_v4" :
        routed_stream_depths_ ? "grasu_regraph_routed_sssp_compute_v3" :
        independent_ ? "grasu_regraph_routed_sssp_compute_v2" : "grasu_regraph_routed_sssp_compute_v1";
    if (profile_id_ != expected_profile || (routed_stream_depths_ && !independent_) ||
        (routed_empty_exit_ && !routed_stream_depths_) || (row_line_read_ && !row_line_model_ && !cross_row_model_) ||
        ((row_line_model_ || cross_row_model_) && (!routed_stream_depths_ || !prefetch_ || !stop_ || routed_empty_exit_)) ||
        (cross_row_pipeline_ && !cross_row_model_) ||
        (cross_row_model_ && (row_line_model_ || !row_line_read_)))
      throw std::invalid_argument("routed profile, AXI channels and stream depths disagree");
    if (output_path_.empty() || dram_config_.empty() || dram_output_.empty() || !max_cycles_)
      throw std::invalid_argument("missing routed SST paths or cycle limit");
    registerClock("150MHz", new SST::Clock::Handler<RoutedReGraphProbe, &RoutedReGraphProbe::tick>(this));
    picoseconds_ = getTimeConverter("1ps");
    registerAsPrimaryComponent();
    primaryComponentDoNotEndSim();
  }

  void setup() override {
    const auto clock = scheduler_.add_clock_mhz("kernel", 150);
    std::vector<std::size_t> channels(32);
    std::iota(channels.begin(), channels.end(), 0);
    auto engine = std::make_unique<DirectDramSim3Engine>(DirectDramSim3Engine::Config{
        .channels = 32, .active_channels = channels, .dram_config_path = dram_config_, .output_root = dram_output_});
    backend_ = std::make_unique<SstMemoryBackend>(clock,
        std::vector<SST::Interfaces::StandardMem *>(32, nullptr), 512ULL << 20, 1, 32, 128,
        "identity", "", 0, 0, 64, std::move(engine));
    scheduler_.add_component(*backend_);
    RoutedReGraphConfig config;
    config.adapter.prefetch_rows = prefetch_;
    config.adapter.stop_after_last = stop_;
    config.adapter.row_line_reads = row_line_read_;
    config.adapter.cross_row_pipeline = cross_row_pipeline_;
    if (routed_empty_exit_) config.adapter.empty_segment_exit_cycles = 73;
    config.compute.cache_segments_per_half = fixture_.cache_segments;
    config.compute.runtime_physical_updates_per_shard = fixture_.physical_updates;
    config.compute.max_supersteps = 256;
    config.compute.apply_request_window = 16;
    config.independent_read_write = independent_;
    if (routed_stream_depths_) {
      config.adapter_stream_depth = 32;
      config.gather_stream_depth = 32;
      config.mux_stream_depth = 32;
    }
    // Explicit, disjoint physical model offsets. These are not captured XRT
    // BO addresses and must not be described as exact board address replay.
    config.compute.vertex_state_base = 0;
    config.compute.source_state_base = 0;
    config.compute.source_state_buffer_stride = fixture_.layout.partitions.size() * 65536 * 4;
    config.status_address = (config.compute.source_state_buffer_stride + 4095) / 4096 * 4096;
    system_ = std::make_unique<RoutedReGraphSystem>(scheduler_, clock, *backend_, fixture_.layout,
                                                  fixture_.initial, config);
    system_->register_components();
  }

  void finish() override {
    if (!system_) return;
    write_routed_regraph_report(output_path_, fixture_, *system_, *backend_, scheduler_.clock(0).completed_cycles, profile_id_);
    std::ofstream diagnostic(output_path_ + ".diagnostic.txt");
    diagnostic << system_->failure() << '\n' << system_->diagnostic() << '\n';
    backend_->print_direct_stats();
  }

  bool tick(SST::Cycle_t) {
    backend_->advance_direct_to(getCurrentSimTime(picoseconds_));
    scheduler_.step();
    system_->advance_if_complete();
    const auto cycle = scheduler_.clock(0).completed_cycles;
    if (cycle % 1000000 == 0)
      std::cout << "routed_progress cycles=" << cycle << " rounds=" << system_->rounds().size() << std::endl;
    if (system_->done() || cycle >= max_cycles_) {
      primaryComponentOKToEndSim();
      return true;
    }
    return false;
  }

  SST_ELI_REGISTER_COMPONENT(RoutedReGraphProbe, "spine_cycle", "RoutedReGraphProbe",
      SST_ELI_ELEMENT_VERSION(1, 0, 0), "Artifact-bound resident routed SSSP compute candidate",
      COMPONENT_CATEGORY_MEMORY)
  SST_ELI_DOCUMENT_PARAMS(
      {"fixture", "Version-1 HLS-exported resident fixture", ""},
      {"output", "Candidate JSON result", ""},
      {"dram_config", "Pinned DRAMSim3 INI", ""},
      {"dram_output", "DRAMSim3 output directory", ""},
      {"max_cycles", "Explicit device cycle cap", "300000000"},
      {"row_prefetch", "Optimized row issue path", "1"},
      {"stop_after_last", "Stop at last occupied row", "1"},
      {"profile_id", "Explicit model identity", "grasu_regraph_routed_sssp_compute_v1"},
      {"independent_read_write", "Separate shared-master AR/AW credits and R/B backpressure", "0"},
      {"routed_stream_depths", "Routed depth-32 edge, Gather and mux streams; other queues unchanged", "0"},
      {"routed_empty_exit", "Routed RTL 73-cycle exit for each visited empty row", "0"},
      {"row_line_model", "Explicit unrouted skip-empty/whole-line comparison identity", "0"},
      {"row_line_read", "Decode eight directory entries per read; requires an explicit line/cross-row model", "0"},
      {"cross_row_model", "Explicit unrouted whole-line/cross-row structural comparison identity", "0"},
      {"cross_row_pipeline", "Separate cross-row reader and finite loaded-FIFO publisher", "0"})
private:
  Scheduler scheduler_;
  RoutedReGraphFixture fixture_;
  std::unique_ptr<SstMemoryBackend> backend_;
  std::unique_ptr<RoutedReGraphSystem> system_;
  SST::TimeConverter picoseconds_;
  std::string output_path_, dram_config_, dram_output_, profile_id_;
  std::uint64_t max_cycles_{};
  bool prefetch_{}, stop_{}, independent_{}, routed_stream_depths_{}, routed_empty_exit_{};
  bool row_line_model_{}, row_line_read_{};
  bool cross_row_model_{}, cross_row_pipeline_{};
};
} // namespace spine::sim::sst_adapter
