#include "../detail/routed_regraph_system.hpp"

#include <sstream>

namespace spine::sim {

RoutedReGraphCounters RoutedReGraphSystem::Impl::counters() const {
  RoutedReGraphCounters c;
  for (const auto &f : frontends) {
    const auto &a = f->adapter->counters();
    c.extent_reads += a.extent_reads;
    c.row_reads += a.row_reads;
    c.segment_reads += a.segment_reads;
    c.packets += a.packets;
    c.live_edges += a.live_edges;
    c.dummy_edges += a.dummy_edges;
    c.gather_rows += f->gather->rows_emitted();
  }
  for (const auto &source : sources) {
    const auto &s = source->counters();
    for (std::size_t worker = 0; worker < s.blocks.size(); ++worker) {
      c.source_blocks += s.blocks[worker];
      c.source_lines += s.lines[worker];
      c.source_terminators += s.terminators[worker];
    }
  }
  c.mux_rows = mux->rows();
  c.apply_reads = apply->reads();
  c.apply_writes = apply->writes();
  c.degree_reads = apply->degree_reads();
  if (pagerank_prepare) {
    const auto p = pagerank_prepare->counters();
    c.prepare_state_reads = p.state_reads;
    c.prepare_degree_reads = p.degree_reads;
    c.prepare_degree_writes = p.degree_writes;
    c.prepare_source_writes = p.source_writes;
    c.prepare_cycles = p.end ? p.end - p.start : 0;
    c.start_cycle = p.start;
  }
  c.source_writes = writeback->source_writes();
  c.status_writes = status->writes();
  for (const auto &port : ports) {
    const auto &s = port->master().stats();
    c.axi_requests += s.requests_accepted;
    c.axi_completions += s.requests_completed;
    c.axi_beats += s.beats_issued;
    c.axi_completed_beats += s.beats_completed;
  }
  if (!rounds.empty()) {
    if (!pagerank_prepare) c.start_cycle = rounds.front().start;
    c.end_cycle = rounds.back().end;
  }
  return c;
}

RoutedReGraphSystem::RoutedReGraphSystem(Scheduler &scheduler, ClockId clock, MemoryBackend &backend,
    GraSuPartitionedPmaLayout layout, AlgorithmInitialState initial, RoutedReGraphConfig config)
    : impl_(std::make_unique<Impl>(scheduler, clock, backend, std::move(layout),
                                   std::move(initial), std::move(config))) {}
RoutedReGraphSystem::~RoutedReGraphSystem() = default;
void RoutedReGraphSystem::register_components(bool reverse) { impl_->register_components(reverse); }
void RoutedReGraphSystem::unregister_components() { impl_->unregister_components(); }
bool RoutedReGraphSystem::advance_if_complete() { return impl_->advance(); }
bool RoutedReGraphSystem::done() const noexcept { return impl_->complete; }
bool RoutedReGraphSystem::failed() const noexcept { return impl_->failed; }
const std::string &RoutedReGraphSystem::failure() const noexcept { return impl_->failure; }
std::vector<std::uint32_t> RoutedReGraphSystem::encoded_state() const {
  return impl_->read_words(30, impl_->config.compute.vertex_state_base);
}
std::vector<std::uint32_t> RoutedReGraphSystem::distances() const {
  auto words = encoded_state();
  words.resize(impl_->layout.vertices);
  for (auto &word : words) word = detail::decode_policy_value(impl_->policy, word);
  return words;
}
std::vector<std::uint32_t> RoutedReGraphSystem::residual_words() const {
  if (!impl_->pagerank_prepare) return {};
  auto words = impl_->read_words(30, impl_->config.compute.residual_state_base);
  words.resize(impl_->layout.vertices);
  return words;
}
std::vector<std::uint32_t> RoutedReGraphSystem::source_state(std::size_t copy, std::size_t buffer) const {
  if (copy > 1 || buffer > 1) throw std::out_of_range("routed source state copy or buffer is invalid");
  return impl_->read_words(copy == 0 ? 23 : 24, impl_->config.compute.source_state_base +
                            buffer * impl_->config.compute.source_state_buffer_stride);
}
const GraSuReGraphRuntimePlan &RoutedReGraphSystem::runtime_plan() const noexcept { return impl_->plan; }
const std::vector<RoutedReGraphInvocation> &RoutedReGraphSystem::invocations() const noexcept { return impl_->invocations; }
const std::vector<RoutedReGraphRound> &RoutedReGraphSystem::rounds() const noexcept { return impl_->rounds; }
RoutedReGraphCounters RoutedReGraphSystem::counters() const { return impl_->counters(); }

RoutedReGraphObservation RoutedReGraphSystem::observation() const {
  RoutedReGraphObservation result;
  for (std::size_t worker = 0; worker < result.frontends.size(); ++worker) {
    const auto& f = *impl_->frontends[worker];
    const auto& s = f.scatter->counters();
    const auto& g = *f.gather;
    result.frontends[worker] = {s.packets, s.emitted, s.source_waits, s.edge_waits,
        s.output_stalls, s.pipeline_stalls, s.request_stalls, s.source_lines,
        g.reset_cycles(), g.merge_cycles(), g.pipeline_drain_cycles(),
        g.output_stall_cycles(), g.conflict_cycles(), g.rows_emitted()};
  }
  for (const auto& source : impl_->sources) {
    const auto& s = source->counters();
    result.sources.push_back({s.blocks[0] + s.blocks[1], s.lines[0] + s.lines[1],
        s.terminators[0] + s.terminators[1], s.memory_parents, s.memory_completions,
        s.output_stalls, s.issue_stalls, s.max_pending});
  }
  const auto& a = *impl_->apply;
  const auto& w = *impl_->writeback;
  result.backend = {impl_->merger->output_stall_cycles(), a.output_stall_cycles(),
      impl_->apply_observer->blocked_cycles(), a.pipeline_capacity_stalls(), a.write_window_stalls(),
      w.pipeline_capacity_stalls(), w.write_window_stalls(), a.max_reads_inflight(),
      a.max_pipeline_occupancy(), a.max_writes_inflight(), w.max_pipeline_occupancy(),
      w.max_writes_inflight()};
  return result;
}

std::string RoutedReGraphSystem::diagnostic() const {
  std::ostringstream out;
  out << "round=" << impl_->rounds.size() << " cycle=" << impl_->cycle()
      << " mux=" << impl_->mux->done() << " merger=" << impl_->merger->done()
      << " apply=" << impl_->apply->done() << " writeback=" << impl_->writeback->done()
      << " status=" << impl_->status->done() << " idle=" << impl_->idle()
      << " global-queues=" << impl_->ordered_rows.size() << ',' << impl_->merged.size() << ',' << impl_->applied.size()
      << " mux-rows=" << impl_->mux->rows() << " apply-rw=" << impl_->apply->reads() << ',' << impl_->apply->writes()
      << " writeback-writes=" << impl_->writeback->source_writes()
      << " backend-outstanding=" << impl_->backend.outstanding();
  out << " source-services=" << impl_->sources.size() << " physical-masters=" << impl_->ports.size();
  for (std::size_t worker = 0; worker < 4; ++worker) {
    const auto &f = *impl_->frontends[worker];
    out << "\nworker=" << worker << " adapter=" << f.adapter->done()
        << " ingress=" << f.ingress->done() << " scatter=" << f.scatter->done()
        << '/' << f.scatter->finished() << " gather=" << f.gather->done()
        << " source=" << f.source->done() << " source-service=" << f.source->name()
        << " packets=" << f.scatter->counters().packets
        << " lines=" << f.scatter->counters().source_lines << '+' << f.scatter->counters().discarded_lines
        << " rows=" << f.gather->rows_emitted() << " queues=" << f.raw.size() << ',' << f.edges.size()
        << ',' << f.updates.size() << ',' << f.rows.size() << ',' << f.internal_requests.size()
        << ',' << f.requests.size() << ',' << f.responses.size() << ',' << f.internal_responses.size();
  }
  for (const auto &p : impl_->ports) {
    out << "\nmaster=" << p->master().name() << " pending=" << p->master().pending_requests()
        << " bursts=" << p->master().outstanding_bursts() << " queues=" << p->requests().size()
        << ',' << p->responses().size() << ',' << p->read_beats().size();
    if (!p->master().idle()) out << ' ' << p->master().diagnostic();
  }
  for (const auto &p : impl_->shared) out << "\nshared=" << p->name() << " pending=" << p->pending();
  for (const auto *c : impl_->components)
    if (c->has_latched_evaluate_guard())
      out << "\nguard=" << c->name() << " ready=" << c->evaluate_ready()
          << " latched=" << c->latched_evaluate_ready();
  return out.str();
}

} // namespace spine::sim
