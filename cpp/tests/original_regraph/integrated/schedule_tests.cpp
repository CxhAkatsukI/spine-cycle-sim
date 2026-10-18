#include "schedule.hpp"
#include <iostream>

namespace k4 = original_r_k4;
namespace rb = original_r_board;

template <typename F> void rejects(F operation) {
  bool rejected = false;
  try { operation(); } catch (const std::runtime_error&) { rejected = true; }
  rb::require(rejected, "invalid K4 schedule/event accepted");
}

int main() {
  try {
    rejects([] { k4::Schedule::build(0); });
    rejects([] { k4::Schedule::build(UINT32_MAX); });
    for (unsigned partitions : {1, 2, 3, 4, 5, 12, 33}) {
      auto schedule = k4::Schedule::build(partitions);
      schedule.validate(partitions);
      rb::require(schedule.commands.size() == 2 + 3ull * partitions, "K4 command count mismatch");
      for (unsigned worker = 0; worker < 4; ++worker)
        rb::require(schedule.worker_partitions[worker] == (partitions + 3 - worker) / 4, "K4 idle/reused worker mismatch");
      std::vector<rb::Times> times;
      for (std::size_t index = 0; index < schedule.commands.size(); ++index) {
        const auto start = 100 + index * 20;
        times.push_back({1, 2, start, start + 10});
        const auto& command = schedule.commands[index];
        if (index < 2) rb::require(command.waits.empty(), "consumer must not wait for producer completion");
        else if (command.role == k4::Role::adapter || command.role == k4::Role::gather)
          rb::require(command.waits == (command.partition >= 4 ? std::vector<std::size_t>{index - 12} :
                                          std::vector<std::size_t>{}), "wrong per-worker predecessor");
        else rb::require(command.waits == (command.partition ? std::vector<std::size_t>{index - 3} :
                                             std::vector<std::size_t>{}), "wrong mux predecessor");
      }
      schedule.verify_events(partitions, times);
      const auto window = rb::window(times);
      rb::require(window.busy_ns == times.size() * 10 && window.span_ns == (times.size() - 1) * 20 + 10,
                  "event union/span mismatch");
      auto bad_times = times; bad_times.pop_back();
      rejects([&] { schedule.verify_events(partitions, bad_times); });
      bad_times = times; bad_times[0].end = bad_times[0].start;
      rejects([&] { schedule.verify_events(partitions, bad_times); });
      auto bad = schedule; bad.commands.back().waits = {bad.commands.size() - 1};
      rejects([&] { bad.validate(partitions); });
      bad = schedule; ++bad.worker_partitions[3];
      rejects([&] { bad.validate(partitions); });
      if (partitions > 1) {
        bad_times = times; bad_times[4].end = bad_times[7].start + 1;
        rejects([&] { schedule.verify_events(partitions, bad_times); });
      }
    }
    // All stream participants can overlap; their durations must not be added.
    const auto schedule = k4::Schedule::build(1);
    const std::vector<rb::Times> overlapped(5, {1, 2, 100, 200});
    schedule.verify_events(1, overlapped);
    rb::require(rb::window(overlapped).busy_ns == 100 && rb::window(overlapped).span_ns == 100,
                "overlapping stream events double counted");
    std::cout << "K4_SCHEDULE_TESTS_PASS_NOT_FPGA\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n'; return 1;
  }
}
