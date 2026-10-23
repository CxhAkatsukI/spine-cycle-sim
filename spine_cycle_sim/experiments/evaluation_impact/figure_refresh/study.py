"""Generate fresh Fig. 8 and supported Fig. 9 data with bounded direct DRAMSim3."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...upstream_controls.execution import run_bounded
from ..r_credits.freeze import ROOT, pin
from ..r_bank_stream import cached_core, runtime
from . import analysis, matrix

DRAM = Path("/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729")
SST = Path("/data/feiyang/sst/bin/sst")


def run(output, reference, cpu, timeout, datasets=(), memory_profile=runtime.FRESH_CPU, figures=(8, 9)):
    if cpu not in os.sched_getaffinity(0):
        raise ValueError("CPU outside allowed affinity")
    compiler = Path("/usr/bin/g++").resolve()
    core, pins = cached_core.validate_convergence(ROOT, reference, compiler,
        complete_status="GATHER_REUSE_COMPLETE_SIMULATOR_PREDICTION")
    output.mkdir(parents=True, exist_ok=False)
    (output / "build").mkdir()
    sources = sorted(p for owner in ("cpp/tests/evaluation_impact", "cpp/sst",
        "spine_cycle_sim/experiments/evaluation_impact/figure_refresh") for p in (ROOT / owner).rglob("*")
        if p.is_file() and p.suffix in (".cpp", ".hpp", ".py"))
    dram_config = ROOT / "configs/memory/HBM2_1ch_x128_summary_only.ini"
    sources += [dram_config]
    pins += [pin(p) for p in sources] + [pin(DRAM / "libdramsim3.so"),
        pin(DRAM / "src/dramsim3.h"), pin(SST)]
    cases = matrix.cases()
    if datasets:
        if set(datasets) - matrix.DATASETS.keys():
            raise ValueError("unknown dataset selection")
        cases = [case for case in cases if case["dataset"] in datasets]
    cases = [case for case in cases if case["figure"] in figures]
    if timeout <= 0 or not cases:
        raise ValueError("positive timeout and nonempty case selection required")
    selected = runtime.settings(memory_profile, 1)
    process_gib = 32 if memory_profile == runtime.LARGE_CPU else 4
    pins += [pin(Path(runtime.__file__)), pin(ROOT / "spine_cycle_sim/experiments/upstream_controls/execution.py")]
    paths = {Path(c[key]) for c in cases for key in ("graph", "update_file", "manifest")}
    pins += [pin(p) for p in sorted(paths)]
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for path in sources:
            archive.add(path, arcname=path.relative_to(ROOT), recursive=False)
    pins.append(pin(output / "sources.tar.gz"))
    report = dict(status="RUNNING", baseline_admitted=False, pins=pins, rows=[], failures=[], steps=[],
        matrix=cases, unsupported=matrix.unsupported(), cpu=cpu, memory_profile=memory_profile,
        process_limit_gib=process_gib, case_timeout_seconds=timeout,
        core_rebuilt=False, reused_core_tests=37,
        model=dict(g="natural-geometry finite direct RMW; shared metadata; not copied-metadata cached prototype",
            r="prefetch_gather_reuse; SSSP only; default-off prediction", spine="Candidate10OnePass device-active",
            memory="Direct DRAMSim3 feedback, 32 channels per arm, 512 MiB/channel, 32 outstanding/channel",
            clock_mhz=150, host_repetitions=5, initial_h2d="logical graph/PMA payload convention, not padded BO DMA",
            host_boundary="full initial physical-image generation plus batch ordering; parsing/oracle/runtime allocation/readback excluded",
            pma_reservation="exact future insertion batch used to reserve resident PMA space before device window",
            energy="DRAMSim3 total including background on ALL 32 budget channels, not measured FPGA power"),
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
    def save():
        atomic_write_json(output / "results.json", report)
    def execute(command, name, seconds):
        step = run_bounded(command, ROOT, output / "raw" / name,
                           timeout=seconds, memory_gib=process_gib, reserve_gib=24)
        report["steps"].append(step)
        save()
        return step
    def invoke(case, arm, mode, name):
        directory = output / name
        directory.mkdir()
        params = dict(mode=mode, arm=arm, graph=case["graph"], updates=case.get("update_file", ""),
            root=case.get("root", 0), output=str(directory), dram_config=str(dram_config), maximum=150000000)
        atomic_write_json(directory / "config.json", params)
        print("START " + name, flush=True)
        step = execute(["env", "LD_LIBRARY_PATH=" + str(DRAM), "taskset", "-c", str(cpu),
            str(SST), "--no-env-config", "--add-lib-path=" + str(output / "build"),
            str(Path(__file__).with_name("sst_config.py")), "--", str(directory / "config.json")], name, timeout)
        row = analysis.host(step) if mode == "host" else analysis.device(step)
        if mode != "host":
            row["energy_pj"] = analysis.energy(directory)
        row["evidence"] = str(directory)
        print("DONE " + name + " " + json.dumps(row), flush=True)
        return row
    save()
    try:
        with runtime.reservation(output, selected) as guard:
            report["admission"] = guard
            command = [str(compiler), "-std=gnu++20", "-O3", "-DNDEBUG", "-fPIC", "-shared",
                "-DHAVE_CONFIG_H", "-DSPINE_HAVE_DIRECT_DRAMSIM3", "-I/data/feiyang/sst/include",
                "-I" + str(ROOT / "cpp/include"), "-I" + str(DRAM / "src"),
                str(ROOT / "cpp/tests/evaluation_impact/figure_refresh/component.cpp"),
                *[str(ROOT / "cpp/sst" / name) for name in ("sst_memory_backend.cpp", "physical_hbm_mapper.cpp", "direct_dramsim3_engine.cpp")],
                str(core / "liboriginal_regraph_cycle.a"), str(core / "libspine_cycle_core.a"),
                "-Wl,--wrap=_ZN5spine3sim13MemoryBackend18initialize_payloadEmmRKSt6vectorIhSaIhEE",
                "-L" + str(DRAM), "-Wl,-rpath," + str(DRAM), "-ldramsim3", "-o", str(output / "build/libfigure_refresh.so")]
            step = execute(command, "build", 240)
            if step["exit_code"] or step["timed_out"]:
                raise ValueError("fresh harness compilation failed")
            pins.append(pin(output / "build/libfigure_refresh.so"))
            for mode in ("update", "propagation", "host"):
                for arm in ("spine", "gr"):
                    invoke(dict(graph="smoke"), arm, mode, f"smoke_{mode}_{arm}")
            for case in cases:
                name = f"fig{case['figure']}_{case['dataset']}_u{case['updates']}"
                arms = {}
                for arm in ("spine", "gr"):
                    try:
                        mode = "update" if case["figure"] == 8 else "propagation"
                        arms[arm] = invoke(case, arm, mode, name + "_" + arm)
                        if case["figure"] == 8:
                            arms[arm]["host"] = invoke(case, arm, "host", name + "_host_" + arm)
                    except (ValueError, RuntimeError) as error:
                        report["failures"].append(dict(case=name, arm=arm, error=repr(error)))
                        save()
                if set(arms) == {"spine", "gr"} and (case["figure"] != 8 or all("host" in r for r in arms.values())):
                    report["rows"].append(analysis.comparison(case, arms))
                else:
                    report["rows"].append(dict(case=case, status="INCOMPLETE_RETAINED", arms=arms))
                save()
            if any(pin(Path(p["path"])) != p for p in pins):
                raise ValueError("frozen source, input or dependency changed during run")
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
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--datasets", nargs="+", choices=tuple(matrix.DATASETS), default=())
    parser.add_argument("--memory-profile", choices=(runtime.FRESH_CPU, runtime.LARGE_CPU), default=runtime.FRESH_CPU)
    parser.add_argument("--figures", nargs="+", type=int, choices=(8, 9), default=(8, 9))
    args = parser.parse_args()
    print(json.dumps({"status": run(args.output.resolve(), args.reference.resolve(), args.cpu,
        args.timeout, args.datasets, args.memory_profile, args.figures)["status"]}))
