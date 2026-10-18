#include "../detail/routed_regraph_system.hpp"

namespace spine::sim {
using namespace detail;

AxiEndpoint RoutedReGraphSystem::Impl::source_memory(std::size_t worker, AxiEndpoint write) {
  const bool paired = config.source_topology == RoutedSourceTopology::kTwoPairwise;
  if (paired && worker >= 2) return *paired_source_endpoints[worker % 2];
  const auto suffix = std::to_string(worker);
  auto &physical = port("source-master" + suffix, worker % 2 == 0 ? 23 : 24, true);
  AxiEndpoint endpoint(physical);
  if (worker < 2) {
    auto &read = client("source-read" + suffix);
    endpoint = share("source-master-mux" + suffix, physical,
        {read.endpoint(true), write});
  }
  if (paired) paired_source_endpoints[worker].emplace(endpoint);
  return endpoint;
}

void RoutedReGraphSystem::Impl::build_source(std::size_t worker, AxiEndpoint memory) {
  const bool paired = config.source_topology == RoutedSourceTopology::kTwoPairwise;
  if (paired && worker < 2) return;
  const auto first = paired ? worker - 2 : worker;
  std::vector<RoutedSourceWorker> inputs;
  for (const auto index : paired ? std::vector{first, worker} : std::vector{worker}) {
    auto &f = *frontends[index];
    inputs.push_back({&f.requests, &f.responses});
  }
  sources.push_back(std::make_unique<RoutedSourceService>("source" + std::to_string(first),
      clock, std::move(inputs), memory, config.compute.max_pending_requests));
  frontends[first]->source = frontends[worker]->source = sources.back().get();
  components.push_back(sources.back().get());
}

void RoutedReGraphSystem::Impl::start_sources(std::uint64_t old_base) {
  const bool paired = config.source_topology == RoutedSourceTopology::kTwoPairwise;
  for (std::size_t service = 0; service < sources.size(); ++service) {
    std::vector<RoutedSourceRegion> regions;
    std::vector<std::size_t> invocations;
    const auto workers = paired ? std::vector{service, service + 2} : std::vector{service};
    for (const auto worker : workers) {
      regions.push_back({old_base, worker % 2 == 0 ? 23U : 24U, padded_vertices});
      invocations.push_back(partitions.size() > worker ? (partitions.size() - 1 - worker) / 4 + 1 : 0);
    }
    sources[service]->start_round(std::move(regions), std::move(invocations));
  }
}

} // namespace spine::sim
