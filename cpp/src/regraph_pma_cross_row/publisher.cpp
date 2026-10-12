#include "state.hpp"

#include "../detail/grasu_regraph_payload.hpp"
#include "spine_sim/grasu_native.hpp"

namespace spine::sim::detail {

ReGraphPmaPacket CrossRowPmaAdapter::packet() const {
  ReGraphPmaPacket result;
  const auto &loaded = *publishing_;
  for (std::size_t lane = 0; lane < 8; ++lane) {
    const auto slot = loaded.task.segment * 16 + half_ * 8 + lane;
    const auto word = decode_u32(loaded.bytes, (half_ * 8 + lane) * 4);
    const auto local = word & kGraSuPmaDestinationMask;
    const auto dummy = (word & 0x8000'0000U) || local >= partition_.destination_vertices ||
        slot < loaded.task.begin || slot >= loaded.task.end || slot >= total_slots_;
    const auto flag = dummy ? 0x8000'0000U : 0U;
    result.sources[lane] = static_cast<std::uint32_t>(loaded.task.source) | flag;
    auto destination = word & 0x7fff'ffffU;
    if (config_.format == ReGraphPmaFormat::kDestination) destination = partition_.destination_base + local;
    else if (config_.format == ReGraphPmaFormat::kUnitWeight) destination = local | (1U << kGraSuPmaWeightShift);
    result.destinations[lane] = destination | flag;
  }
  result.last = emitted_slots_ + 8 >= total_slots_;
  return result;
}

} // namespace spine::sim::detail
