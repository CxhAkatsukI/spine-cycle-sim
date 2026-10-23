"""Freeze a fresh Release core and retain all four numerical regression gates."""

import argparse
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ....upstream_controls.execution import run_bounded
from ...r_bank_stream import runtime
from ...r_credits.freeze import ROOT, pin


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    sources = sorted(p for owner in ("cpp", "spine_cycle_sim/experiments/evaluation_impact/figure_refresh")
        for p in (ROOT / owner).rglob("*") if p.is_file() and p.suffix in (".cpp", ".hpp", ".py"))
    sources += [ROOT / "CMakeLists.txt", ROOT / "cpp/CMakeLists.txt", ROOT / "cpp/sst/Makefile",
                ROOT / "configs/memory/HBM2_1ch_x128_summary_only.ini"]
    archive = output / "sources.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for path in sources:
            handle.add(path, arcname=path.relative_to(ROOT), recursive=False)
    report = dict(status="RUNNING", pins=[pin(p) for p in sources] + [pin(archive)], steps=[])
    def save():
        atomic_write_json(output / "results.json", report)
    save()
    try:
        with runtime.reservation(output, runtime.settings(runtime.FRESH_CPU, 1)) as guard:
            report["admission"] = guard
            build = str(output / "build")
            commands = [
                ("configure", ["cmake", "-S", str(ROOT), "-B", build,
                               "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_TESTING=ON"], 120),
                ("build", ["cmake", "--build", build, "--parallel", "2"], 900),
                ("pagerank", ["ctest", "--test-dir", build, "-R", "routed_pagerank_tests",
                              "--output-on-failure"], 600),
                ("ctest", ["ctest", "--test-dir", build, "--parallel", "2",
                           "--output-on-failure"], 1200),
            ]
            for name, command, timeout in commands:
                print("START " + name, flush=True)
                result = run_bounded(command, ROOT, output / name, timeout=timeout,
                                     memory_gib=4, reserve_gib=24)
                report["steps"].append(result)
                save()
                if result["exit_code"] or result["timed_out"]:
                    raise ValueError(name + " gate failed")
            if any(pin(Path(p["path"])) != p for p in report["pins"]):
                raise ValueError("core source identity changed during gates")
            report.update(status="COMPLETE_CORE_GATES", pins_unchanged=True)
            save()
    except Exception as error:
        report.update(status="FAILED_RETAINED", failures=[repr(error)])
        save()
        raise
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(dict(status=run(args.output.resolve())["status"])))
