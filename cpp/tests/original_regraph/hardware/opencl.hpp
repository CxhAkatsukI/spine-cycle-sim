#pragma once

#define CL_HPP_CL_1_2_DEFAULT_BUILD
#define CL_HPP_TARGET_OPENCL_VERSION 120
#define CL_HPP_MINIMUM_OPENCL_VERSION 120
#define CL_HPP_ENABLE_PROGRAM_CONSTRUCTION_FROM_ARRAY_COMPATIBILITY 1
#include <CL/opencl.hpp>
#include <CL/cl_ext_xilinx.h>

#include "events.hpp"
#include <charconv>
#include <cstdlib>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

namespace original_r_board {
inline void checked(cl_int error, const char* operation) {
  if (error != CL_SUCCESS)
    throw std::runtime_error(std::string(operation) + " OpenCL error=" + std::to_string(error));
}

inline unsigned number(std::string_view value) {
  unsigned result{};
  const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
  require(parsed.ec == std::errc{} && parsed.ptr == value.data() + value.size(), "unsigned integer required");
  return result;
}

inline void require_lease(unsigned index) {
  require(index < 2, "known board index required");
  const auto* value = std::getenv("ORIGINAL_R_LEASE_FD");
  require(value != nullptr, "external exclusive board lease required; do not launch directly");
  const auto fd = number(value);
  require(fd <= INT32_MAX, "invalid lease descriptor");
  struct stat descriptor{}, path{};
  const auto lock = "/tmp/chuxiao-sharded-k4-board-" + std::to_string(index) + ".lock";
  require(fstat(fd, &descriptor) == 0 && stat(lock.c_str(), &path) == 0 && S_ISREG(descriptor.st_mode) &&
          descriptor.st_dev == path.st_dev && descriptor.st_ino == path.st_ino &&
          flock(fd, LOCK_EX | LOCK_NB) == 0, "lease descriptor does not exclusively lock requested board");
}

struct Event {
  std::string role;
  unsigned ordinal{}, lane{};
  cl::Event event;
  Times times() const {
    std::array<cl_ulong, 4> result{};
    constexpr std::array<cl_profiling_info, 4> names{CL_PROFILING_COMMAND_QUEUED, CL_PROFILING_COMMAND_SUBMIT,
                                                    CL_PROFILING_COMMAND_START, CL_PROFILING_COMMAND_END};
    for (unsigned i = 0; i < names.size(); ++i)
      checked(event.getProfilingInfo(names[i], &result[i]), "profile kernel event");
    Times times{result[0], result[1], result[2], result[3]}; times.validate();
    return times;
  }
};

struct Session {
  cl::Device device;
  std::string bdf;
  cl::Context context;
  cl::Program program;
  cl::CommandQueue transfers, wrapper, apply;
  std::vector<cl::CommandQueue> lanes;

  Session(const std::filesystem::path& xclbin, unsigned index, unsigned lane_count) {
    require_lease(index);
    require(lane_count == 14 || lane_count == 4, "only the reviewed 11+3 or generated A4 hardware ABI is supported");
    std::vector<cl::Platform> platforms;
    checked(cl::Platform::get(&platforms), "enumerate platforms");
    std::vector<cl::Device> devices;
    for (const auto& platform : platforms) {
      cl_int error = CL_SUCCESS;
      const auto name = platform.getInfo<CL_PLATFORM_NAME>(&error); checked(error, "platform name");
      if (name != "Xilinx") continue;
      checked(platform.getDevices(CL_DEVICE_TYPE_ACCELERATOR, &devices), "enumerate devices"); break;
    }
    require(index < devices.size(), "requested Xilinx board unavailable");
    device = devices[index];
    cl_int error = CL_SUCCESS;
    const auto name = device.getInfo<CL_DEVICE_NAME>(&error); checked(error, "device name");
    require(name.find("u55c") != std::string::npos, "U55C required");
    std::array<char, 128> address{};
    checked(clGetDeviceInfo(device(), CL_DEVICE_PCIE_BDF, address.size(), address.data(), nullptr), "query BDF");
    require(address.back() == '\0', "unterminated device BDF"); bdf = address.data();
    const auto* expected = std::getenv("ORIGINAL_R_EXPECT_BDF");
    require(expected && bdf == expected, "BDF differs from exclusive board lease");
    context = cl::Context(device, nullptr, nullptr, nullptr, &error); checked(error, "create context");
    lanes.resize(lane_count);
    for (auto* queue : {&transfers, &wrapper, &apply}) {
      *queue = cl::CommandQueue(context, device, CL_QUEUE_PROFILING_ENABLE, &error); checked(error, "create queue");
    }
    for (auto& queue : lanes) {
      queue = cl::CommandQueue(context, device, CL_QUEUE_PROFILING_ENABLE, &error); checked(error, "create lane queue");
    }
    require(!std::filesystem::is_symlink(xclbin) && std::filesystem::is_regular_file(xclbin), "regular xclbin required");
    const auto size = std::filesystem::file_size(xclbin);
    require(size > 0 && size < 128ull * 1024 * 1024, "bounded xclbin required");
    std::vector<unsigned char> binary(size);
    std::ifstream stream(xclbin, std::ios::binary);
    require(bool(stream.read(reinterpret_cast<char*>(binary.data()), size)), "read xclbin failed");
    program = cl::Program(context, {device}, cl::Program::Binaries{{binary.data(), binary.size()}}, nullptr, &error);
    checked(error, "program exclusively leased device");
  }

  cl::Kernel kernel(const std::string& name) {
    cl_int error = CL_SUCCESS;
    cl::Kernel result(program, name.c_str(), &error); checked(error, "bind original kernel"); return result;
  }
  cl::Buffer buffer(unsigned bank, const Words& words, cl_mem_flags flags) {
    require(bank < 32 && !words.empty() && words.size() * 4 < 256ull * 1024 * 1024, "bounded HBM allocation required");
    cl_mem_ext_ptr_t extension{}; extension.flags = bank | XCL_MEM_TOPOLOGY;
    cl_int error = CL_SUCCESS;
    cl::Buffer result(context, flags | CL_MEM_EXT_PTR_XILINX, words.size() * 4, &extension, &error);
    checked(error, "allocate original HBM buffer");
    checked(transfers.enqueueWriteBuffer(result, CL_TRUE, 0, words.size() * 4, words.data()), "upload guarded input");
    return result;
  }
  Words read(const cl::Buffer& buffer, std::size_t words) {
    Words result(words);
    checked(transfers.enqueueReadBuffer(buffer, CL_TRUE, 0, words * 4, result.data()), "complete guarded readback");
    return result;
  }
};
}  // namespace original_r_board
