#include "sst/core/sst_config.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <fstream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "spine_sim/axi.hpp"
#include "spine_sim/fifo.hpp"
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
            local_address, request.bytes,
            std::vector<std::uint8_t>(request.bytes, 0));
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
    external_arrivals_.push_back(BackendResponse{
        .initiator_id = found->second.initiator_id,
        .request_id = found->second.backend_request_id,
        .success = request->getSuccess(),
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
    if ((mode_ != "probe" && mode_ != "spine_vertical") || channels_ == 0 ||
        channel_capacity_bytes_ == 0 || write_percent_ > 100 ||
        (mode_ == "probe" &&
         (request_count_ == 0 || request_bytes_ == 0 || stride_bytes_ == 0)) ||
        (mode_ == "spine_vertical" &&
         (channels_ < 23 || workload_path_.empty()))) {
      output_.fatal(CALL_INFO, -1, "invalid online memory probe parameters\n");
    }

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
    if (mode_ == "spine_vertical") {
      SpineEdgeSlice workload = load_spine_edge_slice(workload_path_);
      spine_expected_edges_ = workload.edges.size();
      SpineL0Config maintenance_config;
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
          4096, std::move(maintenance_config), std::move(initial_state));
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
    source_ = std::make_unique<ProbeSource>(
        core, *requests_, request_count_, request_bytes_, stride_bytes_,
        channel_capacity_bytes_ * channels_, write_percent_);
    sink_ = std::make_unique<ProbeSink>(core, *responses_);

    scheduler_.add_component(*source_);
    scheduler_.add_component(*requests_);
    scheduler_.add_component(*axi_);
    scheduler_.add_component(*backend_);
    scheduler_.add_component(*responses_);
    scheduler_.add_component(*sink_);
  }

  void finish() override {
    if (!result_written_) {
      write_result(false);
    }
  }

  bool clock_tick(SST::Cycle_t) {
    scheduler_.step();
    if (mode_ == "spine_vertical") {
      if (spine_system_->done() && spine_system_->idle() &&
          backend_->outstanding() == 0) {
        write_result(!spine_system_->failed());
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
      {"mode", "probe or spine_vertical", "probe"},
      {"workload", "Spine .slice workload path", ""},
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
      {"max_cycles", "Core-cycle timeout", "1000000"})

  SST_ELI_DOCUMENT_SUBCOMPONENT_SLOTS(
      {"memory", "One StandardMem interface per HBM channel",
       "SST::Interfaces::StandardMem"})

 private:
  void write_result(bool success) {
    if (result_written_) {
      return;
    }
    result_written_ = true;
    std::ofstream result(result_path_);
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
      const auto &reader = spine_system_->reader_counters();
      const auto &compute = spine_system_->compute_counters();
      result << "{\n"
             << "  \"success\": " << (passed ? "true" : "false") << ",\n"
             << "  \"mode\": \"spine_vertical\",\n"
             << "  \"backend\": \"sst_memHierarchy_dramsim3\",\n"
             << "  \"cycles\": " << scheduler_.clock(0).completed_cycles
             << ",\n"
             << "  \"sim_time_fs\": "
             << scheduler_.clock(0).next_edge_fs - scheduler_.clock(0).phase_fs
             << ",\n"
             << "  \"input_edges\": " << spine_expected_edges_ << ",\n"
             << "  \"preload_edges\": " << spine_preload_edges_ << ",\n"
             << "  \"correctness_mismatches\": " << mismatches << ",\n"
             << "  \"frontier_mismatches\": " << frontier_mismatches << ",\n"
             << "  \"next_active\": "
             << spine_system_->compute().next_active().size() << ",\n"
             << "  \"maintenance_scan_passes\": "
             << maintenance.sorted_scan_passes << ",\n"
             << "  \"maintenance_edge_visits\": "
             << maintenance.sorted_edge_visits << ",\n"
             << "  \"maintenance_sorted_bytes\": "
             << maintenance.sorted_read_bytes << ",\n"
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
             << "  \"maintenance_carry_merge_inputs\": "
             << maintenance.carry_merge_inputs << ",\n"
             << "  \"maintenance_carry_outputs\": " << maintenance.carry_outputs
             << ",\n"
             << "  \"reader_tiles\": " << reader.tiles_emitted << ",\n"
             << "  \"reader_edges\": " << reader.edges_emitted << ",\n"
             << "  \"reader_graph_bytes\": " << reader.graph_read_bytes << ",\n"
             << "  \"reader_metadata_bytes\": " << reader.metadata_read_bytes
             << ",\n"
             << "  \"reader_occupied_levels\": " << reader.occupied_levels
             << ",\n"
             << "  \"reader_cold_edges\": " << reader.cold_edges_emitted
             << ",\n"
             << "  \"reader_hot_edges\": " << reader.hot_edges_emitted << ",\n"
             << "  \"compute_fast_tiles\": " << compute.fast_path_tiles << ",\n"
             << "  \"compute_full_tiles\": " << compute.full_path_tiles << ",\n"
             << "  \"compute_processed_edges\": " << compute.processed_edges
             << ",\n"
             << "  \"edge_axis_transfers\": "
             << spine_system_->edge_stream_stats().pushes << ",\n"
             << "  \"edge_axis_max_occupancy\": "
             << spine_system_->edge_stream_stats().max_occupancy << ",\n"
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
  SST::TimeConverter clock_converter_{};
  std::vector<SST::Interfaces::StandardMem *> interfaces_;

  Scheduler scheduler_;
  std::unique_ptr<Fifo<AxiRequest>> requests_;
  std::unique_ptr<Fifo<AxiResponse>> responses_;
  std::unique_ptr<SstMemoryBackend> backend_;
  std::unique_ptr<AxiMaster> axi_;
  std::unique_ptr<ProbeSource> source_;
  std::unique_ptr<ProbeSink> sink_;
  std::unique_ptr<SpineVerticalSliceSystem> spine_system_;
  std::size_t spine_expected_edges_{};
  std::size_t spine_preload_edges_{};
  std::unordered_map<std::uint32_t, std::uint32_t> expected_distances_;
  bool result_written_{};
};

}  // namespace spine::sim::sst_adapter
