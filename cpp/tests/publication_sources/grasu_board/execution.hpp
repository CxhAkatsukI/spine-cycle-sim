#pragma once

#include "runtime.hpp"
#include <chrono>
#include <iomanip>
#include <iostream>

namespace original_g_board {
struct Buffers {
  std::array<cl::Buffer, 4> pma, rows, binary, edges;
  std::array<Longs, 4> guarded_edges;
  Buffers(Session& session, const Model& model) {
    for (unsigned i = 0; i < 4; ++i) {
      guarded_edges[i] = model.edges[i]; guarded_edges[i].push_back(0);
      pma[i] = session.buffer(i, model.initial[i], CL_MEM_READ_WRITE);
      rows[i] = session.buffer(i, model.rows, CL_MEM_READ_ONLY);
      binary[i] = session.buffer(i, model.binary, CL_MEM_READ_ONLY);
      edges[i] = session.buffer(i, guarded_edges[i], CL_MEM_READ_ONLY);
    }
    checked(session.queue.finish(), "finish original G preload");
  }
  void verify(Session& session, const Model& model) {
    for (unsigned i = 0; i < 4; ++i) {
      session.verify(pma[i], model.expected[i]); session.verify(rows[i], model.rows);
      session.verify(binary[i], model.binary); session.verify(edges[i], guarded_edges[i]);
    }
  }
};

inline void run(const Input& input, const Model& model, const std::filesystem::path& xclbin, unsigned index) {
  Session session(xclbin, index); Buffers buffers(session, model);
  std::vector<cl::Kernel> kernels;
  std::vector<std::string> roles;
  for (const auto& kind : {"process_cache", "process_ddr", "dispatch", "bin_search"}) {
    const unsigned count = std::string(kind) == "bin_search" ? 4 : std::string(kind) == "dispatch" ? 1 : 2;
    for (unsigned i = 0; i < count; ++i) {
      const auto instance = std::string(kind) + "_" + std::to_string(i + 1);
      kernels.push_back(session.kernel(std::string(kind) + ":{" + instance + "}")); roles.push_back(instance);
    }
  }
  std::vector<cl::Event> events(kernels.size());
  const auto started = std::chrono::steady_clock::now();
  for (unsigned i = 0; i < 2; ++i) {
    checked(kernels[i].setArg(0, buffers.pma[2 * i]), "bind original G cache");
    for (unsigned arg = 0; arg < 4; ++arg)
      checked(kernels[2 + i].setArg(arg, buffers.pma[2 * i + 1]), "bind original G aliased DDR");
  }
  checked(kernels[4].setArg(0, unsigned(input.updates.size())), "bind original G dispatch count");
  for (unsigned i = 0; i < 4; ++i) {
    checked(kernels[5 + i].setArg(0, buffers.edges[i]), "bind original G edges");
    for (unsigned arg = 1; arg <= 4; ++arg) {
      checked(kernels[5 + i].setArg(arg, buffers.binary[i]), "bind original G binary replicas");
      checked(kernels[5 + i].setArg(arg + 4, buffers.rows[i]), "bind original G row replicas");
    }
    checked(kernels[5 + i].setArg(9, unsigned(model.edges[i].size())), "bind original G search count");
  }
  for (unsigned i = 0; i < kernels.size(); ++i)
    checked(session.queue.enqueueTask(kernels[i], nullptr, &events[i]), "enqueue original G concurrent pipeline");
  checked(session.queue.flush(), "flush original G pipeline"); checked(session.queue.finish(), "finish original G pipeline");
  const auto elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
  buffers.verify(session, model);
  std::uint64_t first = UINT64_MAX, last = 0;
  for (unsigned i = 0; i < events.size(); ++i) {
    std::array<cl_ulong, 4> times{};
    constexpr std::array<cl_profiling_info, 4> fields{CL_PROFILING_COMMAND_QUEUED, CL_PROFILING_COMMAND_SUBMIT,
                                                   CL_PROFILING_COMMAND_START, CL_PROFILING_COMMAND_END};
    for (unsigned j = 0; j < fields.size(); ++j) checked(events[i].getProfilingInfo(fields[j], &times[j]), "profile original G");
    require(times[0] <= times[1] && times[1] <= times[2] && times[2] < times[3], "original G invalid event timestamps");
    first = std::min<std::uint64_t>(first, times[2]); last = std::max<std::uint64_t>(last, times[3]);
    std::cout << "ORIGINAL_G_EVENT {\"role\":\"" << roles[i] << "\",\"queued\":" << times[0]
              << ",\"submitted\":" << times[1] << ",\"start\":" << times[2] << ",\"end\":" << times[3] << "}\n";
  }
  std::cout << std::setprecision(17) << "ORIGINAL_G_BOARD {\"status\":\"FULL_STATE_PASS\",\"bdf\":\"" << session.bdf
            << "\",\"updates\":" << input.updates.size() << ",\"checked_slots_including_guards\":" << model.checked_slots
            << ",\"resident_wall_ms\":" << elapsed << ",\"kernel_event_span_ns\":" << last - first
            << ",\"readback_in_wall\":false,\"host_preparation_in_wall\":false,\"events\":" << events.size() << "}\n";
}
}  // namespace original_g_board
