#include "../detail/routed_regraph_system.hpp"

namespace spine::sim {

std::uint64_t RoutedReGraphSystem::Impl::cycle() const {
  return scheduler.clock(clock).completed_cycles;
}

void RoutedReGraphSystem::Impl::start_adapter(std::size_t worker) {
  auto &f = *frontends[worker];
  if (f.next_adapter >= partitions.size()) return;
  f.adapter_record = invocations.size();
  invocations.push_back({rounds.size(), f.next_adapter, worker, true, cycle(), 0});
  f.adapter->start_partition(partitions[f.next_adapter]);
  f.next_adapter += 4;
}

void RoutedReGraphSystem::Impl::start_lksg(std::size_t worker) {
  auto &f = *frontends[worker];
  if (f.next_lksg >= partitions.size()) return;
  const auto &part = partitions[f.next_lksg];
  f.lksg_record = invocations.size();
  invocations.push_back({rounds.size(), f.next_lksg, worker, false, cycle(), 0});
  const bool compact = config.input_path != RoutedInputPath::kPhysicalSlots;
  if (compact) f.ingress->start_until_last(part.slots / 8);
  else f.ingress->start(part.slots / 8);
  f.scatter->start_partition({.physical_slots = part.slots, .destination_base = part.destination_base,
                             .destination_vertices = part.destination_vertices,
                             .iteration = {.base = 0, .dangling_share = dangling_share},
                             .terminal_framed = compact});
  f.gather->start_partition(part.destination_vertices,
                            !config.experimental_gather_reuse || !f.gather_initialized);
  f.gather_initialized = true;
  f.next_lksg += 4;
}

void RoutedReGraphSystem::Impl::start_round() {
  if (!rounds.empty() && !idle()) throw std::logic_error("routed round barrier is not drained");
  rounds.push_back({.start = cycle()});
  status_started = false;
  const auto old_base = config.compute.source_state_base +
      ((rounds.size() - 1) & 1U) * config.compute.source_state_buffer_stride;
  start_sources(old_base);
  for (std::size_t worker = 0; worker < 4; ++worker) {
    auto &f = *frontends[worker];
    f.next_adapter = f.next_lksg = worker;
    start_adapter(worker);
    start_lksg(worker);
  }
  mux->start_round();
  merger->start_round();
  apply->start_partition(rounds.size(), 0, padded_vertices, true);
  writeback->start_partition(rounds.size(), 0);
}

bool RoutedReGraphSystem::Impl::idle() const {
  if (std::any_of(ports.begin(), ports.end(), [](const auto &p) { return !p->idle(); }) ||
      std::any_of(shared.begin(), shared.end(), [](const auto &p) { return !p->idle(); }) ||
      !ordered_rows.empty() || !merged.empty() || !applied.empty()) return false;
  for (const auto &ptr : frontends) {
    const auto &f = *ptr;
    if (!f.raw.empty() || !f.edges.empty() || !f.updates.empty() || !f.rows.empty() ||
        !f.requests.empty() || !f.internal_requests.empty() || !f.responses.empty() ||
        !f.internal_responses.empty() || !f.ingress->done() ||
        !f.request_bridge->done() || !f.response_bridge->done()) return false;
  }
  return true;
}

bool RoutedReGraphSystem::Impl::advance() {
  if (!registered) throw std::logic_error("cannot advance an unregistered routed system");
  if (complete) return true;
  if (rounds.empty() && pagerank_prepare) {
    if (!pagerank_prepare->done()) return false;
    dangling_share = pagerank_prepare->dangling_share();
    start_round();
    return false;
  }
  bool frontends_done = true;
  for (std::size_t worker = 0; worker < 4; ++worker) {
    auto &f = *frontends[worker];
    if (f.adapter_record && f.adapter->done()) {
      invocations[*f.adapter_record].end = cycle();
      f.adapter_record.reset();
      start_adapter(worker);
    }
    if (f.lksg_record && f.ingress->done() && f.scatter->finished() && f.gather->done()) {
      invocations[*f.lksg_record].end = cycle();
      f.lksg_record.reset();
      start_lksg(worker);
    }
    frontends_done &= !f.adapter_record && !f.lksg_record && f.source->done();
  }
  auto &round = rounds.back();
  if (apply->done() && !round.apply_done) {
    round.apply_done = cycle();
    round.active_vertices = apply->active_vertices();
    status->start(static_cast<std::uint32_t>(round.active_vertices));
    status_started = true;
  }
  if (writeback->done() && !round.writeback_done) round.writeback_done = cycle();
  if (status_started && status->done() && !round.status_done) round.status_done = cycle();
  if (!frontends_done || !mux->done() || !merger->done() || !round.apply_done ||
      !round.writeback_done || !round.status_done || !idle()) return false;
  if (detail::decode_u32(backend.inspect_payload(30, config.status_address, 4)) != round.active_vertices)
    throw std::logic_error("resident active status differs from Apply reduction");
  round.end = cycle();
  if ((config.fixed_rounds && rounds.size() == config.fixed_rounds) ||
      (!config.fixed_rounds && round.active_vertices == 0)) {
    complete = true;
  } else if (rounds.size() >= config.compute.max_supersteps) {
    complete = failed = true;
    failure = "routed graph algorithm reached the superstep limit before the declared completion boundary";
  } else {
    if (pagerank_prepare)
      dangling_share = GraphAlgorithmPolicy::float_to_word(policy.config().damping *
          apply->next_dangling() / static_cast<float>(layout.vertices));
    start_round();
  }
  return complete;
}

} // namespace spine::sim
