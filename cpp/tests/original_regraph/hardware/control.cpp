#include "device.hpp"
#include <iomanip>
#include <iostream>

namespace rb = original_r_board;

int main(int argc, char** argv) {
  try {
    rb::require(argc == 6 || argc == 8,
        "usage: original_r_control offline|board INPUT a4|original_example author_initial|csr_degree OUTPUT [XCLBIN DEVICE]");
    const bool board = std::string_view(argv[1]) == "board";
    rb::require(board ? argc == 8 : argc == 6 && std::string_view(argv[1]) == "offline", "invalid control mode");
    const auto model = rb::Model::load(argv[2], argv[3], rb::binding(argv[4]));
    const std::filesystem::path output(argv[5]);
    rb::require(!std::filesystem::exists(output), "fresh output directory required");
    std::filesystem::create_directories(output);
    rb::Observation observation;
    std::string bdf;
    rb::Window window{};
    std::vector<rb::Times> times;
    if (board) {
      rb::Device device(argv[6], rb::number(argv[7]), model);
      bdf = device.session.bdf;
      observation = device.run(model);
      for (const auto& event : observation.events) times.push_back(event.times());
      window = rb::window(times);
      device.verify(model, output);
    }
    rb::wt::write_words(output / "expected.u32le", model.expected);
    std::ofstream report(output / "result.json");
    report << std::setprecision(17) << "{\n\"status\":\"" << (board ? "ORIGINAL_R_GUARDED_BOARD_CONTROL_PASS" :
        "ORIGINAL_R_CONTROL_OFFLINE_PASS_NOT_FPGA") << "\",\n\"board_programmed\":" << (board ? "true" : "false")
        << ",\n\"hardware_timing_measured\":" << (board ? "true" : "false")
        << ",\n\"publication_match\":false,\n\"topology\":\"" << argv[3] << "\",\n\"binding\":\"" << argv[4]
        << "\",\n\"bdf\":\"" << bdf << "\",\n\"iterations\":1,\n\"argument\":0,\n\"vertices\":" << model.vertices
        << ",\n\"logical_edges\":" << model.logical_edges << ",\n\"physical_edges\":" << model.physical_edges
        << ",\n\"dummy_edges\":" << model.dummy_edges << ",\n\"aligned_vertices\":" << model.aligned
        << ",\n\"published_vertices\":" << model.published << ",\n\"allocation_vertices\":" << model.allocation
        << ",\n\"extra_padding_vertices\":" << model.extra_padding << ",\n\"guard_words\":" << rb::guard_words
        << ",\n\"little\":" << model.little << ",\n\"big\":" << model.big << ",\n\"dense\":" << model.dense
        << ",\n\"sparse\":" << model.sparse << ",\n\"tasks\":" << model.tasks.size()
        << ",\n\"enqueue_to_completion_ms\":";
    if (board) report << observation.enqueue_to_completion_ms; else report << "null";
    report << ",\n\"event_union_ns\":"; if (board) report << window.busy_ns; else report << "null";
    report << ",\n\"event_span_ns\":"; if (board) report << window.span_ns; else report << "null";
    report << ",\n\"events\":[";
    for (unsigned index = 0; index < times.size(); ++index) {
      const auto& event = observation.events[index]; const auto& time = times[index];
      report << (index ? "," : "") << "{\"role\":\"" << event.role << "\",\"ordinal\":" << event.ordinal
          << ",\"lane\":" << event.lane << ",\"queued_ns\":" << time.queued << ",\"submitted_ns\":" << time.submitted
          << ",\"start_ns\":" << time.start << ",\"end_ns\":" << time.end << "}";
    }
    report << "]\n}\n"; report.close(); rb::require(report.good(), "failed to save control observations");
    std::cout << (board ? "ORIGINAL_R_GUARDED_BOARD_CONTROL_PASS" : "ORIGINAL_R_CONTROL_OFFLINE_PASS_NOT_FPGA") << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ORIGINAL_R_CONTROL_REJECTED " << error.what() << '\n'; return 1;
  }
}
