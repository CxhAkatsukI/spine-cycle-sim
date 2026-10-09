#pragma once

#include "state_support.hpp"

namespace original_regraph_state_test {

struct Observation {
  std::uint64_t cycles{};
  std::uint64_t degree_bytes{};
  std::uint64_t write_bytes{};
  std::uint64_t degree_requests{};
  std::uint64_t write_requests{};
  std::uint64_t write_acknowledgements{};
  std::uint64_t apply_credit_stalls{};
  std::uint64_t writer_credit_stalls{};
  std::uint64_t apply_output_stalls{};
  std::uint64_t max_apply_live{};
  std::uint64_t max_writer_live{};
  bool waited_for_write_ack{};
  std::vector<std::uint32_t> values;
  bool operator==(const Observation&) const = default;
};

class StateWiring {
 public:
  explicit StateWiring(std::uint32_t lines = 4096, Options options = {})
      : memory(options.fifo_depth, options.memory_latency),
        input(memory.queue<rg::PropertyLine>("state.input")), state(memory, *input, lines, options) {
    memory.register_components(options.reverse_registration);
  }

  Observation run(const char* id, unsigned case_index, std::uint64_t max_cycles = 1000000) {
    const auto before_apply = state.apply->counters();
    const auto before_writer = state.writer->counters();
    const auto before_pipe = state.apply->pipeline();
    const auto before_memory = memory.backend->traffic_stats();
    state.begin(kArguments.at(case_index));
    Observation observed;
    std::vector<std::uint32_t> expected;
    for (unsigned vertex = 0; vertex < state.lines * 16; ++vertex) {
      expected.push_back(oracle(fixture_sum(case_index, vertex), kDegrees[vertex % 8], kArguments.at(case_index)));
    }
    unsigned sent = 0;
    bool completed = false;
    for (std::uint64_t cycle = 0; cycle < max_cycles; ++cycle) {
      if (sent < state.lines && !input->full()) {
        rg::PropertyLine line;
        for (unsigned word = 0; word < 16; ++word) line[word] = fixture_sum(case_index, sent * 16 + word);
        require(input->try_push(line), "state producer ownership");
        ++sent;
      }
      memory.scheduler.step();
      if (state.apply->finished() && !state.writer->finished()) observed.waited_for_write_ack = true;
      if (state.finished() && memory.drained()) {
        observed.cycles = cycle + 1;
        completed = true;
        break;
      }
    }
    require(completed, "state network timed out");
    const auto& apply = state.apply->counters();
    const auto& writer = state.writer->counters();
    observed.degree_bytes = apply.degree_bytes - before_apply.degree_bytes;
    observed.write_bytes = writer.write_bytes - before_writer.write_bytes;
    observed.degree_requests = apply.lines - before_apply.lines;
    observed.write_requests = writer.write_requests - before_writer.write_requests;
    observed.write_acknowledgements = writer.acknowledgements - before_writer.acknowledgements;
    observed.apply_credit_stalls = apply.credit_stalls - before_apply.credit_stalls;
    observed.writer_credit_stalls = writer.credit_stalls - before_writer.credit_stalls;
    observed.apply_output_stalls = state.apply->pipeline().output_stalls - before_pipe.output_stalls;
    observed.max_apply_live = apply.max_live_lines;
    observed.max_writer_live = writer.max_live_lines;
    const auto traffic = spine::sim::subtract_memory_traffic(memory.backend->traffic_stats(), before_memory);
    require(observed.degree_bytes == state.lines * 64ull && observed.degree_requests == state.lines &&
            observed.write_bytes == state.lines * 64ull * state.options.replicas &&
            observed.write_requests == state.lines * state.options.replicas &&
            observed.write_requests == observed.write_acknowledgements &&
            apply.input_terminators - before_apply.input_terminators == 1 &&
            apply.output_terminators - before_apply.output_terminators == 1 &&
            writer.input_terminators - before_writer.input_terminators == 1 &&
            traffic.reads.bytes == observed.degree_bytes && traffic.writes.bytes == observed.write_bytes &&
            observed.max_apply_live <= state.options.apply_credits &&
            observed.max_writer_live <= state.options.writer_credits,
            "state request/byte/terminator/credit conservation failed");
    for (const auto& port : state.writers) check_axi(port);
    check_axi(state.degree);
    observed.values = state.inspect_and_check(expected);
    emit(id, case_index, observed);
    return observed;
  }

  MemoryFixture memory;
  spine::sim::Fifo<rg::PropertyLine>* input;
  StatePath state;

 private:
  void check_axi(const MemoryLink& port) const {
    const auto& stats = port.master->stats();
    require(stats.requests_accepted == stats.requests_completed && stats.beats_issued == stats.beats_completed &&
            stats.max_outstanding_bursts <= state.options.outstanding, "state AXI conservation failed");
  }

  void emit(const char* id, unsigned case_index, const Observation& row) const {
    std::cout << "STATE_CASE {\"id\":\"" << id << "\",\"case_index\":" << case_index
              << ",\"replicas\":" << state.options.replicas << ",\"cycles\":" << row.cycles
              << ",\"checked_words\":" << row.values.size() << ",\"degree_bytes\":" << row.degree_bytes
              << ",\"write_bytes\":" << row.write_bytes << ",\"degree_requests\":" << row.degree_requests
              << ",\"write_requests\":" << row.write_requests
              << ",\"write_acknowledgements\":" << row.write_acknowledgements
              << ",\"apply_credit_stalls\":" << row.apply_credit_stalls
              << ",\"writer_credit_stalls\":" << row.writer_credit_stalls
              << ",\"apply_output_stalls\":" << row.apply_output_stalls
              << ",\"max_apply_live\":" << row.max_apply_live << ",\"max_writer_live\":" << row.max_writer_live
              << ",\"waited_for_write_ack\":" << (row.waited_for_write_ack ? "true" : "false") << "}\n";
  }
};

}  // namespace original_regraph_state_test
