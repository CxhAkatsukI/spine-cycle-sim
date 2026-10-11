#include <algorithm>
#include <array>
#include <functional>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#include "spine_sim/original_regraph/property_writer.hpp"
#include "spine_sim/original_regraph/sssp_apply.hpp"
#include "spine_sim/original_regraph/udf.hpp"
#include "memory_fixture.hpp"

namespace {
namespace rg = spine::sim::original_regraph;
using namespace spine::sim;
using original_regraph_memory_test::MemoryFixture;
using original_regraph_memory_test::MemoryLink;

constexpr std::uint64_t kOldAddress = 1024;
constexpr std::uint64_t kNewAddress = 1u << 20;
constexpr auto A = rg::kSsspActive;
constexpr auto I = rg::kSsspInfinity;
constexpr rg::PropertyLine kOld{
    I, A | 10, A | 10, A | 10, A, I, A | I, 5,
    10, A | 1, A | 100, 0, 100, A | (I - 1), 1, A | 31};
constexpr rg::PropertyLine kGathered{
    A | 7, A | 10, A | 11, 0, A, 7, A | I, A,
    9, A, A | 99, A | 1, A | 100, A | (I - 2), A | I, A | 30};
constexpr rg::PropertyLine kExpected{
    A | 7, 10, 10, 10, 0, I, I, A,
    10, A, A | 99, 0, 100, A | (I - 2), 1, A | 30};

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

template <typename Error, typename Action>
void rejects(Action action, const std::string& diagnostic) {
  try { action(); }
  catch (const Error& error) {
    require(std::string{error.what()}.find(diagnostic) != std::string::npos,
            "unexpected rejection: " + std::string{error.what()});
    return;
  }
  throw std::runtime_error("missing rejection: " + diagnostic);
}

std::vector<std::uint8_t> encode(const rg::PropertyLine& line) {
  std::vector<std::uint8_t> bytes;
  for (auto word : line) {
    for (unsigned byte = 0; byte < 4; ++byte) bytes.push_back((word >> (8 * byte)) & 255u);
  }
  return bytes;
}

std::uint32_t oracle(std::uint32_t update, std::uint32_t old) {
  const auto distance = old & rg::kSsspValueMask;
  if ((update & A) != 0 && (update & rg::kSsspValueMask) < distance) return update;
  return distance;
}

struct ManualOptions {
  std::size_t depth{8};
  std::size_t credits{rg::kApplyLineCredits};
  rg::PipelineTiming timing{rg::kApplyPostReadTiming};
  std::uint64_t address{kOldAddress};
  std::uint64_t bytes{256};
  bool reverse{};
};

struct ManualApply {
  explicit ManualApply(ManualOptions options = {}) : memory(options.depth, 4) {
    requests = memory.queue<AxiRequest>("old.requests");
    responses = memory.queue<AxiResponse>("old.responses");
    input = memory.queue<rg::PropertyWrite>("gathered");
    output = memory.queue<rg::PropertyWrite>("applied");
    apply = memory.make<rg::SsspApply>("sssp_apply", memory.clock,
        rg::TransactionPort{*requests, *responses}, *input, *output,
        options.address, options.bytes, options.timing, options.credits);
    memory.register_components(options.reverse);
  }

  void until(const std::function<bool()>& ready) {
    memory.scheduler.run_until(ready, 1000);
  }

  template <typename T>
  void push(Fifo<T>& queue, T value) {
    until([&] { return !queue.full(); });
    require(queue.try_push(std::move(value)), "test producer lost FIFO ownership");
    memory.scheduler.step();
  }

  template <typename T>
  T take(Fifo<T>& queue) {
    until([&] { return !queue.empty(); });
    T value;
    require(queue.try_pop(value), "test consumer lost FIFO ownership");
    memory.scheduler.step();
    return value;
  }

  void respond(const AxiRequest& request, const rg::PropertyLine& old) {
    push(*responses, AxiResponse{.transaction_id = request.transaction_id,
        .operation = MemoryOperation::kRead, .success = true, .read_data = encode(old)});
  }

  MemoryFixture memory;
  Fifo<AxiRequest>* requests{};
  Fifo<AxiResponse>* responses{};
  Fifo<rg::PropertyWrite>* input{};
  Fifo<rg::PropertyWrite>* output{};
  rg::SsspApply* apply{};
};

std::vector<std::uint64_t> test_full_line_restart(bool reverse) {
  ManualApply path({.reverse = reverse});
  path.apply->begin(1);
  path.push(*path.input, rg::PropertyWrite{kGathered, 2, false});
  path.push(*path.input, rg::PropertyWrite{{}, 0, true});
  const auto request = path.take(*path.requests);
  require(request.operation == MemoryOperation::kRead && request.address == kOldAddress + 128 &&
          request.bytes == 64 && !request.stream_read_beats && !request.target_channel &&
          request.write_data.empty(), "old-state read did not use the indexed complete line");
  path.memory.scheduler.run_events(32);
  require(!path.apply->finished() && path.output->empty() &&
          path.apply->counters().old_state_responses == 0, "Apply bypassed the read acknowledgement");
  rejects<std::logic_error>([&] { path.apply->begin(1); }, "restart requires drained");
  path.respond(request, kOld);
  const auto result = path.take(*path.output);
  require(!result.end && result.index == 2 && result.data == kExpected,
          "full 16-word SSSP Apply result differs from literal oracle");
  require(path.apply->finished() && !path.output->empty(), "terminator was not emitted after arithmetic drain");
  rejects<std::logic_error>([&] { path.apply->begin(0); }, "restart requires drained");
  require(path.take(*path.output).end && path.memory.drained(), "terminal or queues did not drain");
  const auto first = path.apply->counters();
  require(first.lines == 1 && first.old_state_responses == 1 && first.old_state_bytes == 64 &&
          first.active_vertices == 6 && first.input_terminators == 1 && first.output_terminators == 1,
          "SSSP Apply line/read/activation/terminal counters differ");

  path.apply->begin(1, kOldAddress + 4096);
  path.push(*path.input, rg::PropertyWrite{kGathered, 2, false});
  const auto next = path.take(*path.requests);
  require(next.transaction_id > request.transaction_id && next.address == kOldAddress + 4096 + 128,
          "restart reused a transaction or ignored relocated old state");
  path.respond(next, kExpected);
  auto cleared = kExpected;
  for (auto& word : cleared) word &= rg::kSsspValueMask;
  require(path.take(*path.output).data == cleared, "equal updates did not clear all stale active bits");
  path.memory.scheduler.run_events(8);
  require(!path.apply->finished() && path.output->empty(), "missing input terminal was silently synthesized");
  path.push(*path.input, rg::PropertyWrite{{}, 0, true});
  require(path.take(*path.output).end && path.apply->finished(), "restart terminal missing");
  require(path.apply->counters().active_vertices == first.active_vertices,
          "stale old-state active bits counted as new activations");

  path.apply->begin(0);
  path.push(*path.input, rg::PropertyWrite{{}, 0, true});
  require(path.take(*path.output).end && path.apply->finished() && path.memory.drained(),
          "empty round did not terminate without reads");
  require(path.apply->counters().lines == 2 && path.apply->counters().old_state_bytes == 128 &&
          path.apply->counters().input_terminators == 3 && path.apply->counters().output_terminators == 3,
          "restart counters did not conserve work");
  return {path.memory.scheduler.clock(path.memory.clock).completed_cycles,
          path.apply->counters().active_vertices, path.apply->counters().max_live_lines,
          path.apply->pipeline().accepted, path.apply->pipeline().completed,
          path.apply->pipeline().output_stalls};
}

void test_out_of_order_and_pipeline_pressure() {
  ManualApply path({.depth = 1, .credits = 2, .timing = {5, 2, 1}});
  path.apply->begin(2);
  path.push(*path.input, rg::PropertyWrite{kGathered, 3, false});
  const auto first = path.take(*path.requests);
  path.push(*path.input, rg::PropertyWrite{kGathered, 1, false});
  const auto second = path.take(*path.requests);
  path.push(*path.input, rg::PropertyWrite{{}, 0, true});
  rg::PropertyLine zero{};
  path.respond(second, zero);
  path.memory.scheduler.run_events(8);
  require(path.output->empty() && path.apply->counters().old_state_responses == 1 &&
          !path.apply->finished(), "out-of-order read response reordered Apply output");
  path.respond(first, kOld);
  path.memory.scheduler.run_events(32);
  require(!path.apply->finished() && path.apply->pipeline().output_stalls &&
          path.apply->pipeline().capacity_stalls && path.apply->pipeline().max_inflight == 1 &&
          path.apply->counters().max_live_lines <= 2,
          "finite pipeline/output backpressure was bypassed");
  const auto a = path.take(*path.output);
  const auto b = path.take(*path.output);
  require(!a.end && a.index == 3 && a.data == kExpected &&
          !b.end && b.index == 1 && b.data == zero, "out-of-order responses changed ordered full-line results");
  require(path.take(*path.output).end && path.apply->finished() && path.memory.drained(),
          "pressure run terminated before complete drain");
  require(path.apply->counters().old_state_bytes == 128 && path.apply->counters().active_vertices == 6,
          "pipeline stalls duplicated reads or active counts");
}

void test_request_backpressure() {
  ManualApply path({.depth = 1});
  path.apply->begin(1);
  path.push(*path.requests, AxiRequest{.transaction_id = 999, .operation = MemoryOperation::kRead,
      .address = 0, .bytes = 64, .stream_read_beats = false, .target_channel = std::nullopt, .write_data = {}});
  path.push(*path.input, rg::PropertyWrite{kGathered, 0, false});
  path.memory.scheduler.run_events(8);
  require(path.apply->counters().request_stalls && path.apply->counters().lines == 0 &&
          !path.input->empty(), "full old-state request FIFO consumed an unissued input");
  require(path.take(*path.requests).transaction_id == 999, "request blocker changed");
  const auto request = path.take(*path.requests);
  path.respond(request, kOld);
  path.push(*path.input, rg::PropertyWrite{{}, 0, true});
  require(path.take(*path.output).data == kExpected && path.take(*path.output).end && path.memory.drained(),
          "request backpressure changed result or drain");
}

void test_rejections() {
  const auto invalid_input = [](std::uint32_t lines, rg::PropertyWrite packet, const std::string& message) {
    ManualApply path;
    path.apply->begin(lines);
    path.push(*path.input, packet);
    rejects<std::logic_error>([&] { path.memory.scheduler.step(); }, message);
  };
  invalid_input(1, {{}, 0, true}, "terminated before expected extent");
  invalid_input(0, {kGathered, 0, false}, "excess SSSP Apply data");
  {
    ManualApply path;
    path.apply->begin(1);
    path.push(*path.input, rg::PropertyWrite{kGathered, 4, false});
    rejects<std::out_of_range>([&] { path.memory.scheduler.step(); }, "old-state index exceeds allocation");
  }
  for (const bool trailing_end : {false, true}) {
    ManualApply path;
    path.apply->begin(0);
    path.push(*path.input, rg::PropertyWrite{{}, 0, true});
    path.push(*path.input, rg::PropertyWrite{{}, 0, trailing_end});
    rejects<std::logic_error>([&] { path.memory.scheduler.step(); }, "input after terminator");
  }
  for (unsigned bad = 0; bad < 4; ++bad) {
    ManualApply path;
    path.apply->begin(1);
    path.push(*path.input, rg::PropertyWrite{kGathered, 0, false});
    const auto request = path.take(*path.requests);
    AxiResponse response{.transaction_id = request.transaction_id,
        .operation = MemoryOperation::kRead, .success = true, .read_data = encode(kOld)};
    if (bad == 0) response.transaction_id = 999;
    if (bad == 1) response.operation = MemoryOperation::kWrite;
    if (bad == 2) response.success = false;
    if (bad == 3) response.read_data.pop_back();
    path.push(*path.responses, response);
    rejects<std::logic_error>([&] { path.memory.scheduler.step(); },
        bad == 0 ? "unexpected SSSP Apply old-state response" : "read parent acknowledgement mismatch");
  }
  {
    ManualApply path;
    path.apply->begin(2);
    path.push(*path.input, rg::PropertyWrite{kGathered, 0, false});
    const auto first = path.take(*path.requests);
    path.push(*path.input, rg::PropertyWrite{kGathered, 1, false});
    const auto second = path.take(*path.requests);
    require(first.transaction_id != second.transaction_id, "duplicate request ID");
    path.respond(second, kOld);
    path.memory.scheduler.step();
    path.respond(second, kOld);
    rejects<std::logic_error>([&] { path.memory.scheduler.step(); }, "unexpected SSSP Apply old-state response");
  }
  for (const auto options : {ManualOptions{.credits = 0}, ManualOptions{.address = 1},
       ManualOptions{.bytes = 0}, ManualOptions{.bytes = 65},
       ManualOptions{.address = std::numeric_limits<std::uint64_t>::max() - 63, .bytes = 64}}) {
    rejects<std::invalid_argument>([&] { ManualApply path(options); }, "invalid SSSP Apply");
  }
  rejects<std::invalid_argument>([] { ManualApply path({.timing = {0, 1, 1}}); }, "pipeline timing");
  ManualApply path;
  rejects<std::invalid_argument>([&] { path.apply->begin(0, 1); }, "invalid relocated");
  rejects<std::invalid_argument>([&] {
    path.apply->begin(0, std::numeric_limits<std::uint64_t>::max() - 63);
  }, "invalid relocated");
  path.push(*path.requests, AxiRequest{});
  rejects<std::logic_error>([&] { path.apply->begin(0); }, "restart requires drained");
}

struct ResidentOptions {
  std::size_t depth{8};
  std::size_t apply_credits{rg::kApplyLineCredits};
  std::size_t writer_credits{rg::kWriterLineCredits};
  bool reverse{};
};

struct Observation {
  std::uint64_t cycles{}, active{}, read_bytes{}, write_bytes{}, acknowledgements{};
  std::uint64_t credit_stalls{}, writer_credit_stalls{}, output_stalls{};
  std::size_t max_live{}, max_pipeline{};
  bool waited_for_ack{};
  std::vector<std::uint32_t> values;
  bool operator==(const Observation&) const = default;
};

class ResidentApply {
 public:
  explicit ResidentApply(ResidentOptions options = {}) : memory(options.depth, 16), options(options) {
    input = memory.queue<rg::PropertyWrite>("resident.gathered");
    output = memory.queue<rg::PropertyWrite>("resident.applied");
    old = memory.port("old_state_axi", 100, 30, 2, 2);
    apply = memory.make<rg::SsspApply>("resident.apply", memory.clock,
        rg::TransactionPort{*old.requests, *old.responses}, *input, *output,
        kOldAddress, kLines * 64ull, rg::kApplyPostReadTiming, options.apply_credits);
    std::vector<rg::WriteTarget> targets;
    for (unsigned replica = 0; replica < 4; ++replica) {
      auto port = memory.port("replica" + std::to_string(replica), 200 + replica, 1 + replica * 2, 2, 2);
      targets.push_back({{*port.requests, *port.responses}, kNewAddress, kLines * 64ull});
      replicas.push_back(port);
    }
    writer = memory.make<rg::PropertyBroadcastWriter>("resident.writer", memory.clock,
        *output, targets, options.writer_credits);
    memory.register_components(options.reverse);
  }

  Observation run() {
    const auto before_apply = apply->counters();
    const auto before_writer = writer->counters();
    const auto before_pipe = apply->pipeline();
    const auto before_traffic = memory.backend->traffic_stats();
    std::vector<std::uint8_t> old_bytes;
    std::vector<std::uint32_t> expected;
    for (unsigned line = 0; line < kLines; ++line) {
      const auto bytes = encode(rotated(kOld, line));
      old_bytes.insert(old_bytes.end(), bytes.begin(), bytes.end());
      const auto gathered = rotated(kGathered, line);
      const auto old_line = rotated(kOld, line);
      for (unsigned word = 0; word < 16; ++word) expected.push_back(oracle(gathered[word], old_line[word]));
    }
    memory.backend->initialize_payload(30, kOldAddress, old_bytes);
    for (unsigned replica = 0; replica < 4; ++replica) {
      memory.backend->fill_payload(1 + replica * 2, kNewAddress, kLines * 64ull + 64, 0xa5);
    }
    apply->begin(kLines);
    writer->begin(kLines);
    Observation observed;
    unsigned sent = 0;
    bool sent_end = false;
    for (unsigned cycle = 0; cycle < 100000; ++cycle) {
      if (sent < kLines) {
        if (input->try_push({rotated(kGathered, sent), sent, false})) ++sent;
      } else if (!sent_end) sent_end = input->try_push({{}, 0, true});
      memory.scheduler.step();
      if (apply->finished() && !writer->finished() &&
          writer->counters().acknowledgements < writer->counters().write_requests) {
        observed.waited_for_ack = true;
      }
      if (apply->finished() && writer->finished() && memory.drained()) {
        observed.cycles = cycle + 1;
        break;
      }
    }
    require(observed.cycles != 0 && sent_end, "resident SSSP Apply/writer timeout");
    const auto& ac = apply->counters();
    const auto& wc = writer->counters();
    observed.active = ac.active_vertices - before_apply.active_vertices;
    observed.read_bytes = ac.old_state_bytes - before_apply.old_state_bytes;
    observed.write_bytes = wc.write_bytes - before_writer.write_bytes;
    observed.acknowledgements = wc.acknowledgements - before_writer.acknowledgements;
    observed.credit_stalls = ac.credit_stalls - before_apply.credit_stalls;
    observed.writer_credit_stalls = wc.credit_stalls - before_writer.credit_stalls;
    observed.output_stalls = apply->pipeline().output_stalls - before_pipe.output_stalls;
    observed.max_live = ac.max_live_lines;
    observed.max_pipeline = apply->pipeline().max_inflight;
    const auto traffic = subtract_memory_traffic(memory.backend->traffic_stats(), before_traffic);
    require(ac.lines - before_apply.lines == kLines &&
            ac.old_state_responses - before_apply.old_state_responses == kLines &&
            observed.active == kLines * 6 && observed.read_bytes == kLines * 64ull &&
            observed.write_bytes == kLines * 64ull * 4 && observed.acknowledgements == kLines * 4 &&
            wc.write_requests - before_writer.write_requests == observed.acknowledgements &&
            ac.input_terminators - before_apply.input_terminators == 1 &&
            ac.output_terminators - before_apply.output_terminators == 1 &&
            wc.input_terminators - before_writer.input_terminators == 1 &&
            apply->pipeline().accepted - before_pipe.accepted == kLines &&
            apply->pipeline().completed - before_pipe.completed == kLines &&
            observed.max_live <= options.apply_credits &&
            wc.max_live_lines <= options.writer_credits && observed.max_pipeline <= rg::kApplyPostReadTiming.capacity &&
            traffic.reads.bytes == observed.read_bytes && traffic.writes.bytes == observed.write_bytes,
            "resident line/read/active/credit/terminal/replica traffic conservation failed");
    for (unsigned replica = 0; replica < replicas.size(); ++replica) {
      const auto bytes = memory.backend->inspect_payload(1 + replica * 2, kNewAddress, kLines * 64ull + 64);
      for (unsigned vertex = 0; vertex < expected.size(); ++vertex) {
        std::uint32_t word = 0;
        for (unsigned byte = 0; byte < 4; ++byte) word |= std::uint32_t{bytes[vertex * 4 + byte]} << (8 * byte);
        require(word == expected[vertex], "resident output replica differs from independent SSSP oracle");
        if (replica == 0) observed.values.push_back(word);
      }
      require(std::all_of(bytes.end() - 64, bytes.end(), [](auto byte) { return byte == 0xa5; }),
              "SSSP writer changed allocation guard");
      check_axi(replicas[replica]);
    }
    check_axi(old);
    require(memory.backend->inspect_payload(30, kOldAddress, old_bytes.size()) == old_bytes,
            "SSSP Apply mutated old-state allocation");
    return observed;
  }

 private:
  static constexpr unsigned kLines = 64;
  static rg::PropertyLine rotated(const rg::PropertyLine& source, unsigned offset) {
    rg::PropertyLine result;
    for (unsigned word = 0; word < 16; ++word) result[word] = source[(word + offset) % 16];
    return result;
  }
  static void check_axi(const MemoryLink& port) {
    const auto& stats = port.master->stats();
    require(port.master->idle() && stats.requests_accepted == stats.requests_completed &&
            stats.beats_issued == stats.beats_completed && stats.max_outstanding_bursts <= 2,
            "resident AXI request/beat/credit conservation failed");
  }
  MemoryFixture memory;
  ResidentOptions options;
  Fifo<rg::PropertyWrite>* input{};
  Fifo<rg::PropertyWrite>* output{};
  MemoryLink old;
  std::vector<MemoryLink> replicas;
  rg::SsspApply* apply{};
  rg::PropertyBroadcastWriter* writer{};
};

void test_resident_replicas() {
  ResidentApply normal;
  const auto baseline = normal.run();
  require(normal.run() == baseline, "resident restart changed state/cycles/counters");
  ResidentApply reversed({.reverse = true});
  require(reversed.run() == baseline, "reverse registration changed state/cycles/counters");
  ResidentApply narrow({.depth = 1, .apply_credits = 1, .writer_credits = 1});
  const auto pressured = narrow.run();
  require(pressured.values == baseline.values && pressured.cycles > baseline.cycles &&
          pressured.credit_stalls && pressured.max_live == 1, "one Apply credit bypassed backpressure");
  ResidentApply write_narrow({.depth = 1, .writer_credits = 1});
  const auto write_pressure = write_narrow.run();
  require(write_pressure.values == baseline.values && write_pressure.cycles > baseline.cycles &&
          write_pressure.writer_credit_stalls && write_pressure.output_stalls,
          "replica writer pressure did not reach Apply");
  require(baseline.waited_for_ack && pressured.waited_for_ack && write_pressure.waited_for_ack,
          "resident completion did not wait for replica acknowledgement tail");
}
}  // namespace

int main() {
  try {
    require(test_full_line_restart(false) == test_full_line_restart(true),
            "manual reverse registration changed protocol timing/counters");
    test_out_of_order_and_pipeline_pressure();
    test_request_backpressure();
    test_rejections();
    test_resident_replicas();
    std::cout << "SSSP Apply checks passed: full lines, strict min, stale-active clear, finite reads, "
                 "pipeline/credit pressure, terminals, restart, reverse registration, replica acks\n"
                 "Timing assumption: kApplyPostReadTiming inherited from PR; not SSSP HLS calibrated\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
