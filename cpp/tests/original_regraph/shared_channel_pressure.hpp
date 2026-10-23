#pragma once

#include "state_support.hpp"

namespace original_regraph_pressure_test {
using namespace spine::sim;
using original_regraph_state_test::require;

inline std::array<std::uint64_t, 4> run(bool reverse) {
  original_regraph_memory_test::MemoryFixture memory;
  const auto reader = memory.port("pressure.read", 401, 1);
  const auto writer = memory.port("pressure.write", 402, 1);
  constexpr std::size_t bytes = 256 * 1024;
  constexpr std::uint64_t destination = 1 << 20;
  std::vector<std::uint8_t> input(bytes), output(bytes);
  for (std::size_t i = 0; i < bytes; ++i) {
    input[i] = static_cast<std::uint8_t>(i * 17 + i / 64);
    output[i] = static_cast<std::uint8_t>(i * 7 + 11);
  }
  memory.backend->initialize_payload(1, 0, input);
  memory.backend->fill_payload(1, destination, bytes + 64, 0xa5);
  memory.register_components(reverse);
  require(reader.requests->try_push({.transaction_id = 1, .address = 0, .bytes = bytes,
      .stream_read_beats = true, .write_data = {}}), "pressure read enqueue failed");
  require(writer.requests->try_push({.transaction_id = 2, .operation = MemoryOperation::kWrite,
      .address = destination, .bytes = bytes, .write_data = output}), "pressure write enqueue failed");
  std::size_t received = 0;
  bool read_ack = false, write_ack = false;
  std::uint64_t end = 0;
  for (std::uint64_t cycle = 0; cycle < 1000000; ++cycle) {
    AxiReadBeatResponse beat;
    if (reader.beats->try_pop(beat)) {
      require(received < bytes && beat.success && beat.transaction_id == 1 &&
          beat.address == received && beat.parent_offset == received &&
          beat.last == (received + 64 == bytes) && beat.read_data.size() == 64 &&
          std::equal(beat.read_data.begin(), beat.read_data.end(), input.begin() + received),
          "pressure read beat differs from resident payload");
      received += 64;
    }
    AxiResponse response;
    if (reader.responses->try_pop(response)) {
      require(!read_ack && response.success && response.transaction_id == 1 &&
          response.read_data == input, "pressure read acknowledgement differs");
      read_ack = true;
    }
    if (writer.responses->try_pop(response)) {
      require(!write_ack && response.success && response.transaction_id == 2,
              "pressure write acknowledgement differs");
      write_ack = true;
    }
    memory.scheduler.step();
    if (read_ack && write_ack && received == bytes && memory.drained()) {
      end = cycle + 1;
      break;
    }
  }
  require(end != 0, "shared-channel pressure test timed out");
  const auto payload = memory.backend->inspect_payload(1, destination, bytes + 64);
  require(std::equal(output.begin(), output.end(), payload.begin()) &&
      std::all_of(payload.end() - 64, payload.end(), [](auto b) { return b == 0xa5; }),
      "shared-channel pressure write or guard differs");
  const auto traffic = memory.backend->traffic_stats();
  const auto* arbitration = memory.backend->arbitration_stats();
  require(traffic.reads.bytes == bytes && traffic.writes.bytes == bytes && arbitration &&
      arbitration->contended_cycles > 0 && arbitration->unique_intents == arbitration->grants &&
      arbitration->grants == arbitration->consumed_grants,
      "shared-channel pressure did not contend or conserve requests");
  return {end, traffic.reads.bytes, traffic.writes.bytes, arbitration->contended_cycles};
}
} // namespace original_regraph_pressure_test
