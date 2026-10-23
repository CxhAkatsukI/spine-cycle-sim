"""Build one frozen three-algorithm harness, then run finite comparison pairs."""

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import struct
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ....upstream_controls.execution import run_bounded
from ...r_credits.freeze import ROOT, pin
from ...r_bank_stream import runtime
from .. import analysis
from ..study import DRAM, SST
from . import matrix


def residual_threshold(value):
    """Record the actual FP32 per-vertex threshold shared by both device arms."""
    try:
        rounded = struct.unpack("<f", struct.pack("<f", float(value)))[0]
    except (ValueError, TypeError, OverflowError, struct.error) as error:
        raise ValueError("positive finite FP32 residual epsilon required") from error
    if not math.isfinite(rounded) or rounded <= 0:
        raise ValueError("positive finite FP32 residual epsilon required")
    return rounded


def run(output, core, cpu, timeout, datasets, algorithms, memory_profile, smoke_only=False,
        residual_epsilon=1e-6):
    if cpu not in os.sched_getaffinity(0) or timeout <= 0:
        raise ValueError("allowed CPU and positive timeout required")
    epsilon = residual_threshold(residual_epsilon)
    cases = [] if smoke_only else matrix.cases(datasets, algorithms)
    selected = runtime.settings(memory_profile, 1)
    process_gib = 32 if memory_profile == runtime.LARGE_CPU else 4
    compiler = Path("/usr/bin/g++").resolve()
    dram_config = ROOT / "configs/memory/HBM2_1ch_x128_summary_only.ini"
    output.mkdir(parents=True, exist_ok=False)
    (output / "build").mkdir()
    sources = sorted(p for owner in ("cpp", "spine_cycle_sim/experiments/evaluation_impact/figure_refresh")
        for p in (ROOT / owner).rglob("*") if p.is_file() and p.suffix in (".cpp", ".hpp", ".py"))
    sources += [ROOT / "CMakeLists.txt", ROOT / "cpp/CMakeLists.txt", ROOT / "cpp/sst/Makefile", dram_config]
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for path in sources:
            archive.add(path, arcname=path.relative_to(ROOT), recursive=False)
    pins = [pin(p) for p in sources] + [pin(output / "sources.tar.gz"), pin(compiler),
        pin(SST), pin(DRAM / "libdramsim3.so"), pin(DRAM / "src/dramsim3.h"),
        pin(Path(runtime.__file__)), pin(ROOT / "spine_cycle_sim/experiments/upstream_controls/execution.py")]
    pins += [pin(p) for p in sorted({Path(c[k]) for c in cases for k in ("graph", "update_file", "manifest")})]
    report = dict(status="RUNNING", baseline_admitted=False, pins=pins, matrix=cases,
        rows=[], failures=[], steps=[], smokes=[], cpu=cpu, case_timeout_seconds=timeout,
        memory_profile=memory_profile, process_limit_gib=process_gib,
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        model=dict(clock_mhz=150, memory="Direct DRAMSim3, all 32 channels, 512 MiB/channel, 32 outstanding/channel",
            g="finite natural-geometry/shared-metadata G; original-G performance not admitted",
            r="prefetch_gather_reuse, algorithm-specific finite apply and timed PR preparation",
            spine="Candidate10OnePass; device-active and owner closure",
            correction="Spine residual correction is oracle-directed timed work replay, not a functional AXI-derived seed implementation",
            residual_contract="hardware-warm dangling L-infinity, fixed per-vertex epsilon, damping=FP32(0.85)",
            residual_epsilon=epsilon,
            rank_oracle="independent double Jacobi; L1 error <= V*epsilon/(1-damping)",
            resource_control="latest R resource budget, not a strict same-resource original-A4 reproduction",
            boundary="resident old convergence, batch maintenance and device preparation through new convergence; no host time",
            pma_reservation="exact future batch and zero-source reservation convention retained from SSSP study",
            energy="all-32-channel DRAMSim3 total incl. background/refresh; modeled HBM, not measured FPGA energy"))

    def save():
        atomic_write_json(output / "results.json", report)

    def execute(command, name, seconds):
        step = run_bounded(command, ROOT, output / "raw" / name, timeout=seconds,
                           memory_gib=process_gib, reserve_gib=24)
        report["steps"].append(step)
        save()
        return step

    def invoke(case, arm, name):
        directory = output / name
        directory.mkdir()
        params = dict(arm=arm, algorithm=case["algorithm"], graph=case["graph"],
            updates=case.get("update_file", ""), output=str(directory),
            root=case.get("root", 0), residual_epsilon=epsilon,
            dram_config=str(dram_config), maximum=150000000)
        atomic_write_json(directory / "config.json", params)
        print("START " + name, flush=True)
        step = execute(["env", "LD_LIBRARY_PATH=" + str(DRAM), "taskset", "-c", str(cpu), str(SST),
            "--no-env-config", "--add-lib-path=" + str(output / "build"),
            str(Path(__file__).with_name("sst_config.py")), "--", str(directory / "config.json")], name, timeout)
        row = analysis.device(step)
        row.update(energy_pj=analysis.energy(directory), energy_details=analysis.energy_details(directory),
                   evidence=str(directory), final_state=pin(directory / "final.u32le"),
                   state_hashes={name: pin(directory / (name + ".u32le"))["sha256"]
                                 for name in ("old_state", "expected", "final")})
        print("DONE " + name + " " + json.dumps(row), flush=True)
        return row

    save()
    try:
        with runtime.reservation(output, selected) as guard:
            report["admission"] = guard
            step = execute(["cmake", "--build", str(core), "--parallel", "2", "--target",
                            "spine_cycle_core", "original_regraph_cycle"], "core", 600)
            if step["exit_code"] or step["timed_out"]:
                raise ValueError("core build failed")
            libraries = [core / "cpp" / name for name in ("liboriginal_regraph_cycle.a", "libspine_cycle_core.a")]
            pins.extend(pin(p) for p in libraries)
            command = [str(compiler), "-std=gnu++20", "-O3", "-DNDEBUG", "-fPIC", "-shared",
                "-DHAVE_CONFIG_H", "-DSPINE_HAVE_DIRECT_DRAMSIM3", "-I/data/feiyang/sst/include",
                "-I" + str(ROOT / "cpp/include"), "-I" + str(DRAM / "src"),
                str(ROOT / "cpp/tests/evaluation_impact/figure_refresh/multialgorithm/component.cpp"),
                *[str(ROOT / "cpp/sst" / n) for n in ("sst_memory_backend.cpp", "physical_hbm_mapper.cpp", "direct_dramsim3_engine.cpp")],
                *map(str, libraries), "-L" + str(DRAM), "-Wl,-rpath," + str(DRAM), "-ldramsim3",
                "-o", str(output / "build/libfigure_multi.so")]
            step = execute(command, "plugin", 360)
            if step["exit_code"] or step["timed_out"]:
                raise ValueError("fresh multialgorithm harness compilation failed")
            pins.append(pin(output / "build/libfigure_multi.so"))
            for algorithm in algorithms:
                for arm in ("spine", "gr"):
                    report["smokes"].append(invoke(dict(graph="smoke", algorithm=algorithm), arm,
                                                   "smoke_" + algorithm + "_" + arm))
                    save()
            for case in cases:
                name = "fig9_" + case["algorithm"] + "_" + case["dataset"] + "_u8"
                arms = {}
                for arm in ("spine", "gr"):
                    try:
                        arms[arm] = invoke(case, arm, name + "_" + arm)
                    except (ValueError, RuntimeError) as error:
                        report["failures"].append(dict(case=name, arm=arm, error=repr(error)))
                        save()
                if len(arms) == 2 and any(arms["spine"]["state_hashes"][k] != arms["gr"]["state_hashes"][k]
                                          for k in ("old_state", "expected")):
                    raise ValueError("arms do not share the same initial state and independent expected result")
                row = analysis.comparison(case, arms) if len(arms) == 2 else dict(
                    case=case, status="INCOMPLETE_RETAINED", arms=arms)
                report["rows"].append(row)
                save()
            if any(pin(Path(p["path"])) != p for p in pins):
                raise ValueError("pinned sources, input or dependency changed during run")
            report["pins_unchanged"] = True
            report["status"] = "COMPLETE_SUPPORTED_SCOPE" if not report["failures"] else "PARTIAL_RETAINED"
            save()
    except Exception as error:
        report["status"] = "FAILED_RETAINED"
        report["failures"].append(dict(error=repr(error)))
        save()
        raise
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--datasets", nargs="+", choices=("AU", "SU", "WK"), default=("AU", "SU", "WK"))
    parser.add_argument("--algorithms", nargs="+", choices=("SSSP", "CC", "ResPR"), default=("SSSP", "CC", "ResPR"))
    parser.add_argument("--memory-profile", choices=(runtime.FRESH_CPU, runtime.LARGE_CPU), default=runtime.FRESH_CPU)
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--residual-epsilon", type=residual_threshold, default=1e-6,
                        help="Fixed per-vertex ResPR threshold; historical setting is 1e-6 (no division by V)")
    args = parser.parse_args()
    print(json.dumps(dict(status=run(args.output.resolve(), args.core.resolve(), args.cpu, args.timeout,
        args.datasets, args.algorithms, args.memory_profile, args.smoke_only, args.residual_epsilon)["status"])))
