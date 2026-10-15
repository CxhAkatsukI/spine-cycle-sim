"""Bounded XRT-host compilation and resident handoff preflight; never programs FPGA."""

import argparse
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities, run_bounded
from ..search_pipeline.synthesis import unchanged
from .analysis import CLAIMS, PASS, UNIT_PASS, analyze
from .preparation import command, prepare


def run(output, upstream, integration, xrt):
    compiler = shutil.which("g++")
    if not compiler or not (xrt / "include/CL/cl_ext_xilinx.h").is_file():
        raise ValueError("G++ and installed XRT required")
    pins, contract = prepare(output, upstream, integration)
    report = {"status": "PREPARED", "source": pins, "contract": contract, "steps": [], "cases": [],
              "errors": [], **dict.fromkeys(CLAIMS, False),
              "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
              "resources": {"memory_max_gib": 4, "memory_high_gib": 3, "reserve_gib": 104,
                            "swap_max_bytes": 0, "cpu_affinity": [124, 125], "timeout_seconds_per_step": 900},
              "scope": "host functional preflight only; no FPGA API or production kernel executed"}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    binary, unit = output / "probe", output / "resident-test"
    source = output / "source/continuous_handoff"
    try:
        stages = [("unit-compile", [compiler, "-std=c++20", "-O2", "-g0", "-Wall", "-Wextra", "-Werror",
                    "-D_GLIBCXX_ASSERTIONS", "-fsanitize=undefined", "-fno-sanitize-recover=all", "-MD", "-MF",
                    str(unit.with_suffix(".d")), "-MT", "probe", f"-I{output / 'source'}",
                    str(source / "resident_test.cpp"), "-o", str(unit)]),
                  ("unit", [str(unit)]), ("compile", command(output / "source", xrt, compiler, binary))]
        stages += [(row["case"], [str(binary), "--model-check", row["input"]]) for row in contract["cases"]]
        for label, argv in stages:
            unchanged(pins)
            report["status"] = "RUNNING_" + label
            save()
            step = run_bounded(["systemd-run", "--user", "--scope", "--quiet",
                "--property=MemoryHigh=3G", "--property=MemoryMax=4G", "--property=MemorySwapMax=0",
                "--property=OOMPolicy=kill", "env", "MALLOC_ARENA_MAX=2", "taskset", "-c", "124,125", *argv],
                output, output / label, timeout=900, memory_gib=4, reserve_gib=104)
            report["steps"].append({"label": label, **step})
            save()
            stdout, stderr = (Path(step[key]).read_text() for key in ("stdout", "stderr"))
            if step["exit_code"] or step["timed_out"] or stderr.strip():
                raise ValueError(label + " failed; retained unchanged")
            if label.endswith("compile"):
                if stdout.strip():
                    raise ValueError("unexpected compile diagnostic")
                target = unit if label == "unit-compile" else binary
                report[label + "_binary_sha256"] = sha256_file(target)
                report.setdefault("dependencies", []).extend(dependency_identities(target.with_suffix(".d"), output))
            elif label == "unit":
                if stdout != UNIT_PASS + "\n":
                    raise ValueError("resident policy unit failed")
            else:
                case = next(row for row in contract["cases"] if row["case"] == label)
                report["cases"].append({"case": label, **analyze(case, stdout, stderr)})
            save()
        unchanged(pins + report["dependencies"])
        report["status"] = PASS
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        save()
        raise
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "upstream", "integration", "xrt"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(run(*(path.resolve() for path in (args.output, args.upstream, args.integration, args.xrt)))["status"], flush=True)
