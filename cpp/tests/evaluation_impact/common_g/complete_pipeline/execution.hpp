#pragma once

#include "memory.hpp"
#include <chrono>
#include <exception>
#include <functional>
#include <pthread.h>

namespace complete_g {
// Full cache C simulation needs an 8-MiB local array. Do not enlarge the
// default stack of the hundreds of small finite-search worker threads.
class CacheThread {
 public:
  explicit CacheThread(std::function<void()> body) : body_(std::move(body)) {
    pthread_attr_t attributes;
    require(!pthread_attr_init(&attributes), "cache thread attributes");
    const int stack = pthread_attr_setstacksize(&attributes, 32 * 1024 * 1024);
    const int create = stack ? stack : pthread_create(&thread_, &attributes, [](void* self) -> void* {
      auto& task = *static_cast<CacheThread*>(self);
      try { task.body_(); } catch (...) { task.error_ = std::current_exception(); }
      return nullptr;
    }, this);
    pthread_attr_destroy(&attributes);
    require(!create, "cache thread launch");
  }
  void join() {
    require(!pthread_join(thread_, nullptr), "cache thread join");
    if (error_) std::rethrow_exception(error_);
  }
 private:
  pthread_t thread_{};
  std::function<void()> body_;
  std::exception_ptr error_;
};

inline void check_report_isolation() {
  std::array<search_pipeline::HostReport*, 2> addresses{};
  std::mutex mutex;
  std::condition_variable ready;
  unsigned arrived = 0;
  std::array<std::thread, 2> threads;
  for (unsigned lane = 0; lane < 2; ++lane) threads[lane] = std::thread([&, lane] {
    std::unique_lock<std::mutex> lock(mutex);
    addresses[lane] = &search_pipeline::last_host_report();
    ++arrived;
    ready.notify_all();
    ready.wait(lock, [&] { return arrived == 2; });
    require(addresses[0] != addresses[1], "concurrent search diagnostics share mutable storage");
  });
  for (auto& thread : threads) thread.join();
}

template <class FixtureType, class MemoryType>
inline std::array<unsigned, 4> run_g(const FixtureType& fixture, MemoryType& memory,
                                    const std::vector<unsigned long>& updates, bool registered) {
  std::array<std::vector<unsigned long>, 4> lanes;
  std::array<unsigned long, 4> probes{};
  std::array<search_pipeline::HostReport, 4> reports;
  std::array<unsigned, 4> dispatched{};
  for (unsigned i = 0; i < updates.size(); ++i) {
    lanes[i % 4].push_back(updates[i]);
    unsigned long ignored = 0;
    ++dispatched[MemoryType::owner(fixture.locate(updates[i], ignored))];
  }
  hls::stream<Packet> searched[4], inputs[4], outputs[4];
  search_pipeline::HostNetwork host;
  for (unsigned lane = 0; lane < 4; ++lane) {
    host.bind(searched[lane]); host.bind(inputs[lane]); host.bind(outputs[lane]);
    host.launch([&, lane] {
      bin_search(lanes[lane].data(), fixture.binary.data(), fixture.binary.data(),
          fixture.binary.data(), fixture.binary.data(), fixture.rows.data(), fixture.rows.data(),
          fixture.rows.data(), fixture.rows.data(), lanes[lane].size(), searched[lane]);
      reports[lane] = search_pipeline::last_host_report();
    });
    host.launch([&, lane] {
      if (lane == 3) std::this_thread::sleep_for(std::chrono::milliseconds(5));
      for (auto raw : lanes[lane]) {
        const auto packet = searched[lane].read();
        const auto segment = fixture.locate(raw, probes[lane]);
        const ap_uint<96> expected = (ap_uint<96>(raw) << 32) | ap_uint<96>(segment * 16);
        require(packet.data == expected && packet.keep == decltype(packet.keep)(-1) &&
                packet.strb == decltype(packet.strb)(-1) && !packet.last,
                "complete G ordered search payload/sideband mismatch");
        inputs[lane].write(packet);
      }
    });
  }
  host.launch([&] {
    production_dispatch::dispatch(updates.size(), inputs[0], inputs[1], inputs[2], inputs[3],
                                 outputs[0], outputs[2], outputs[1], outputs[3]);
  });
  auto cache = [&](unsigned port) {
    if (registered) cache_registered::candidate(memory.buffers[port].data(), outputs[port]);
    else process_cache(memory.buffers[port].data(), outputs[port]);
  };
  CacheThread even([&] { cache(0); }), odd([&] { cache(2); });
  for (unsigned port : {1u, 3u}) host.launch([&, port] {
    auto* buffer = memory.buffers[port].data();
    // Match the actual host: all four DDR pointer arguments alias the same BO,
    // and cold indices retain the complete local index, including hot prefix.
    production_ddr::process_ddr(buffer, buffer, buffer, buffer, outputs[port]);
  });
  even.join(); odd.join();
  // Cache consumers are not owned by HostNetwork; finish them before its
  // queue-conservation snapshot can observe a still-pending end token.
  host.join();
  const auto& external = search_pipeline::last_host_report().channels;
  require(external.size() == 12, "external G FIFO topology");
  for (unsigned lane = 0; lane < 4; ++lane) {
    const auto& channels = reports[lane].channels;
    require(channels.size() == 339, "four-CU finite search topology");
    const auto requests = lanes[lane].size() + probes[lane] + 1;
    require(channels[337].writes == requests && channels[338].writes == requests,
            "four-CU metadata request/response ledger");
    require(external[3 * lane].writes == lanes[lane].size() &&
            external[3 * lane + 1].writes == lanes[lane].size() &&
            external[3 * lane + 2].writes == dispatched[lane] + 1,
            "complete G stream ledger/end-token mismatch");
  }
  memory.apply(fixture, updates);
  memory.check();
  return dispatched;
}

inline unsigned check_adapter(const Fixture& fixture, Memory& memory) {
  std::vector<Word> rows((vertices + 7) / 8);
  for (unsigned source = 0; source < vertices; ++source)
    rows[source / 8].range((source % 8) * 64 + 63, (source % 8) * 64) = fixture.rows[source];
  const auto expected = memory.logical(fixture.source);
  std::set<std::pair<unsigned, unsigned>> actual;
  hls::stream<edge_burst_pkt_t> output;
  search_pipeline::FiniteQueue<edge_burst_pkt_t> queue(2);
  output.set_delegate(&queue);
  unsigned packets = 0;
  std::thread consumer([&] {
    while (true) {
      const auto packet = output.read();
      require(++packets <= segments * 2, "adapter emitted too many packets");
      require(packet.keep == decltype(packet.keep)(-1) && packet.strb == decltype(packet.strb)(-1),
              "adapter byte enables");
      for (unsigned lane = 0; lane < 8; ++lane) {
        const unsigned source = packet.data.range(lane * 64 + 31, lane * 64).to_uint();
        const unsigned word = packet.data.range(lane * 64 + 63, lane * 64 + 32).to_uint();
        require(bool(source >> 31) == bool(word >> 31), "adapter dummy consistency");
        if (!(word >> 31)) require(actual.emplace(source, word).second, "adapter duplicate edge");
      }
      if (packet.last) break;
    }
  });
  pma_to_regraph_adapter(memory.buffers[0].data(), memory.buffers[1].data(),
      memory.buffers[2].data(), memory.buffers[3].data(), rows.data(), vertices, segments * 16,
      MAX_CACHE_SEGMENT, 0, vertices, output);
  consumer.join();
  const auto stats = queue.stats();
  require(packets == segments * 2 && queue.size() == 0 && stats.writes == stats.reads &&
          stats.high_water <= stats.capacity && actual == expected,
          "physical G PMA handoff vs independent logical graph");
  output.set_delegate(nullptr);
  return actual.size();
}
}  // namespace complete_g
