#include "spine_sim/algorithm_pipeline.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace spine::sim {

AlgorithmPipeline::AlgorithmPipeline(std::string name, ClockId clock_id,
                                     GraphAlgorithmPolicy policy,
                                     AlgorithmPipelineConfig config,
                                     AlgorithmPipelinePorts ports)
    : Component(std::move(name), clock_id),
      policy_(std::move(policy)),
      config_(config),
      ports_(ports),
      source_map_{
          .kind = AlgorithmPipelineStage::kSourceMap,
          .requests = ports_.source_requests,
          .responses = ports_.source_responses,
          .config = config_.source_map,
          .completions = {},
          .staged_request = std::nullopt,
          .last_accept_cycle = std::nullopt,
          .staged_retire = false,
      },
      edge_map_{
          .kind = AlgorithmPipelineStage::kEdgeMap,
          .requests = ports_.edge_requests,
          .responses = ports_.edge_responses,
          .config = config_.edge_map,
          .completions = {},
          .staged_request = std::nullopt,
          .last_accept_cycle = std::nullopt,
          .staged_retire = false,
      },
      reduce_{
          .kind = AlgorithmPipelineStage::kReduce,
          .requests = ports_.reduce_requests,
          .responses = ports_.reduce_responses,
          .config = config_.reduce,
          .completions = {},
          .staged_request = std::nullopt,
          .last_accept_cycle = std::nullopt,
          .staged_retire = false,
      },
      apply_{
          .kind = AlgorithmPipelineStage::kApply,
          .requests = ports_.apply_requests,
          .responses = ports_.apply_responses,
          .config = config_.apply,
          .completions = {},
          .staged_request = std::nullopt,
          .last_accept_cycle = std::nullopt,
          .staged_retire = false,
      } {
  validate_stage(source_map_);
  validate_stage(edge_map_);
  validate_stage(reduce_);
  validate_stage(apply_);
}

void AlgorithmPipeline::validate_stage(const StageState &stage) const {
  if (stage.requests == nullptr || stage.responses == nullptr ||
      stage.requests->clock_id() != clock_id() ||
      stage.responses->clock_id() != clock_id() ||
      stage.config.latency_cycles == 0 ||
      stage.config.initiation_interval == 0 || stage.config.capacity == 0) {
    throw std::invalid_argument("invalid algorithm pipeline stage");
  }
}

bool AlgorithmPipeline::drained() const noexcept {
  const auto empty = [](const StageState &stage) {
    return stage.completions.empty() && !stage.staged_request.has_value() &&
           !stage.staged_retire;
  };
  return empty(source_map_) && empty(edge_map_) && empty(reduce_) &&
         empty(apply_);
}

void AlgorithmPipeline::evaluate_stage(
    StageState &stage, AlgorithmPipelineStageCounters &counters,
    const CycleContext &context) {
  stage.staged_request.reset();
  stage.staged_retire = false;
  if (!stage.completions.empty() &&
      stage.completions.front().due_cycle <= context.domain_cycle) {
    if (stage.responses->try_push(stage.completions.front().response)) {
      stage.staged_retire = true;
    } else {
      ++counters.output_backpressure_stalls;
    }
  }

  const AlgorithmPipelineRequest *request = stage.requests->front();
  if (request == nullptr) {
    return;
  }
  if (request->stage != stage.kind) {
    throw std::logic_error("algorithm request entered the wrong pipeline stage");
  }
  if (stage.completions.size() >= stage.config.capacity) {
    ++counters.capacity_stalls;
    return;
  }
  if (stage.last_accept_cycle.has_value() &&
      context.domain_cycle <
          *stage.last_accept_cycle + stage.config.initiation_interval) {
    ++counters.initiation_interval_stalls;
    return;
  }
  AlgorithmPipelineRequest staged;
  if (stage.requests->try_pop(staged)) {
    stage.staged_request = staged;
  }
}

void AlgorithmPipeline::commit_stage(
    StageState &stage, AlgorithmPipelineStageCounters &counters,
    const CycleContext &context) {
  if (stage.staged_retire) {
    stage.completions.pop_front();
    stage.staged_retire = false;
    ++counters.completed;
  }
  if (!stage.staged_request.has_value()) {
    return;
  }
  stage.completions.push_back(Completion{
      .due_cycle = context.domain_cycle + stage.config.latency_cycles,
      .response = execute(*stage.staged_request),
  });
  stage.staged_request.reset();
  stage.last_accept_cycle = context.domain_cycle;
  ++counters.accepted;
  counters.max_inflight =
      std::max(counters.max_inflight, stage.completions.size());
}

AlgorithmPipelineResponse AlgorithmPipeline::execute(
    const AlgorithmPipelineRequest &request) const {
  AlgorithmPipelineResponse response{
      .stage = request.stage,
      .transaction_id = request.transaction_id,
      .source = {},
      .mapped = 0,
      .reduced = 0,
      .applied = {},
  };
  switch (request.stage) {
    case AlgorithmPipelineStage::kSourceMap:
      response.source = policy_.prepare_source(request.state,
                                               request.out_degree);
      return response;
    case AlgorithmPipelineStage::kEdgeMap:
      response.mapped =
          policy_.map_edge(request.source_payload, request.edge_weight);
      return response;
    case AlgorithmPipelineStage::kReduce:
      response.reduced = policy_.reduce(request.current, request.candidate);
      return response;
    case AlgorithmPipelineStage::kApply:
      response.applied =
          policy_.apply(request.state, request.reduced, request.context);
      return response;
  }
  throw std::logic_error("unknown algorithm pipeline stage");
}

void AlgorithmPipeline::evaluate(const CycleContext &context) {
  evaluate_stage(source_map_, counters_.source_map, context);
  evaluate_stage(edge_map_, counters_.edge_map, context);
  evaluate_stage(reduce_, counters_.reduce, context);
  evaluate_stage(apply_, counters_.apply, context);
}

void AlgorithmPipeline::commit(const CycleContext &context) {
  commit_stage(source_map_, counters_.source_map, context);
  commit_stage(edge_map_, counters_.edge_map, context);
  commit_stage(reduce_, counters_.reduce, context);
  commit_stage(apply_, counters_.apply, context);
}

}  // namespace spine::sim
