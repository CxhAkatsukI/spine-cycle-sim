#include "spine_sim/original_regraph/mixed_indexer.hpp"

#include <limits>

namespace spine::sim::original_regraph {

MixedWriteIndexer::MixedWriteIndexer(std::string name, ClockId clock,
    Fifo<PropertyLine>& little, Fifo<PropertyLine>& big, Fifo<PropertyWrite>& output, PipelineTiming timing)
    : Component(std::move(name), clock), little_(little), big_(big), output_(output), pipeline_(timing) {
  if (&little == &big || little.clock_id() != clock || big.clock_id() != clock || output.clock_id() != clock) {
    throw std::invalid_argument("mixed indexer requires distinct same-clock inputs");
  }
}
void MixedWriteIndexer::begin(std::uint32_t little_lines, std::uint32_t big_lines) {
  if (active_ || !pipeline_.drained() || !little_.empty() || !big_.empty() || !output_.empty()) {
    throw std::logic_error("mixed indexer restart requires drain");
  }
  if (std::uint64_t{little_lines} + big_lines > std::numeric_limits<std::uint32_t>::max()) {
    throw std::out_of_range("mixed write index domain exceeded");
  }
  little_lines_ = little_lines; big_lines_ = big_lines;
  little_index_ = big_index_ = 0; active_ = true;
}
void MixedWriteIndexer::evaluate(const CycleContext& context) {
  accepted_little_ = accepted_big_ = ended_ = false;
  if (!active_) return;
  if ((little_index_ == little_lines_ && !little_.empty()) || (big_index_ == big_lines_ && !big_.empty())) {
    throw std::logic_error("excess mixed merge output");
  }
  if (const auto* packet = pipeline_.ready(context.domain_cycle)) {
    if (output_.try_push(*packet)) pipeline_.stage_retire();
    else pipeline_.output_stall();
  }
  if (pipeline_.can_accept(context.domain_cycle)) {
    PropertyLine data;
    if (little_index_ < little_lines_ && little_.try_pop(data)) {
      pipeline_.stage_accept({data, little_index_, false}, context.domain_cycle); accepted_little_ = true;
    } else if (big_index_ < big_lines_ && big_.try_pop(data)) {
      pipeline_.stage_accept({data, little_lines_ + big_index_, false}, context.domain_cycle); accepted_big_ = true;
    }
  }
  if (little_index_ == little_lines_ && big_index_ == big_lines_ && pipeline_.drained()) {
    ended_ = output_.try_push({{}, 0, true});
  }
}
void MixedWriteIndexer::commit(const CycleContext& context) {
  if (accepted_little_) ++little_index_;
  if (accepted_big_) ++big_index_;
  if (ended_) active_ = false;
  pipeline_.commit(context.domain_cycle);
}

}  // namespace spine::sim::original_regraph
