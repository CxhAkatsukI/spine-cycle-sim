#pragma once

#define CL_HPP_CL_1_2_DEFAULT_BUILD
#define CL_HPP_TARGET_OPENCL_VERSION 120
#define CL_HPP_MINIMUM_OPENCL_VERSION 120
#define CL_HPP_ENABLE_PROGRAM_CONSTRUCTION_FROM_ARRAY_COMPATIBILITY 1
#include <CL/opencl.hpp>
#include <CL/cl_ext_xilinx.h>

#include "model.hpp"
#include <charconv>
#include <cstdlib>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

namespace original_g_board {
inline void checked(cl_int error, const char* operation) {
  if (error != CL_SUCCESS) throw std::runtime_error(std::string(operation) + " OpenCL error=" + std::to_string(error));
}

inline unsigned number(std::string_view text) {
  unsigned value{}; const auto parsed = std::from_chars(text.data(), text.data() + text.size(), value);
  require(parsed.ec == std::errc{} && parsed.ptr == text.data() + text.size(), "unsigned integer required");
  return value;
}

inline void require_lease(unsigned index) {
  require(index < 2, "known G board index required");
  const auto* value = std::getenv("ORIGINAL_G_LEASE_FD");
  require(value != nullptr, "external original G board lease required");
  const auto fd = number(value); require(fd <= INT32_MAX, "invalid original G lease descriptor");
  struct stat descriptor{}, path{};
  const auto lock = "/tmp/chuxiao-sharded-k4-board-" + std::to_string(index) + ".lock";
  require(fstat(fd, &descriptor) == 0 && stat(lock.c_str(), &path) == 0 && S_ISREG(descriptor.st_mode) &&
          descriptor.st_dev == path.st_dev && descriptor.st_ino == path.st_ino && flock(fd, LOCK_EX | LOCK_NB) == 0,
          "original G lease does not exclusively lock requested board");
}

struct Session {
  cl::Device device;
  std::string bdf;
  cl::Context context;
  cl::Program program;
  cl::CommandQueue queue;

  Session(const std::filesystem::path& xclbin, unsigned index) {
    require_lease(index);
    std::vector<cl::Platform> platforms; checked(cl::Platform::get(&platforms), "enumerate platforms");
    std::vector<cl::Device> devices;
    for (const auto& platform : platforms) {
      cl_int error = CL_SUCCESS; const auto name = platform.getInfo<CL_PLATFORM_NAME>(&error); checked(error, "platform name");
      if (name != "Xilinx") continue;
      checked(platform.getDevices(CL_DEVICE_TYPE_ACCELERATOR, &devices), "enumerate devices"); break;
    }
    require(index < devices.size(), "original G Xilinx device unavailable"); device = devices[index];
    cl_int error = CL_SUCCESS; const auto name = device.getInfo<CL_DEVICE_NAME>(&error); checked(error, "device name");
    require(name.find("u55c") != std::string::npos, "original G control requires U55C");
    std::array<char, 128> address{};
    checked(clGetDeviceInfo(device(), CL_DEVICE_PCIE_BDF, address.size(), address.data(), nullptr), "query G BDF");
    require(address.back() == '\0', "unterminated G BDF"); bdf = address.data();
    const auto* expected = std::getenv("ORIGINAL_G_EXPECT_BDF");
    require(expected && bdf == expected, "original G BDF differs from exclusive lease");
    context = cl::Context(device, nullptr, nullptr, nullptr, &error); checked(error, "create G context");
    queue = cl::CommandQueue(context, device, CL_QUEUE_PROFILING_ENABLE | CL_QUEUE_OUT_OF_ORDER_EXEC_MODE_ENABLE, &error);
    checked(error, "create original G out-of-order queue");
    require(!std::filesystem::is_symlink(xclbin) && std::filesystem::is_regular_file(xclbin), "regular original G xclbin required");
    const auto size = std::filesystem::file_size(xclbin);
    require(size > 0 && size < 128ull * 1024 * 1024, "bounded original G xclbin required");
    std::vector<unsigned char> binary(size); std::ifstream stream(xclbin, std::ios::binary);
    require(bool(stream.read(reinterpret_cast<char*>(binary.data()), size)), "read original G xclbin");
    program = cl::Program(context, {device}, cl::Program::Binaries{{binary.data(), binary.size()}}, nullptr, &error);
    checked(error, "program exclusively leased original G board");
  }

  cl::Kernel kernel(const std::string& name) {
    cl_int error = CL_SUCCESS; cl::Kernel result(program, name.c_str(), &error); checked(error, "bind original G kernel"); return result;
  }
  template<class T> cl::Buffer buffer(unsigned bank, const std::vector<T>& values, cl_mem_flags flags) {
    require(bank < 4 && !values.empty() && values.size() * sizeof(T) <= 64ull * 1024 * 1024, "bounded G bank allocation");
    cl_mem_ext_ptr_t extension{}; extension.flags = bank | XCL_MEM_TOPOLOGY;
    cl_int error = CL_SUCCESS;
    cl::Buffer result(context, flags | CL_MEM_EXT_PTR_XILINX, values.size() * sizeof(T), &extension, &error);
    checked(error, "allocate original G buffer");
    checked(queue.enqueueWriteBuffer(result, CL_TRUE, 0, values.size() * sizeof(T), values.data()), "preload original G buffer");
    return result;
  }
  template<class T> void verify(const cl::Buffer& buffer, const std::vector<T>& expected) {
    std::vector<T> observed(expected.size());
    checked(queue.enqueueReadBuffer(buffer, CL_TRUE, 0, observed.size() * sizeof(T), observed.data()), "full G readback");
    require(observed == expected, "original G complete buffer or guard mismatch");
  }
};
}  // namespace original_g_board
