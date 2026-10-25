// Host-only launch diagnostic; the pinned model, buffers and FPGA are unchanged.
#include "device.hpp"
#include <iomanip>
#include <iostream>

namespace rb = original_r_board;

struct AuthorObservation {
  rb::Observation complete;
  double post_enqueue_wait_ms{};
};

AuthorObservation author_run(rb::Device& device, const rb::Model& model) {
  AuthorObservation observation;
  auto& result = observation.complete;
  result.events.reserve(model.tasks.size() + 2);
  const auto begin = std::chrono::steady_clock::now();
  unsigned argument = 0;
  for (const auto& buffer : device.sources)
    rb::checked(device.wrapper.setArg(argument++, buffer), "bind source");
  for (const auto& buffer : device.outputs)
    rb::checked(device.wrapper.setArg(argument++, buffer), "bind output");
  rb::checked(device.wrapper.setArg(argument++, model.dense), "bind dense");
  rb::checked(device.wrapper.setArg(argument++, model.sparse), "bind sparse");
  result.events.push_back({"hbm_wrapper", 0, 0, {}});
  rb::checked(device.session.wrapper.enqueueTask(device.wrapper, nullptr, &result.events.back().event), "enqueue wrapper");
  rb::checked(device.apply_kernel.setArg(0, device.divisor), "bind divisor");
  rb::checked(device.apply_kernel.setArg(1, model.dense), "bind apply dense");
  rb::checked(device.apply_kernel.setArg(2, model.sparse), "bind apply sparse");
  rb::checked(device.apply_kernel.setArg(3, 0u), "bind PR argument");
  result.events.push_back({"apply", 0, 0, {}});
  rb::checked(device.session.apply.enqueueTask(device.apply_kernel, nullptr, &result.events.back().event), "enqueue apply");
  for (unsigned ordinal = 0; ordinal < model.tasks.size(); ++ordinal) {
    const auto& task = model.tasks[ordinal];
    auto& kernel = device.lanes[task.kernel];
    rb::checked(kernel.setArg(0, device.edges[ordinal]), "bind edges");
    rb::checked(kernel.setArg(1, task.words / 2), "bind edge count");
    rb::checked(kernel.setArg(2, task.destination), "bind destination");
    result.events.push_back({task.kernel < model.little ? "little" : "big", ordinal, task.kernel, {}});
    rb::checked(device.session.lanes[task.kernel].enqueueTask(kernel, nullptr,
        &result.events.back().event), "enqueue GS");
  }
  // Match the author's host timer placement, retaining the full window too.
  const auto wait_begin = std::chrono::steady_clock::now();
  for (auto& queue : device.session.lanes) rb::checked(queue.finish(), "finish GS");
  rb::checked(device.session.apply.finish(), "finish apply");
  rb::checked(device.session.wrapper.finish(), "finish wrapper");
  const auto end = std::chrono::steady_clock::now();
  observation.post_enqueue_wait_ms = std::chrono::duration<double, std::milli>(end - wait_begin).count();
  result.enqueue_to_completion_ms = std::chrono::duration<double, std::milli>(end - begin).count();
  return observation;
}

rb::Observation prepared_run(rb::Device& device, const rb::Model& model) {
  const auto begin = std::chrono::steady_clock::now();
  unsigned argument = 0;
  for (const auto& buffer : device.sources)
    rb::checked(device.wrapper.setArg(argument++, buffer), "bind source");
  for (const auto& buffer : device.outputs)
    rb::checked(device.wrapper.setArg(argument++, buffer), "bind output");
  rb::checked(device.wrapper.setArg(argument++, model.dense), "bind dense");
  rb::checked(device.wrapper.setArg(argument++, model.sparse), "bind sparse");
  rb::checked(device.apply_kernel.setArg(0, device.divisor), "bind divisor");
  rb::checked(device.apply_kernel.setArg(1, model.dense), "bind apply dense");
  rb::checked(device.apply_kernel.setArg(2, model.sparse), "bind apply sparse");
  rb::checked(device.apply_kernel.setArg(3, 0u), "bind PR argument");
  std::vector<cl::Kernel> kernels;
  for (unsigned ordinal = 0; ordinal < model.tasks.size(); ++ordinal) {
    const auto& task = model.tasks[ordinal];
    const bool big = task.kernel >= model.little;
    const std::string name = big ? "bigKernelScatterGather" : "littleKernelScatterGather";
    kernels.push_back(device.session.kernel(name + ":{" + name + "_" +
        std::to_string((big ? task.kernel - model.little : task.kernel) + 1) + "}"));
    rb::checked(kernels.back().setArg(0, device.edges[ordinal]), "bind edges");
    rb::checked(kernels.back().setArg(1, task.words / 2), "bind edge count");
    rb::checked(kernels.back().setArg(2, task.destination), "bind destination");
  }
  rb::Observation result;
  result.events.reserve(model.tasks.size() + 2);
  result.events.push_back({"hbm_wrapper", 0, 0, {}});
  rb::checked(device.session.wrapper.enqueueTask(device.wrapper, nullptr, &result.events.back().event), "enqueue wrapper");
  result.events.push_back({"apply", 0, 0, {}});
  rb::checked(device.session.apply.enqueueTask(device.apply_kernel, nullptr, &result.events.back().event), "enqueue apply");
  for (unsigned ordinal = 0; ordinal < model.tasks.size(); ++ordinal) {
    const auto& task = model.tasks[ordinal];
    result.events.push_back({task.kernel < model.little ? "little" : "big", ordinal, task.kernel, {}});
    rb::checked(device.session.lanes[task.kernel].enqueueTask(kernels[ordinal], nullptr,
        &result.events.back().event), "enqueue GS");
  }
  rb::checked(device.session.wrapper.flush(), "flush wrapper");
  rb::checked(device.session.apply.flush(), "flush apply");
  for (auto& queue : device.session.lanes) rb::checked(queue.flush(), "flush GS");
  for (auto& queue : device.session.lanes) rb::checked(queue.finish(), "finish GS");
  rb::checked(device.session.apply.finish(), "finish apply");
  rb::checked(device.session.wrapper.finish(), "finish wrapper");
  result.enqueue_to_completion_ms = std::chrono::duration<double, std::milli>(
      std::chrono::steady_clock::now() - begin).count();
  return result;
}

void save(const rb::Observation& observation, const std::filesystem::path& output,
          double post_enqueue_wait_ms = -1) {
  std::vector<rb::Times> times;
  for (const auto& event : observation.events) times.push_back(event.times());
  const auto window = rb::window(times);
  std::ofstream report(output / "timing.json");
  report << std::setprecision(17) << "{\"resident_wall_ms\":" << observation.enqueue_to_completion_ms
      << ",\"event_span_ns\":" << window.span_ns << ",\"event_union_ns\":" << window.busy_ns
      << ",\"post_enqueue_wait_ms\":";
  if (post_enqueue_wait_ms < 0) report << "null";
  else report << post_enqueue_wait_ms;
  report << ",\"events\":[";
  for (unsigned i = 0; i < times.size(); ++i) {
    const auto& event = observation.events[i]; const auto& time = times[i];
    report << (i ? "," : "") << "{\"role\":\"" << event.role << "\",\"ordinal\":" << event.ordinal
        << ",\"lane\":" << event.lane << ",\"queued_ns\":" << time.queued
        << ",\"submitted_ns\":" << time.submitted << ",\"start_ns\":" << time.start
        << ",\"end_ns\":" << time.end << "}";
  }
  report << "]}\n"; report.close(); rb::require(report.good(), "save timing failed");
}

int main(int argc, char** argv) {
  try {
    rb::require(argc == 7, "usage: launch_control INPUT TOPOLOGY BINDING OUTPUT XCLBIN DEVICE");
    const auto model = rb::Model::load(argv[1], argv[2], rb::binding(argv[3]));
    const std::filesystem::path output(argv[4]);
    rb::require(!std::filesystem::exists(output), "fresh output required");
    std::filesystem::create_directories(output);
    rb::Device device(argv[5], rb::number(argv[6]), model);
    for (unsigned repeat = 0; repeat < 4; ++repeat) {
      for (const std::string mode : {"baseline", "prebound", "author_order"}) {
        if (repeat == 0 && mode != "baseline") continue;
        const auto destination = output / (mode + "_r" + std::to_string(repeat));
        std::filesystem::create_directory(destination);
        const auto author = mode == "author_order" ? author_run(device, model) : AuthorObservation{};
        const auto observation = mode == "baseline" ? device.run(model) :
            mode == "prebound" ? prepared_run(device, model) : author.complete;
        device.verify(model, destination);
        rb::wt::write_words(destination / "expected.u32le", model.expected);
        save(observation, destination, mode == "author_order" ? author.post_enqueue_wait_ms : -1);
        std::cout << destination.filename().string() << " correctness PASS" << std::endl;
      }
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "LAUNCH_DIAGNOSTIC_REJECTED " << error.what() << '\n'; return 1;
  }
}
