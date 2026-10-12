"""Fresh Release build and serial bounded executions; no production-plugin writes."""

from ...a4_control.execution import execute, require_executors
from .contract import HARNESS, LIMITS, TARGETS, label


def commands(root, output):
    return [("compiler", ["g++", "--version"], 1, 30),
            ("configure", ["cmake", "-S", str(root / HARNESS), "-B", str(output / "build"),
                           "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_CXX_COMPILER=/usr/bin/g++",
                           "-DBUILD_TESTING=ON", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"], 6, 300),
            ("build", ["cmake", "--build", str(output / "build"), "--target", *TARGETS, "-j2"], 6, 600)]


def binary_paths(output):
    return {"original": output / "build/simulator/cpp/original_regraph_sssp_real_round",
            "candidate": output / "build/routed_regraph_cross_row_round"}


def case_command(output, mode, latency, reverse, arm):
    binary = binary_paths(output)["original" if arm == "original" else "candidate"]
    command = ["taskset", "-c", LIMITS["affinity"], str(binary), str(output / "inputs" / mode),
               str(output / "states" / label(mode, latency, reverse, arm)), str(latency), str(reverse),
               str(LIMITS["max_cycles"])]
    if arm != "original":
        command.append(str(int(arm == "cross_row")))
    return command
