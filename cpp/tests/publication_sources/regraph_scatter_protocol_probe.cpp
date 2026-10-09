#include "probe_support.hpp"
#include "acc_data_types.h"
#include "acc_scatter.h"
#include "hbm_wrapper.h"

#include <deque>
#include <optional>

namespace {
struct Watchdog {};

ap_uint<512> source_line(unsigned address) {
  ap_uint<512> result = 0;
  for (unsigned word = 0; word < 16; ++word) {
    result.range(word * 32 + 31, word * 32) = 17 + (address * 16 + word) % 31;
  }
  return result;
}

class Requests final : public hls::stream_delegate<sizeof(ppb_request_dt)> {
 public:
  bool read(void*) override { throw std::runtime_error("output-only requests"); }
  bool read_nb(void*) override { throw std::runtime_error("output-only requests"); }
  std::size_t size() override { return 0; }
  void write(const void* pointer) override {
    const auto value = *static_cast<const ppb_request_dt*>(pointer);
    values.push_back(value);
    pending.push_back(value);
  }
  std::vector<ppb_request_dt> values;
  std::deque<ppb_request_dt> pending;
};

// Request-dependent functional service, not a cycle simulator. Validate the
// complete generated response sequence against the original wrapper below.
class Responses final : public hls::stream_delegate<sizeof(ppb_response_dt)> {
 public:
  explicit Responses(Requests& requests) : requests_(requests) {}
  bool read(void* pointer) override {
    require(read_nb(pointer), "blocking response had no pending request");
    return true;
  }
  bool read_nb(void* pointer) override {
    if (++polls > 10000) throw Watchdog{};
    if (!active_ && !requests_.pending.empty()) {
      active_ = requests_.pending.front();
      requests_.pending.pop_front();
      offset_ = 0;
    }
    if (!active_) return false;
    ppb_response_dt value{};
    if (active_->end_flag) {
      value.end_flag = true;
      active_.reset();
    } else {
      value.addr = active_->request_round.to_uint() * (SRC_BUFFER_SIZE / 16) + offset_;
      value.data = source_line(value.addr.to_uint());
      if (++offset_ == SRC_BUFFER_SIZE / 16) active_.reset();
    }
    *static_cast<ppb_response_dt*>(pointer) = value;
    values.push_back(value);
    return true;
  }
  void write(const void*) override { throw std::runtime_error("input-only responses"); }
  std::size_t size() override {
    if (++polls > 10000) throw Watchdog{};
    return active_ || !requests_.pending.empty() ? 1 : 0;
  }
  unsigned polls{};
  std::vector<ppb_response_dt> values;
 private:
  Requests& requests_;
  std::optional<ppb_request_dt> active_;
  unsigned offset_{};
};

unsigned check_wrapper(const Requests& requests, const Responses& responses) {
  std::vector<ap_uint<512>> properties(65536 / 16);
  for (unsigned line = 0; line < properties.size(); ++line) properties[line] = source_line(line);
  hls::stream<l_ppb_request_pkt> input;
  hls::stream<l_ppb_response_pkt> output;
  unsigned normal = 0;
  for (const auto request : requests.values) {
    l_ppb_request_pkt packet{};
    packet.data = request.request_round;
    packet.last = request.end_flag;
    normal += !request.end_flag;
    input.write(packet);
  }
  littleKernelReadMemory<0>(0, properties.data(), 1, input, output);
  require(input.empty() && output.size() == responses.values.size(), "original wrapper extent mismatch");
  for (const auto expected : responses.values) {
    const auto observed = output.read();
    require(observed.last == expected.end_flag, "original wrapper terminator mismatch");
    if (!expected.end_flag) {
      require(observed.dest == expected.addr && observed.data == expected.data,
              "original wrapper response differs from request-dependent service");
    }
  }
  require(output.empty(), "original wrapper output conservation");
  return normal;
}

void run_case(const char* id, const std::vector<unsigned>& rounds, bool expected_watchdog,
              unsigned& physical, unsigned& normals, unsigned& response_lines) {
  Requests requests;
  Responses responses(requests);
  hls::stream<ppb_request_dt> request_stream;
  hls::stream<ppb_response_dt> response_stream;
  request_stream.set_delegate(&requests);
  response_stream.set_delegate(&responses);
  hls::stream<edge_burst_dt> edges;
  hls::stream<update_set_dt> updates;
  std::vector<edge_burst_dt> fixture;
  for (unsigned round : rounds) {
    for (unsigned index = 0; index < 4; ++index) {
      edge_burst_dt burst{};
      for (unsigned lane = 0; lane < 8; ++lane) {
        burst.edges[lane].src = round * SRC_BUFFER_SIZE + index * 101 + lane * 13;
        burst.edges[lane].dst = index * 8 + lane;
      }
      fixture.push_back(burst);
    }
  }
  for (unsigned lane = 4; lane < 8; ++lane) {
    fixture.back().edges[lane].src |= 1u << 31;
    fixture.back().edges[lane].dst = 1u << 19;
  }
  for (const auto burst : fixture) edges.write(burst);
  bool watchdog = false;
  try { accScatter(request_stream, response_stream, edges, updates, fixture.size() * 8); }
  catch (const Watchdog&) { watchdog = true; }
  require(watchdog == expected_watchdog, "original Scatter protocol outcome mismatch");
  if (!watchdog) {
    std::vector<unsigned> expected_rounds{0};
    for (const auto round : rounds) {
      for (const auto needed : {round, round + 1}) {
        if (needed > expected_rounds.back()) expected_rounds.push_back(needed);
      }
    }
    require(requests.values.size() == expected_rounds.size() + 1 &&
            requests.values.back().end_flag &&
            requests.values.back().request_round == expected_rounds.back(),
            "original Scatter request/termination sequence extent mismatch");
    for (unsigned index = 0; index < expected_rounds.size(); ++index) {
      require(!requests.values[index].end_flag &&
              requests.values[index].request_round == expected_rounds[index],
              "original Scatter source-gap request sequence mismatch");
    }
    require(edges.empty() && updates.size() == fixture.size(), "Scatter edge/update conservation");
    for (const auto burst : fixture) {
      const auto observed = updates.read();
      for (unsigned lane = 0; lane < 8; ++lane) {
        const auto source = burst.edges[lane].src.to_uint() & 0x7fffffffu;
        require(observed.tuples[lane].dst == burst.edges[lane].dst &&
                observed.tuples[lane].update == 17 + source % 31,
                "request-dependent Scatter differs from per-source oracle");
      }
    }
    normals += check_wrapper(requests, responses);
    response_lines += responses.values.size() - 1;
    physical += fixture.size() * 8;
    std::cout << "ORIGINAL_SCATTER_CASE {\"id\":\"" << id << "\",\"checked_words\":"
              << fixture.size() * 8 << ",\"source_response_lines\":" << responses.values.size() - 1
              << ",\"request_rounds\":[";
    for (unsigned index = 0; index < expected_rounds.size(); ++index) {
      if (index) std::cout << ',';
      std::cout << requests.values[index].request_round;
    }
    std::cout << "]}\n";
  } else {
    // Expected rejection is not functional admission. Drain fixture queues to
    // avoid HLS leftover warnings obscuring the intentional watchdog result.
    while (!edges.empty()) edges.read();
    while (!updates.empty()) updates.read();
  }
}
}  // namespace

int main() {
  try {
    using Difference = decltype(ap_uint<32>{1} - ap_uint<32>{2});
    static_assert(Difference::width == 33 && Difference::sign_flag,
                  "Scatter guard requires signed 33-bit HLS subtraction");
    require((ap_uint<32>{1} - ap_uint<32>{2}) <= 1,
            "HLS subtraction guard changed signedness");
    unsigned physical = 0, normals = 0, lines = 0;
    run_case("source_window0", {0, 0}, false, physical, normals, lines);
    run_case("source_window1", {1, 1}, false, physical, normals, lines);
    run_case("source_windows012", {0, 1, 2}, false, physical, normals, lines);
    run_case("source_initial_round2", {2}, false, physical, normals, lines);
    run_case("source_gap0_to3", {0, 3}, false, physical, normals, lines);
    std::cout << "PUBLICATION_PROBE {\"kind\":\"regraph_scatter_protocol\",\"passed\":true,"
                 "\"little\":" << LITTLE_KERNEL_NUM << ",\"big\":" << BIG_KERNEL_NUM
              << ",\"positive_cases\":5,\"known_source_gap_watchdogs\":0,\"physical_edges\":"
              << physical << ",\"normal_source_requests\":" << normals
              << ",\"source_response_lines\":" << lines
              << ",\"guard_expression_bits\":33,\"guard_expression_signed\":true}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
