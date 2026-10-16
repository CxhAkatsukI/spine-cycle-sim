#pragma once

#include "opencl.hpp"
#include <chrono>

namespace original_r_board {
struct Observation {
  double enqueue_to_completion_ms{};
  std::vector<Event> events;
};

struct Device {
  Session session;
  std::vector<cl::Kernel> lanes;
  cl::Kernel wrapper, apply_kernel;
  std::vector<cl::Buffer> sources, outputs, edges;
  cl::Buffer divisor;

  Device(const std::filesystem::path& xclbin, unsigned index, const Model& model) :
      session(xclbin, index, board_lanes(model)),
      wrapper(session.kernel("kernelHBMWrapper:{kernelHBMWrapper_1}")),
      apply_kernel(session.kernel("kernelApply:{kernelApply_1}")) {
    for (unsigned lane = 0; lane < model.little + model.big; ++lane) {
      const bool big = lane >= model.little;
      const auto name = big ? "bigKernelScatterGather" : "littleKernelScatterGather";
      lanes.push_back(session.kernel(std::string(name) + ":{" + name + "_" +
          std::to_string((big ? lane - model.little : lane) + 1) + "}"));
      sources.push_back(session.buffer(2 * lane + 1, model.source(), CL_MEM_READ_ONLY));
      outputs.push_back(session.buffer(2 * lane + 1, model.output(), CL_MEM_READ_WRITE));
    }
    divisor = session.buffer(30, model.divisor(), CL_MEM_READ_ONLY);
    for (unsigned ordinal = 0; ordinal < model.tasks.size(); ++ordinal)
      edges.push_back(session.buffer(2 * model.tasks[ordinal].kernel, model.edges(ordinal), CL_MEM_READ_ONLY));
  }

  Observation run(const Model& model) {
    Observation result;
    result.events.reserve(model.tasks.size() + 2);
    const auto begin = std::chrono::steady_clock::now();
    unsigned argument = 0;
    for (const auto& buffer : sources) checked(wrapper.setArg(argument++, buffer), "bind source replica");
    for (const auto& buffer : outputs) checked(wrapper.setArg(argument++, buffer), "bind output replica");
    checked(wrapper.setArg(argument++, model.dense), "bind wrapper dense count");
    checked(wrapper.setArg(argument++, model.sparse), "bind wrapper sparse count");
    result.events.push_back({"hbm_wrapper", 0, 0, {}});
    checked(session.wrapper.enqueueTask(wrapper, nullptr, &result.events.back().event), "enqueue HBM wrapper");
    checked(apply_kernel.setArg(0, divisor), "bind apply divisor");
    checked(apply_kernel.setArg(1, model.dense), "bind apply dense count");
    checked(apply_kernel.setArg(2, model.sparse), "bind apply sparse count");
    checked(apply_kernel.setArg(3, 0u), "bind one-superstep PR argument");
    result.events.push_back({"apply", 0, 0, {}});
    checked(session.apply.enqueueTask(apply_kernel, nullptr, &result.events.back().event), "enqueue apply");
    for (unsigned ordinal = 0; ordinal < model.tasks.size(); ++ordinal) {
      const auto& task = model.tasks[ordinal]; auto& kernel = lanes[task.kernel];
      checked(kernel.setArg(0, edges[ordinal]), "bind resident task edges");
      checked(kernel.setArg(1, task.words / 2), "bind physical task edge count");
      checked(kernel.setArg(2, task.destination), "bind destination offset");
      result.events.push_back({task.kernel < model.little ? "little" : "big", ordinal, task.kernel, {}});
      checked(session.lanes[task.kernel].enqueueTask(kernel, nullptr, &result.events.back().event), "enqueue original GS task");
    }
    // Streaming kernels need all queues submitted before waiting on any consumer.
    checked(session.wrapper.flush(), "flush wrapper"); checked(session.apply.flush(), "flush apply");
    for (auto& queue : session.lanes) checked(queue.flush(), "flush GS queue");
    for (auto& queue : session.lanes) checked(queue.finish(), "complete GS queue");
    checked(session.apply.finish(), "complete apply"); checked(session.wrapper.finish(), "complete publication");
    result.enqueue_to_completion_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - begin).count();
    return result;
  }

  void verify(const Model& model, const std::filesystem::path& output) {
    for (unsigned lane = 0; lane < lanes.size(); ++lane) {
      const auto actual = session.read(outputs[lane], model.expected.size());
      model.verify(actual, model.expected, "published output, padding, tail or guard mismatch");
      wt::write_words(output / ("replica" + std::to_string(lane) + ".u32le"), actual);
      model.verify(session.read(sources[lane], model.allocation + guard_words), model.source(),
                   "resident source or source guard changed");
    }
    model.verify(session.read(divisor, model.allocation + guard_words), model.divisor(), "divisor or guard changed");
    for (unsigned ordinal = 0; ordinal < edges.size(); ++ordinal) {
      const auto target = model.edges(ordinal);
      model.verify(session.read(edges[ordinal], target.size()), target, "resident task edge or guard changed");
    }
  }
};
}  // namespace original_r_board
