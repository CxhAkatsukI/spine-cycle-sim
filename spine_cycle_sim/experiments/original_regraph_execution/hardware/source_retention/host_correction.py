"""CPU qualification for the opt-in, old-graph-only resident correction cache."""

import argparse
import json
import os
from pathlib import Path
import subprocess

from .follow import unchanged
from .runtime import identity, save


PASS = "CPU_CORRECTION_BIT_EXACT_NOT_FPGA"
FILES = ("Makefile", "host_resident_benchmark.hpp", "host_resident_pagerank_correction.hpp",
         "host_resident_pagerank_correction_test.cpp", "host_resident_benchmark_test.cpp",
         "host_partitioned_algorithms_smoke.cpp", "host_split.hpp", "xcl2.cpp")


def validate_test_logs(correction, resident):
    marker = "RESIDENT_CORRECTION_TEST_PASS cases=160 bit_exact_seed=1 "
    if correction.count(marker) != 1 or "scope=offboard_not_fpga" not in correction:
        raise ValueError("160 bit-exact correction cases required")
    if resident.count("RESIDENT_BENCHMARK_HOST_TEST_PASS algorithm=2 scope=offboard_driver_only") != 1:
        raise ValueError("Residual PR host-driver regression required")
    if "RESIDENT_CORRECTION mode=old_incoming_fp32_replay" not in resident:
        raise ValueError("driver test did not exercise the opt-in correction cache")


def qualify(source, host, correction_test, resident_test, output):
    output.mkdir(parents=True, exist_ok=False)
    pins = [identity(source / name) for name in FILES]
    pins += [identity(host), identity(correction_test), identity(resident_test), identity(__file__)]
    report = dict(status="RUNNING_CPU_TESTS", pins=pins, host=identity(host), tests={},
                  preparation_scope="old_graph_and_old_rank_only_single_batch",
                  fpga_correctness_measured=False)
    save(output / "qualification.json", report)
    try:
        env = dict(os.environ, LD_LIBRARY_PATH="/opt/xilinx/xrt/lib")
        for name, binary in (("correction", correction_test), ("resident", resident_test)):
            unchanged(pins)
            command = ["/usr/bin/taskset", "-c", "124,125", str(binary)]
            with (output / (name + ".stdout.txt")).open("x") as stdout, \
                    (output / (name + ".stderr.txt")).open("x") as stderr:
                subprocess.run(command, env=env, stdout=stdout, stderr=stderr, check=True, timeout=30)
            report["tests"][name] = dict(command=command,
                stdout=identity(output / (name + ".stdout.txt")),
                stderr=identity(output / (name + ".stderr.txt")))
        validate_test_logs(*(Path(report["tests"][name]["stdout"]["path"]).read_text()
                             for name in ("correction", "resident")))
        unchanged(pins)
        report["status"] = PASS
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(output / "qualification.json", report)
    return report


def admit(path, host):
    report = json.loads(path.read_text())
    if (report["status"], report["host"], report["preparation_scope"],
            report["fpga_correctness_measured"]) != (PASS, identity(host),
                "old_graph_and_old_rank_only_single_batch", False):
        raise ValueError("qualified old-graph-only correction host required")
    pins = [identity(path), *report["pins"]]
    pins.extend(pin for test in report["tests"].values() for pin in (test["stdout"], test["stderr"]))
    unchanged(pins)
    validate_test_logs(*(Path(report["tests"][name]["stdout"]["path"]).read_text()
                         for name in ("correction", "resident")))
    return pins


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "host", "correction-test", "resident-test", "output"):
        parser.add_argument("--" + name, type=lambda s: Path(s).resolve(), required=True)
    args = parser.parse_args()
    print(qualify(args.source, args.host, args.correction_test, args.resident_test, args.output)["status"])
