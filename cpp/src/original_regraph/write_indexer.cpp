#include "spine_sim/original_regraph/write_indexer.hpp"

namespace spine::sim::original_regraph {

LittleWriteIndexer::LittleWriteIndexer(std::string name, ClockId clock,
                                       Fifo<PropertyLine>& input, Fifo<PropertyWrite>& output,
                                       PipelineTiming timing)
    : Component(std::move(name), clock), input_(input), output_(output), pipeline_(timing) {
  if (input.clock_id() != clock || output.clock_id() != clock) {
    throw std::invalid_argument("write-indexer port clock mismatch");
  }
}

void LittleWriteIndexer::begin(std::uint32_t lines) {
  if (active_ || !pipeline_.drained() || !input_.empty() || !output_.empty()) {
    throw std::logic_error("write indexer restart requires drained queues");
  }
  expected_ = lines;
  indexed_ = 0;
  active_ = true;
}

void LittleWriteIndexer::evaluate(const CycleContext& context) {
  stage_line_ = stage_end_ = false;
  if (!active_) return;
  if (const auto* packet = pipeline_.ready(context.domain_cycle)) {
    if (output_.try_push(*packet)) pipeline_.stage_retire();
    else pipeline_.output_stall();
  }
  if (indexed_ < expected_ && !input_.empty() && pipeline_.can_accept(context.domain_cycle)) {
    PropertyLine data;
    if (!input_.try_pop(data)) throw std::logic_error("write-indexer input ownership");
    pipeline_.stage_accept({data, indexed_, false}, context.domain_cycle);
    stage_line_ = true;
  }
  if (indexed_ == expected_ && pipeline_.drained()) {
    stage_end_ = output_.try_push({{}, 0, true});
  }
}

void LittleWriteIndexer::commit(const CycleContext& context) {
  if (stage_line_) ++indexed_;
  if (stage_end_) active_ = false;
  pipeline_.commit(context.domain_cycle);
}

}  // namespace spine::sim::original_regraph
