#pragma once

#define CL_HPP_CL_1_2_DEFAULT_BUILD
#define CL_HPP_TARGET_OPENCL_VERSION 120
#define CL_HPP_MINIMUM_OPENCL_VERSION 120
#define CL_HPP_ENABLE_PROGRAM_CONSTRUCTION_FROM_ARRAY_COMPATIBILITY 1
#include <CL/opencl.hpp>
#include <CL/cl_ext_xilinx.h>

#include "model.hpp"
#include <chrono>
#include <cstdlib>
#include <iostream>

namespace continuous_g {
using Clock = std::chrono::steady_clock;
inline double milliseconds(Clock::time_point begin) {
  return std::chrono::duration<double, std::milli>(Clock::now() - begin).count();
}
inline void checked(cl_int status, const char* operation) {
  if (status != CL_SUCCESS)
    throw std::runtime_error(std::string(operation) + " OpenCL error=" + std::to_string(status));
}

struct Event {
  const char* role;
  unsigned shard;
  cl::Event event;
  std::array<cl_ulong, 4> times() const {
    std::array<cl_ulong, 4> result{};
    const std::array<cl_profiling_info, 4> names{CL_PROFILING_COMMAND_QUEUED,
        CL_PROFILING_COMMAND_SUBMIT, CL_PROFILING_COMMAND_START, CL_PROFILING_COMMAND_END};
    for (unsigned i = 0; i < 4; ++i)
      checked(event.getProfilingInfo(names[i], &result[i]), "profile event");
    check_input(std::is_sorted(result.begin(), result.end()), "event timestamps out of order");
    return result;
  }
};

inline std::array<double, 2> event_window(const std::vector<Event>& events) {
  std::vector<std::pair<cl_ulong, cl_ulong>> intervals;
  for (const auto& event : events) {
    const auto times = event.times();
    intervals.emplace_back(times[2], times[3]);
  }
  if (intervals.empty()) return {0, 0};
  std::sort(intervals.begin(), intervals.end());
  auto end = intervals.front().first;
  cl_ulong busy = 0;
  for (const auto& interval : intervals) {
    if (interval.second > end) busy += interval.second - std::max(interval.first, end);
    end = std::max(end, interval.second);
  }
  return {busy / 1e6, (end - intervals.front().first) / 1e6};
}

struct Session {
  cl::Device device;
  std::string bdf;
  cl::Context context;
  cl::CommandQueue transfers, updates, barriers;
  cl::Program program;
  Session(const char* xclbin, unsigned device_index) {
    check_input(device_index < 2, "known device index required");
    std::vector<cl::Platform> platforms;
    checked(cl::Platform::get(&platforms), "enumerate platforms");
    std::vector<cl::Device> devices;
    for (const auto& platform : platforms) {
      if (platform.getInfo<CL_PLATFORM_NAME>() != "Xilinx") continue;
      checked(platform.getDevices(CL_DEVICE_TYPE_ACCELERATOR, &devices), "enumerate devices");
      break;
    }
    check_input(device_index < devices.size(), "requested Xilinx device unavailable");
    device = devices[device_index];
    check_input(device.getInfo<CL_DEVICE_NAME>().find("u55c") != std::string::npos, "U55C required");
    std::array<char, 128> address{};
    checked(clGetDeviceInfo(device(), CL_DEVICE_PCIE_BDF, address.size(), address.data(), nullptr),
            "query device BDF");
    check_input(address.back() == '\0', "unterminated device BDF");
    bdf = address.data();
    const auto* expected_bdf = std::getenv("CONTINUOUS_G_EXPECT_BDF");
    check_input(expected_bdf && bdf == expected_bdf, "device BDF differs from exclusive board lease");
    cl_int error = CL_SUCCESS;
    context = cl::Context(device, nullptr, nullptr, nullptr, &error);
    checked(error, "create context");
    const auto flags = CL_QUEUE_PROFILING_ENABLE | CL_QUEUE_OUT_OF_ORDER_EXEC_MODE_ENABLE;
    for (auto* queue : {&transfers, &updates, &barriers}) {
      *queue = cl::CommandQueue(context, device, flags, &error);
      checked(error, "create queue");
    }
    std::ifstream stream(xclbin, std::ios::binary | std::ios::ate);
    check_input(bool(stream) && stream.tellg() > 0, "missing/empty xclbin");
    std::vector<unsigned char> bytes(static_cast<std::size_t>(stream.tellg()));
    stream.seekg(0);
    check_input(bool(stream.read(reinterpret_cast<char*>(bytes.data()), bytes.size())), "read xclbin");
    program = cl::Program(context, {device}, cl::Program::Binaries{{bytes.data(), bytes.size()}}, nullptr, &error);
    checked(error, "program device");
  }
  cl::Kernel kernel(const std::string& name) {
    cl_int error = CL_SUCCESS;
    cl::Kernel result(program, name.c_str(), &error);
    checked(error, "bind kernel");
    return result;
  }
  cl::Buffer buffer(unsigned bank, std::size_t bytes, cl_mem_flags flags) {
    check_input(bytes > 0 && bank < 23, "invalid graph buffer geometry");
    cl_mem_ext_ptr_t extension{};
    extension.flags = bank | XCL_MEM_TOPOLOGY;
    cl_int error = CL_SUCCESS;
    cl::Buffer result(context, flags | CL_MEM_EXT_PTR_XILINX, bytes, &extension, &error);
    checked(error, "allocate HBM buffer");
    return result;
  }
};
}  // namespace continuous_g
