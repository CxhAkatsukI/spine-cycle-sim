#pragma once

#include <memory>
#include <string>
#include <vector>

#include "spine_sim/grasu_update/search.hpp"

namespace spine::sim::grasu_update_detail {

struct DegreeDelta {
  std::uint64_t global_index{};
  std::uint32_t source{};
  std::int32_t delta{};
};

// All three geometries use direct HBM read/modify/write, not an implicit cache.
enum class DirectProcessorTopology { kSequentialHot, kParallelHot, kCold };

class Processor : public Component {
public:
  struct Ports {
    Fifo<LocatedUpdate>* input{};
    std::array<FixedAxiPort*, 2> reads{};
    std::array<FixedAxiPort*, 2> writes{};
    Fifo<DegreeDelta>* degree_output{};
  };
  using Component::Component;
  virtual bool idle() const noexcept = 0;
  virtual bool failed() const noexcept = 0;
  virtual const std::string& failure() const noexcept = 0;
  virtual std::uint64_t completed() const noexcept = 0;
  virtual std::uint64_t lane_queue_stalls() const noexcept = 0;
  virtual std::uint64_t pma_reads() const noexcept { return completed(); }
  virtual std::uint64_t pma_writes() const noexcept { return completed(); }
};

std::unique_ptr<Processor> make_direct_processor(
    std::string name, ClockId clock, DirectProcessorTopology topology,
    std::size_t lane_fifo_depth, std::uint64_t pma_base,
    std::uint64_t partition_stride,
    const std::vector<std::uint64_t>& partition_bases,
    bool explicit_regions, GraSuPmaWordAbi abi, Processor::Ports ports);

}  // namespace spine::sim::grasu_update_detail
