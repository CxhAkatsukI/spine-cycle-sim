#pragma once

#include "../../memory_fixture.hpp"
#include "input.hpp"

namespace original_regraph_mixed_test {
namespace rg = spine::sim::original_regraph;
using spine::sim::Fifo;
using original_regraph_memory_test::MemoryLink;

class Resources : public original_regraph_memory_test::MemoryFixture {
 public:
  explicit Resources(std::uint64_t latency) : MemoryFixture(32, latency) {}
  template <typename T> Fifo<T>* stream(const std::string& name, std::size_t depth) {
    auto* queue = make<Fifo<T>>(name, clock, depth);
    checks_.push_back([queue] { return queue->empty() && queue->stats().pushes == queue->stats().pops &&
        queue->stats().max_occupancy <= queue->depth(); });
    return queue;
  }
  bool drained() const {
    return MemoryFixture::drained() && std::all_of(checks_.begin(), checks_.end(), [](const auto& check) { return check(); });
  }
 private:
  std::vector<std::function<bool()>> checks_;
};

struct Tasks {
  std::vector<const Task*> tasks;
  std::vector<std::uint64_t> starts, completions;
  bool active{};
};

inline constexpr std::uint64_t kOutputAddress = 64ull * 1024 * 1024;

}  // namespace original_regraph_mixed_test
