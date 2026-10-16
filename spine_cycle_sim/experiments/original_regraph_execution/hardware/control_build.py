"""Explicit XRT linkage for the guarded original-R host, not a generic ICD."""

from pathlib import Path

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.runtime import library_paths

XRT = Path("/opt/xilinx/xrt")


def runtime_inputs():
    return [(XRT / "lib" / name).resolve(strict=True)
            for name in ("libxilinxopencl.so", "libxrt_core.so.2")]


def command(compiler, source, binary, dependency, build, name):
    if build not in ("release", "ubsan") or name not in ("model_tests", "control"):
        raise ValueError("explicit guarded host build and target required")
    flags = ["-std=c++20", "-O2", "-DNDEBUG", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
    if build == "ubsan":
        flags += ["-fsanitize=undefined", "-fno-sanitize-recover=all"]
    result = [str(compiler), *flags, "-MD", "-MF", str(dependency), "-MT", "probe",
              "-I" + str(XRT / "include"), str(source / (name + ".cpp")), "-o", str(binary)]
    if name == "control":
        result += [str(XRT / "lib/libxilinxopencl.so"), "-Wl,-rpath," + str(XRT / "lib")]
    return result


def resolved_libraries(stdout, stderr):
    if stderr.strip():
        raise ValueError("unexpected guarded host loader diagnostic")
    paths = library_paths(stdout)
    if runtime_inputs()[0] not in paths:
        raise ValueError("guarded host must resolve the explicitly pinned Xilinx OpenCL library")
    return paths
