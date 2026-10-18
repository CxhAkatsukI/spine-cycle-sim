#include "../detail/routed_regraph_system.hpp"

namespace spine::sim {
using namespace detail;

RoutedReGraphSystem::Impl::Client::Client(std::string name, ClockId clock, std::size_t depth)
    : requests(name + "-requests", clock, depth), responses(name + "-responses", clock, depth),
      beats(name + "-beats", clock, depth) {}
AxiEndpoint RoutedReGraphSystem::Impl::Client::endpoint(bool stream) {
  return {requests, responses, stream ? &beats : nullptr};
}

RoutedReGraphSystem::Impl::Frontend::Frontend(std::size_t worker, ClockId clock,
    const RoutedReGraphConfig &config)
    : raw("raw" + std::to_string(worker), clock, config.adapter_stream_depth),
      edges("edges" + std::to_string(worker), clock, config.internal_fifo_depth),
      updates("updates" + std::to_string(worker), clock, config.internal_fifo_depth),
      rows("rows" + std::to_string(worker), clock, config.gather_stream_depth),
      requests("requests" + std::to_string(worker), clock, config.external_fifo_depth),
      internal_requests("internal-requests" + std::to_string(worker), clock, config.internal_fifo_depth),
      responses("responses" + std::to_string(worker), clock, config.external_fifo_depth),
      internal_responses("internal-responses" + std::to_string(worker), clock, config.internal_fifo_depth) {}

RoutedReGraphSystem::Impl::Impl(Scheduler &scheduler_, ClockId clock_, MemoryBackend &backend_,
    GraSuPartitionedPmaLayout layout_, AlgorithmInitialState initial_, RoutedReGraphConfig config_)
    : scheduler(scheduler_), clock(clock_), backend(backend_), layout(std::move(layout_)),
      initial(std::move(initial_)), config(std::move(config_)),
      policy({.kind = GraphAlgorithmKind::kWeightedSssp, .vertices = layout.vertices}),
      ordered_rows("ordered-rows", clock, config.mux_stream_depth),
      merged("merged", clock, config.compute.merger_apply_fifo_depth),
      applied("applied", clock, config.compute.apply_wrapper_fifo_depth) {
  admit();
  initialize_memory();
  build();
}

RoutedReGraphSystem::Impl::~Impl() {
  if (registered)
    for (auto it = components.rbegin(); it != components.rend(); ++it) scheduler.remove_component(**it);
}

RoutedReGraphSystem::Impl::Client &RoutedReGraphSystem::Impl::client(std::string name) {
  clients.push_back(std::make_unique<Client>(std::move(name), clock, config.external_fifo_depth));
  auto &value = *clients.back();
  components.insert(components.end(), {&value.requests, &value.responses, &value.beats});
  return value;
}

FixedAxiPort &RoutedReGraphSystem::Impl::port(std::string name, std::size_t channel, bool stream) {
  const auto &c = config.compute;
  ports.push_back(std::make_unique<FixedAxiPort>(std::move(name), clock, FixedAxiPortConfig{
      .memory_channels = 32, .channel = channel,
      .initiator_id = config.first_initiator_id + static_cast<std::uint32_t>(ports.size()),
      .stream_read_beats = stream, .max_pending_requests = c.max_pending_requests,
      .max_outstanding_bursts = c.max_outstanding_bursts,
      .response_beats_per_cycle = c.response_beats_per_cycle,
      .independent_read_write = stream && config.independent_read_write}, backend));
  auto &value = *ports.back();
  components.insert(components.end(), {&value.requests(), &value.responses(), &value.read_beats(), &value.master()});
  return value;
}

AxiEndpoint RoutedReGraphSystem::Impl::share(std::string name, FixedAxiPort &physical,
                                           std::vector<AxiEndpoint> endpoints) {
  auto result = endpoints.front();
  shared.push_back(std::make_unique<SharedAxiPort>(std::move(name), clock, physical,
                                               std::move(endpoints), config.shared_master_capacity));
  components.push_back(shared.back().get());
  return result;
}

void RoutedReGraphSystem::Impl::build() {
  components.insert(components.end(), {&ordered_rows, &merged, &applied});
  auto &primary_write = client("source-primary-write");
  auto &mirror_write = client("source-mirror-write");
  std::array<Fifo<ReGraphGatherRow> *, 4> gather_rows{};
  for (std::size_t worker = 0; worker < 4; ++worker) {
    const auto suffix = std::to_string(worker);
    frontends[worker] = std::make_unique<Frontend>(worker, clock, config);
    auto &f = *frontends[worker];
    components.insert(components.end(), {&f.raw, &f.edges, &f.updates, &f.rows,
        &f.requests, &f.internal_requests, &f.responses, &f.internal_responses});
    auto &adapter_port = port("adapter-master" + suffix, 0, config.adapter.cross_row.bank_read_beats);
    const auto source_endpoint = source_memory(worker,
        worker % 2 == 0 ? primary_write.endpoint() : mirror_write.endpoint());
    f.adapter = std::make_unique<ReGraphPmaAdapter>("adapter" + suffix, clock,
                                                  config.adapter, adapter_port, f.raw);
    f.ingress = std::make_unique<RoutedStreamBridge<ReGraphPmaPacket>>(
        "ingress" + suffix, clock, f.raw, f.edges, true);
    f.request_bridge = std::make_unique<RoutedStreamBridge<ReGraphSourceCacheRequest>>(
        "request-bridge" + suffix, clock, f.internal_requests, f.requests);
    f.response_bridge = std::make_unique<RoutedStreamBridge<ReGraphSourceCacheResponse>>(
        "response-bridge" + suffix, clock, f.responses, f.internal_responses);
    f.scatter = std::make_unique<RoutedScatter>("scatter" + suffix, clock, policy,
        config.adapter.format, f.edges, RoutedSourceWorker{&f.internal_requests, &f.internal_responses}, f.updates);
    f.gather = make_regraph_gather("gather" + suffix, clock, layout.vertices, policy,
                                   config.compute, f.updates, f.rows, *f.scatter);
    components.insert(components.end(), {f.adapter.get(), f.ingress.get(), f.request_bridge.get(),
        f.response_bridge.get(), f.scatter.get()});
    build_source(worker, source_endpoint);
    components.push_back(f.gather.get());
    gather_rows[worker] = &f.rows;
  }
  auto &read = client("apply-read");
  auto &write = client("apply-write");
  auto &status_client = client("apply-status");
  share("apply-master-mux", port("apply-master", 30),
        {read.endpoint(), write.endpoint(), status_client.endpoint()});
  auto global = config.compute;
  global.partition_vertices = padded_vertices;
  mux = std::make_unique<RoutedGatherMux>("gather-mux", clock, gather_rows, ordered_rows, partitions.size());
  merger = make_regraph_merger("global-merger", clock, global, ordered_rows, merged);
  // The hardware processes padding as initialized zero-valued vertices, not
  // the legacy simulator's out-of-range INF sentinel branch.
  apply = make_regraph_apply("global-apply", clock, padded_vertices, policy, global, merged, applied,
      ReGraphApplyPorts{read.endpoint(), write.endpoint(), std::nullopt, std::nullopt, std::nullopt},
      *frontends[0]->scatter);
  writeback = make_regraph_writeback("global-writeback", clock, global, policy, applied,
                                    primary_write.endpoint(), mirror_write.endpoint());
  status = std::make_unique<RoutedStatusWriter>("active-status", clock, status_client.endpoint(),
                                               30, config.status_address);
  components.insert(components.end(), {mux.get(), merger.get(), apply.get(), writeback.get(), status.get()});
}

void RoutedReGraphSystem::Impl::register_components(bool reverse) {
  if (registered || started) throw std::logic_error("routed system can be registered only once");
  if (reverse) std::reverse(components.begin(), components.end());
  for (auto *component : components) scheduler.add_component(*component);
  registered = started = true;
  start_round();
}

void RoutedReGraphSystem::Impl::unregister_components() {
  if (!registered || !complete || !idle()) throw std::logic_error("routed unregister requires completed drained execution");
  for (auto it = components.rbegin(); it != components.rend(); ++it) scheduler.remove_component(**it);
  registered = false;
}

} // namespace spine::sim
