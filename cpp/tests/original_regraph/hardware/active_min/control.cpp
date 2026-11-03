#include "../device.hpp"
#include "input.hpp"

#include <iomanip>
#include <iostream>

namespace rb = original_r_board;
namespace am = rb::active_min;

int main(int argc, char** argv) {
  try {
    rb::require(argc == 5 || argc == 7,
        "usage: active_min_control offline|board cc|weighted_sssp INPUT OUTPUT [XCLBIN DEVICE]");
    const auto mode = std::string_view(argv[1]), algorithm = std::string_view(argv[2]);
    const bool board = mode == "board";
    rb::require((board && argc == 7) || (mode == "offline" && argc == 5), "invalid control mode");
    rb::require(algorithm == "cc" || algorithm == "weighted_sssp", "explicit active-min algorithm required");
    const auto policy = algorithm == "cc" ? am::Policy::cc : am::Policy::weighted_sssp;
    const auto model = am::board_model(am::Input::load(argv[3], policy));
    const std::filesystem::path output(argv[4]);
    rb::require(std::filesystem::create_directory(output), "fresh result directory required");
    rb::wt::write_words(output / "expected.u32le", model.expected);
    rb::Observation observation;
    std::string bdf;
    std::vector<rb::Times> times;
    rb::Window window{};
    if (board) {
      rb::Device device(argv[5], rb::number(argv[6]), model, rb::ApplyBuffer::active_property);
      bdf = device.session.bdf;
      observation = device.run(model);
      for (const auto& event : observation.events) times.push_back(event.times());
      window = rb::window(times);
      device.verify(model, output);
    }
    const auto status = board ? "A4_ACTIVE_MIN_BOARD_PASS" : "A4_ACTIVE_MIN_OFFLINE_PASS_NOT_FPGA";
    std::ofstream report(output / "result.json");
    report << std::setprecision(17) << "{\n\"status\":\"" << status << "\",\n\"algorithm\":\"" << algorithm
        << "\",\n\"bdf\":\"" << bdf << "\",\n\"topology\":\"a4\",\n\"iterations\":1"
        << ",\n\"vertices\":" << model.vertices << ",\n\"logical_edges\":" << model.logical_edges
        << ",\n\"physical_edges\":" << model.physical_edges << ",\n\"tasks\":" << model.tasks.size()
        << ",\n\"hardware_timing_measured\":" << (board ? "true" : "false") << ",\n\"enqueue_to_completion_ms\":";
    if (board) report << observation.enqueue_to_completion_ms; else report << "null";
    report << ",\n\"event_span_ns\":"; if (board) report << window.span_ns; else report << "null";
    report << ",\n\"event_union_ns\":"; if (board) report << window.busy_ns; else report << "null";
    report << ",\n\"events\":[";
    for (unsigned i = 0; i < times.size(); ++i) {
      const auto& event = observation.events[i];
      const auto& time = times[i];
      report << (i ? "," : "") << "{\"role\":\"" << event.role << "\",\"ordinal\":" << event.ordinal
          << ",\"lane\":" << event.lane << ",\"queued_ns\":" << time.queued
          << ",\"submitted_ns\":" << time.submitted << ",\"start_ns\":" << time.start
          << ",\"end_ns\":" << time.end << "}";
    }
    report << "]\n}\n";
    report.close();
    rb::require(report.good(), "failed to save active-min observations");
    std::cout << status << '\n';
  } catch (const std::exception& error) {
    std::cerr << "A4_ACTIVE_MIN_REJECTED " << error.what() << '\n';
    return 1;
  }
}
