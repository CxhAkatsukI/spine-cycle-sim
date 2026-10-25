#pragma once

#include <functional>

#include "spine_sim/grasu_update/processor.hpp"

namespace spine::sim::grasu_update_detail {

// Source16 geometry and isolated process_1 schedule, not a routed-G calibration.
inline constexpr std::size_t kCachedHotSegments = 131072;
inline constexpr std::size_t kCachedHotBanks = 16;
inline constexpr std::size_t kCachedBankQueueDepth = 2;
inline constexpr std::uint64_t kCachedUpdateInterval = 3;
inline constexpr std::uint64_t kCachedUpdateLatency = 7;

// input_closed must become true only after the producer has committed its last
// packet. Completion includes bank-rounded preload and acknowledged writeback.
// The default preserves the legacy full-capacity transfer; zero skips memory.
std::unique_ptr<Processor> make_cached_processor(
    std::string name, ClockId clock, std::uint64_t pma_base,
    Processor::Ports ports, std::function<bool()> input_closed,
    std::size_t valid_segments = kCachedHotSegments);

}  // namespace spine::sim::grasu_update_detail
