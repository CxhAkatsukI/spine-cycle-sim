#pragma once

#include "routed_regraph_scatter.hpp"
#include "routed_regraph_transport.hpp"
#include "routed_regraph_input.hpp"
#include "routed_regraph_observer.hpp"
#include "spine_sim/routed_regraph.hpp"
#include "spine_sim/shared_axi_port.hpp"

namespace spine::sim {

class RoutedReGraphSystem::Impl {
public:
  Impl(Scheduler &, ClockId, MemoryBackend &, GraSuPartitionedPmaLayout,
       AlgorithmInitialState, RoutedReGraphConfig);
  ~Impl();
  void admit();
  void initialize_memory();
  void build();
  AxiEndpoint source_memory(std::size_t worker, AxiEndpoint write);
  void build_source(std::size_t worker, AxiEndpoint);
  void start_sources(std::uint64_t old_base);
  void register_components(bool reverse);
  void unregister_components();
  void start_round();
  void start_adapter(std::size_t worker);
  void start_lksg(std::size_t worker);
  bool advance();
  [[nodiscard]] bool idle() const;
  [[nodiscard]] std::uint64_t cycle() const;
  [[nodiscard]] std::vector<std::uint32_t> read_words(std::size_t channel,
                                                    std::uint64_t address) const;
  [[nodiscard]] RoutedReGraphCounters counters() const;

  struct Client {
    Client(std::string, ClockId, std::size_t);
    AxiEndpoint endpoint(bool stream = false);
    Fifo<AxiRequest> requests;
    Fifo<AxiResponse> responses;
    Fifo<AxiReadBeatResponse> beats;
  };
  struct Frontend {
    Frontend(std::size_t, ClockId, const RoutedReGraphConfig &);
    Fifo<ReGraphPmaPacket> raw, edges;
    Fifo<detail::PmaEdgeBatch> updates;
    Fifo<detail::ReGraphGatherRow> rows;
    Fifo<detail::ReGraphSourceCacheRequest> requests, internal_requests;
    Fifo<detail::ReGraphSourceCacheResponse> responses, internal_responses;
    std::unique_ptr<detail::RoutedStreamBridge<ReGraphPmaPacket>> ingress;
    std::unique_ptr<detail::RoutedStreamBridge<detail::ReGraphSourceCacheRequest>> request_bridge;
    std::unique_ptr<detail::RoutedStreamBridge<detail::ReGraphSourceCacheResponse>> response_bridge;
    std::unique_ptr<detail::RoutedPmaInput> adapter;
    std::unique_ptr<detail::RoutedScatter> scatter;
    detail::RoutedSourceService *source{};
    std::unique_ptr<detail::ReGraphGatherEngine> gather;
    std::size_t next_adapter{}, next_lksg{};
    std::optional<std::size_t> adapter_record, lksg_record;
    bool gather_initialized{};
  };
  Client &client(std::string name);
  FixedAxiPort &port(std::string name, std::size_t channel, bool stream = false);
  AxiEndpoint share(std::string name, FixedAxiPort &, std::vector<AxiEndpoint>);

  Scheduler &scheduler;
  ClockId clock;
  MemoryBackend &backend;
  GraSuPartitionedPmaLayout layout;
  AlgorithmInitialState initial;
  RoutedReGraphConfig config;
  GraphAlgorithmPolicy policy;
  std::size_t padded_vertices{};
  GraSuReGraphRuntimePlan plan;
  std::vector<ReGraphPmaPartition> partitions;
  std::vector<std::unique_ptr<FixedAxiPort>> ports;
  std::vector<std::unique_ptr<Client>> clients;
  std::vector<std::unique_ptr<SharedAxiPort>> shared;
  std::array<std::unique_ptr<Frontend>, 4> frontends;
  std::array<std::optional<AxiEndpoint>, 2> paired_source_endpoints;
  std::vector<std::unique_ptr<detail::RoutedSourceService>> sources;
  Fifo<detail::ReGraphGatherRow> ordered_rows;
  Fifo<detail::ReGraphMergedBurst> merged;
  Fifo<detail::ReGraphAppliedBurst> applied;
  std::unique_ptr<detail::RoutedGatherMux> mux;
  std::unique_ptr<detail::ReGraphMergerEngine> merger;
  std::unique_ptr<detail::ReGraphApplyEngine> apply;
  std::unique_ptr<detail::RoutedApplyObserver> apply_observer;
  std::unique_ptr<detail::ReGraphWritebackEngine> writeback;
  std::unique_ptr<detail::RoutedStatusWriter> status;
  std::vector<Component *> components;
  std::vector<RoutedReGraphInvocation> invocations;
  std::vector<RoutedReGraphRound> rounds;
  bool registered{}, started{}, complete{}, failed{}, status_started{};
  std::string failure;
};

} // namespace spine::sim
