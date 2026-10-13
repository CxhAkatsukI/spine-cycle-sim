#pragma once

#include <memory>
#include <string>

#include "spine_sim/fifo.hpp"
#include "spine_sim/fixed_axi_port.hpp"
#include "spine_sim/grasu.hpp"

namespace spine::sim::grasu_update_detail {

struct LocatedUpdate {
  std::uint64_t global_index{};
  std::uint32_t source{};
  std::size_t partition{};
  std::uint32_t segment_head_slot{};
  std::uint32_t destination{};
  std::uint16_t weight{1};
  bool delete_op{};
  std::uint64_t last_binary_head{};
};

class Search : public Component {
public:
  using Component::Component;
  virtual bool done() const noexcept = 0;
  virtual bool failed() const noexcept = 0;
  virtual const std::string& failure() const noexcept = 0;
  virtual std::uint64_t row_reads() const noexcept = 0;
  virtual std::uint64_t binary_probes() const noexcept = 0;
};

std::unique_ptr<Search> make_parallel_search(
    std::string name, ClockId clock, std::size_t cu, std::size_t count,
    std::uint64_t update_base, std::uint64_t row_base,
    std::uint64_t binary_base, FixedAxiPort& updates,
    FixedAxiPort& metadata, Fifo<LocatedUpdate>& output,
    std::size_t contexts = 16);

}  // namespace spine::sim::grasu_update_detail
