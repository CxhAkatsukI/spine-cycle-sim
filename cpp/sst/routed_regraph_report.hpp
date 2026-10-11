#pragma once

#include "spine_sim/routed_regraph_fixture.hpp"
#include "sst_memory_backend.hpp"

namespace spine::sim::sst_adapter {
void write_routed_regraph_report(const std::string &path, const RoutedReGraphFixture &,
                                const RoutedReGraphSystem &, const SstMemoryBackend &,
                                std::uint64_t observed_cycles);
}
