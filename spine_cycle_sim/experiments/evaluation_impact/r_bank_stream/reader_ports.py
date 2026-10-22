"""Fresh-core, bounded comparison of one versus two physical PMA reader ports."""

import argparse
import json
import os
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...upstream_controls.execution import run_bounded
from ..r_credits.freeze import ROOT, pin
from . import cached_core, prefetch_analysis, reader_ports_analysis as analysis
from .runtime import LOCAL, reservation, settings
from .study import COMPILER


def run(output, before, a4_reference, cpu):
    if type(cpu) is not int or cpu not in os.sched_getaffinity(0):
        raise ValueError("one allowed CPU required")
    reference = json.loads(before.read_text())
    a4 = json.loads(a4_reference.read_text())
    if (reference.get("pins_unchanged") is not True or len(reference.get("rows", [])) != 4 or
            reference.get("status") != "PREFETCH_COMPACT_DIAGNOSTIC_COMPLETE_NOT_RETENTION" or
            a4.get("pins_unchanged") is not True or len(a4.get("r_rows", [])) != 32):
        raise ValueError("complete immutable reader and A4 references required")
    inputs = before.parent / "inputs/warm_update"
    expected = {p["path"]: p for p in reference["pins"] if p["path"].startswith(str(inputs) + "/")}
    if set(expected) != {str(p) for p in inputs.iterdir()} or any(
            sha256_file(Path(p)) != record["sha256"] for p, record in expected.items()):
        raise ValueError("reader inputs changed or are unpinned")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(inputs, output / "inputs/warm_update")
    sources = sorted(path for owner in ("cpp", "spine_cycle_sim", "configs", "tests", "scripts", "sst")
                     for path in (ROOT / owner).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    sources.append(ROOT / "CMakeLists.txt")
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for path in sources:
            archive.add(path, arcname=path.relative_to(ROOT), recursive=False)
    report = dict(status="WAITING_FOR_ADMISSION", steps=[], rows=[], cpu=cpu, matrix=analysis.MATRIX,
        boundary="resident post-update PMA through drained weighted packet sinks; one scan; no compute/G/host",
        claim="extra_physical_reader_ports_diagnostic_not_complete_R", baseline_admitted=False,
        pins=[pin(p) for p in sources] + [pin(before), pin(a4_reference), pin(COMPILER.resolve()),
            pin(output / "sources.tar.gz")] + [pin(p) for p in sorted((output / "inputs/warm_update").iterdir())])

    def save():
        atomic_write_json(output / "results.json", report)

    def verify():
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("pinned source, input, binary, compiler or reference changed")

    def checked(command, label, timeout=600):
        print("RUN " + label, flush=True)
        step = run_bounded(command, ROOT, output / "raw" / label, timeout=timeout,
                           memory_gib=4, reserve_gib=24)
        report["steps"].append(step); save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("bounded reader-port check failed: " + label)
        return Path(step["stdout"]).read_text()

    save()
    try:
        with reservation(output, settings(LOCAL, 1), 600) as safety:
            report.update(status="BUILDING_FRESH_CORE", safety=safety); save()
            build = output / "build"
            core = build / "core"
            checked(["cmake", "-S", str(ROOT), "-B", str(core), "-DCMAKE_BUILD_TYPE=Release",
                     "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"], "configure")
            checked(["cmake", "--build", str(core), "-j1"], "build_core", 1800)
            checked(["ctest", "--test-dir", str(core), "--output-on-failure", "--timeout", "600", "-j1"],
                    "core_ctest", 2400)
            libraries = {name: core / "cpp" / ("lib" + name + ".a")
                         for name in ("spine_cycle_core", "original_regraph_cycle")}
            for source in ("prefetch_compact", "prefetch_compact_test"):
                binary = build / source
                checked(cached_core.command(ROOT, core / "cpp", binary, COMPILER, source), "build_" + source)
                report["pins"].append(pin(binary))
            report["pins"] += [pin(p) for p in libraries.values()] + [
                pin(core / "CMakeCache.txt"), pin(core / "compile_commands.json")]
            stdout = checked(["taskset", "-c", str(cpu), str(build / "prefetch_compact_test")], "synthetic")
            if not all(f"{name} PASS 16 executions" in stdout for name in
                       ("PREFETCH_COMPACT_TEST", "DUAL_PORT_PREFETCH_TEST")):
                raise ValueError("both finite synthetic matrices required")
            report["transport_probes"] = prefetch_analysis.transport_probes(stdout)
            verify(); report["status"] = "RUNNING_COMPLETE_READER_MATRIX"; save()
            for latency, reverse, ports in analysis.MATRIX:
                command = ["taskset", "-c", str(cpu), str(build / "prefetch_compact"),
                    str(output / "inputs/warm_update"), str(latency), str(reverse), "100000000", "1"]
                if ports == 2: command.append("dual-port")
                label = f"lat{latency}_reverse{reverse}_ports{ports}"
                row = prefetch_analysis.parse(checked(command, label))
                report["rows"].append(dict(latency=latency, reverse=reverse, ports=ports, observations=row))
                save(); print("DONE " + label, flush=True)
            report["analysis"] = analysis.summarize(report["rows"], reference["rows"], a4["r_rows"])
            verify(); report.update(status="READER_PORTS_COMPLETE_NOT_R_RETENTION", pins_unchanged=True)
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error)); save()
        raise
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "before", "a4-reference"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps({"status": run(args.output.resolve(), args.before.resolve(),
                                  args.a4_reference.resolve(), args.cpu)["status"]}))
