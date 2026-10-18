#pragma once

#include "capture.hpp"
#include "schedule.hpp"
#include "../hardware/opencl.hpp"
#include <chrono>

namespace original_r_k4 {
struct Observation {
  double enqueue_to_completion_ms{};
  std::vector<rb::Event> events;
  std::vector<rb::Times> times;
  rb::Window window;
};

struct Device {
  rb::Session session;
  cl::CommandQueue pipeline;
  std::array<cl::Kernel, 4> adapter, gather;
  cl::Kernel hbm, apply, mux;
  std::vector<cl::Buffer> graph_buffers, state_buffers;

  Device(const std::filesystem::path& xclbin, unsigned index, const Model& model) :
      session(xclbin, index, 4),
      hbm(session.kernel("kernelHBMWrapper:{kernelHBMWrapper_1}")),
      apply(session.kernel("regraph_pagerank_apply:{regraph_pagerank_apply_1}")),
      mux(session.kernel("regraph_frontend_mux:{regraph_frontend_mux_1}")) {
    cl_int error = CL_SUCCESS;
    constexpr auto properties = CL_QUEUE_OUT_OF_ORDER_EXEC_MODE_ENABLE | CL_QUEUE_PROFILING_ENABLE;
    const auto supported = session.device.getInfo<CL_DEVICE_QUEUE_PROPERTIES>(&error);
    rb::checked(error, "query K4 queue properties");
    require((supported & properties) == properties, "K4 requires out-of-order profiled streaming queue");
    pipeline = cl::CommandQueue(session.context, session.device, properties, &error);
    rb::checked(error, "create K4 streaming queue");
    for (unsigned worker = 0; worker < 4; ++worker) {
      const auto suffix = std::to_string(worker + 1) + "}";
      adapter[worker] = session.kernel("pma_to_regraph_adapter:{pma_to_regraph_adapter_" + suffix);
      gather[worker] = session.kernel("lksg_stream:{lksg_stream_" + suffix);
    }
    for (const auto& value : model.preparation.buffers)
      graph_buffers.push_back(session.buffer(value.bank, value.initial, CL_MEM_READ_ONLY));
    for (const auto& value : model.state)
      state_buffers.push_back(session.buffer(value.bank, value.initial,
                                           value.expected.empty() ? CL_MEM_READ_ONLY : CL_MEM_READ_WRITE));
  }

  const cl::Buffer& graph(const Model& model, unsigned partition, const std::string& name) const {
    const auto& value = model.preparation.buffer(partition, name);
    return graph_buffers.at(&value - model.preparation.buffers.data());
  }
  const cl::Buffer& state(const Model& model, const std::string& name) const {
    const auto& value = model.buffer(name);
    return state_buffers.at(&value - model.state.data());
  }

  void bind(const Model& model, const Command& command, const Schedule& schedule) {
    const auto arg = [](cl::Kernel& kernel, unsigned index, const auto& value) {
      rb::checked(kernel.setArg(index, value), "bind K4 kernel argument");
    };
    if (command.role == Role::hbm) {
      for (unsigned index = 0; index < 4; ++index)
        arg(hbm, index, state(model, index % 2 ? "source_a1" : "source_a0"));
      arg(hbm, 4, state(model, "source_b0")); arg(hbm, 5, state(model, "source_b1"));
      for (unsigned worker = 0; worker < 4; ++worker) arg(hbm, 6 + worker, schedule.worker_partitions[worker]);
    } else if (command.role == Role::apply) {
      arg(apply, 0, state(model, "rank")); arg(apply, 1, state(model, "divisor"));
      arg(apply, 2, state(model, "stats")); arg(apply, 3, model.original.aligned / 16);
      arg(apply, 4, model.original.vertices); arg(apply, 5, damping); arg(apply, 6, 0.0F);
      arg(apply, 7, base); arg(apply, 8, dangling_share);
    } else if (command.role == Role::adapter) {
      auto& kernel = adapter.at(command.worker);
      const auto& shard = model.preparation.graph.shards.at(command.partition);
      for (unsigned port = 0; port < 4; ++port)
        arg(kernel, port, graph(model, command.partition, "pma" + std::to_string(port)));
      arg(kernel, 4, graph(model, command.partition, "row")); arg(kernel, 5, model.original.vertices);
      arg(kernel, 6, static_cast<unsigned>(model.preparation.plan.shards.at(command.partition).pma_slot_count));
      arg(kernel, 7, static_cast<unsigned>(cache_segments)); arg(kernel, 8, shard.destination_base);
      arg(kernel, 9, static_cast<unsigned>(shard.destination_vertices));
    } else if (command.role == Role::gather) {
      auto& kernel = gather.at(command.worker);
      arg(kernel, 1, static_cast<unsigned>(model.preparation.plan.shards.at(command.partition).pma_slot_count));
      arg(kernel, 2, 0u); arg(kernel, 3, model.preparation.graph.shards.at(command.partition).destination_base);
      arg(kernel, 4, true);
    } else {
      require(command.role == Role::mux, "unrecognized K4 command");
      arg(mux, 4, command.worker); arg(mux, 5, static_cast<unsigned>(partition_vertices / 16));
    }
  }

  cl::Kernel& kernel(const Command& command) {
    switch (command.role) {
      case Role::hbm: return hbm;
      case Role::apply: return apply;
      case Role::adapter: return adapter.at(command.worker);
      case Role::gather: return gather.at(command.worker);
      case Role::mux: return mux;
    }
    throw std::runtime_error("invalid K4 command");
  }

  Observation run(const Model& model, const Schedule& schedule) {
    schedule.validate(model.preparation.graph.shards.size());
    require(schedule.worker_partitions == model.worker_partitions, "K4 worker partition count mismatch");
    Observation result;
    result.events.reserve(schedule.commands.size());
    const auto begin = std::chrono::steady_clock::now();
    for (const auto& command : schedule.commands) {
      bind(model, command, schedule);
      std::vector<cl::Event> waits;
      for (const auto index : command.waits) waits.push_back(result.events.at(index).event);
      result.events.push_back({name(command.role), command.partition, command.worker, {}});
      rb::checked(pipeline.enqueueTask(kernel(command), waits.empty() ? nullptr : &waits,
                                      &result.events.back().event), "enqueue K4 stream command");
    }
    // Producers and consumers must all be submitted before waiting on a stream.
    rb::checked(pipeline.flush(), "flush K4 streaming queue");
    rb::checked(pipeline.finish(), "complete K4 publication");
    result.enqueue_to_completion_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - begin).count();
    for (const auto& event : result.events) result.times.push_back(event.times());
    schedule.verify_events(model.preparation.graph.shards.size(), result.times);
    result.window = rb::window(result.times);
    return result;
  }

  void verify(const Model& model, const std::filesystem::path& output) {
    require(std::filesystem::create_directory(output / "readback"), "fresh readback directory required");
    const auto save = [&](const Buffer& expected, const cl::Buffer& device, const std::string& filename) {
      auto actual = session.read(device, expected.initial.size());
      rb::wt::write_words(output / "readback" / (filename + ".u32le"), actual);
      expected.verify(actual);
      return actual;
    };
    for (std::size_t index = 0; index < graph_buffers.size(); ++index) {
      const auto& expected = model.preparation.buffers.at(index);
      save(expected, graph_buffers[index], buffer_name(expected));
    }
    for (std::size_t index = 0; index < state_buffers.size(); ++index) {
      const auto& expected = model.state.at(index);
      const auto actual = save(expected, state_buffers[index], buffer_name(expected));
      if (expected.name == "rank" || expected.name == "source_b0") {
        Words external(model.original.vertices);
        for (std::size_t vertex = 0; vertex < external.size(); ++vertex)
          external[vertex] = actual.at(model.preparation.graph.external_to_internal.at(vertex));
        rb::wt::write_words(output / (expected.name == "rank" ? "gathered_external.u32le" : "payload_external.u32le"), external);
      }
    }
  }
};
}  // namespace original_r_k4
