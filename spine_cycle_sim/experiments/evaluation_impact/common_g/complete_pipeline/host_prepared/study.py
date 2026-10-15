"""Bounded real-input complete-G source campaign; never a board timing claim."""

import argparse
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities, run_bounded
from ...search_pipeline.synthesis import unchanged
from .analysis import CLAIMS, PASS, analyze
from .preparation import command, prepare


def run(output, upstream, integration, include):
    compiler = shutil.which("g++")
    if not compiler or not (include / "ap_int.h").is_file():
        raise ValueError("G++ and vendor headers required")
    pins, contract = prepare(output, upstream, integration)
    report = {"status": "PREPARED", "source": pins, "contract": contract, "errors": [], "rows": [],
              "steps": [], **dict.fromkeys(CLAIMS, False),
              "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
              "resources": {"memory_max_gib": 4, "memory_high_gib": 3, "reserve_gib": 104,
                            "swap_max_bytes": 0, "cpu_affinity": [124, 125], "timeout_seconds_per_step": 900},
              "scope": "production_host_headers_to_real_PMA_to_G_to_direct_adapter; source_only",
              "excludes": ["OpenCL/XRT binding", "integrated RTL/backpressure", "FPGA time", "ReGraph compute",
                           "host-inclusive performance", "unseen future reservation", "cold real-trace updates"]}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    binary = output / "probe"
    try:
        stages = [("compile", command(output / "source", include, compiler, binary))]
        stages += [(case["case"], [str(binary), case["case"], case["input"]]) for case in contract["cases"]]
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
            if step["exit_code"] or step["timed_out"]:
                raise ValueError(label + " failed; retained unchanged")
            if label == "compile":
                if Path(step["stdout"]).read_text().strip() or Path(step["stderr"]).read_text().strip():
                    raise ValueError("unexpected compile diagnostic")
                report["binary_sha256"] = sha256_file(binary)
                report["dependencies"] = dependency_identities(binary.with_suffix(".d"), output)
            else:
                case = next(c for c in contract["cases"] if c["case"] == label)
                report["rows"] += analyze(case, Path(step["stdout"]).read_text(), Path(step["stderr"]).read_text())
            save()
        unchanged(pins + report["dependencies"])
        report["status"] = PASS
    except BaseException as error:
        report["errors"].append(repr(error))
        report["status"] = "FAILED_RETAINED"
        save()
        raise
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "upstream", "integration", "hls-include"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(run(*(p.resolve() for p in (args.output, args.upstream, args.integration, args.hls_include)))["status"], flush=True)
