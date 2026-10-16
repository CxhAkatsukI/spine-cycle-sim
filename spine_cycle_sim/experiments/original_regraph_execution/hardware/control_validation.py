"""Compile and audit the original-R board-control host offline, in a finite cgroup."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes, dependency_identities, run_bounded
from . import artifact, control_analysis as analysis, control_inputs, study

POLICY = {"tree_memory_gib": 4, "reserve_gib": 24, "background_memory_gib": 8,
          "allow_bounded_builds": True}
COMPILER = Path("/usr/bin/g++").resolve()


def run(root: Path, captures: Path, audit: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARED", "errors": [], "policy": POLICY, "steps": [], "rows": [],
              "negative_controls": [], "pins": [], "board_programmed": False,
              "hardware_timing_measured": False, "publication_match": False}
    lease = None

    def save():
        atomic_write_json(output / "results.json", report)

    def step(name, command, success=True):
        record = run_bounded(command, root, output / "steps" / name,
                             timeout=120, memory_gib=2, reserve_gib=32)
        report["steps"].append({"id": name, **record})
        save()
        if record["timed_out"] or (record["exit_code"] == 0) != success:
            raise ValueError("unexpected bounded control result: " + name)
        return record

    save()
    try:
        group = current()
        report["containment"] = verify(group, memory_gib=POLICY["tree_memory_gib"])
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        report["admission"] = lease.sample(available_memory_bytes(), other_builds(), POLICY, commit=True)
        if not report["admission"]["admitted"]:
            raise ValueError("full finite peer budgets plus reserve do not fit; no compiler launched")
        reference = json.loads((audit / "results.json").read_text())
        if reference["status"] != study.STATUS or reference["errors"]:
            raise ValueError("passing independent original-R offline audit required")
        for pin in reference["pins"]:
            if artifact.identity(Path(pin["path"])) != pin:
                raise ValueError("independent audit provenance changed")
        report["compiler_version"] = subprocess.check_output([str(COMPILER), "--version"], text=True)
        report["source_revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        report["worktree_status"] = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines()
        source = root / "cpp/tests/original_regraph/hardware"
        report["pins"] = [artifact.identity(path) for path in sorted(source.glob("*")) if path.is_file()]
        report["pins"] += [artifact.identity(audit / "results.json"), artifact.identity(COMPILER)]
        report["pins"] += study.runner_pins()
        inputs = control_inputs.admit(captures, reference, output / "inputs")
        report["pins"] += [pin for admitted in inputs.values() for item in admitted for pin in item["pins"]]
        report["inputs"] = inputs
        binary_dir = output / "bin"
        binary_dir.mkdir()
        for build in ("release", "ubsan"):
            flags = ["-std=c++20", "-O2", "-DNDEBUG", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
            if build == "ubsan":
                flags += ["-fsanitize=undefined", "-fno-sanitize-recover=all"]
            for name in ("model_tests", "control"):
                binary, dependency = binary_dir / f"{build}_{name}", binary_dir / f"{build}_{name}.d"
                command = [str(COMPILER), *flags, "-MD", "-MF", str(dependency), "-MT", "probe",
                           "-I/opt/xilinx/xrt/include", str(source / (name + ".cpp")), "-o", str(binary)]
                if name == "control":
                    command += ["-lOpenCL"]
                step(f"compile_{build}_{name}", command)
                report["pins"] += dependency_identities(dependency, root) + [artifact.identity(binary)]
            step(f"{build}_model_tests", [str(binary_dir / f"{build}_model_tests")])
            for topology, admitted in inputs.items():
                for item in admitted:
                    oracle = next(case for case in reference["cases"] if case["id"] == topology + "_" + item["id"])
                    for binding in analysis.BINDINGS:
                        for repetition in range(2):
                            name = f"{build}_{topology}_{item['id']}_{binding}_{repetition}"
                            destination = output / "cases" / name
                            record = step(name, [str(binary_dir / f"{build}_control"), "offline",
                                item["directory"], topology, binding, str(destination)])
                            if Path(record["stderr"]).stat().st_size:
                                raise ValueError("offline control emitted unexpected diagnostics")
                            observed = json.loads((destination / "result.json").read_text())
                            row = {"build": build, "repetition": repetition, "topology": topology,
                                   "graph": item["id"], "binding": binding, "directory": str(destination),
                                   "observation": observed, "analysis": analysis.inspect(observed, destination, oracle)}
                            report["rows"].append(row)
                            save()
                            print("Validated " + name + " (offline, not FPGA)", flush=True)
        analysis.matrix(report["rows"])
        binary = str(binary_dir / "release_control")
        small = inputs["original_example"][0]["directory"]
        for name, command, message in (
            ("missing_lease", ["/usr/bin/env", "-u", "ORIGINAL_R_LEASE_FD", binary, "board", small,
                "original_example", "csr_degree", str(output / "negative_missing_lease"), "/nonexistent.xclbin", "0"],
                "external exclusive board lease required"),
            ("unknown_binding", [binary, "offline", small, "original_example", "implicit",
                str(output / "negative_binding")], "explicit author_initial or csr_degree"),
            ("a4_board_abi", [binary, "board", inputs["a4"][0]["directory"], "a4", "csr_degree",
                str(output / "negative_a4_board"), "/nonexistent.xclbin", "0"], "A4 remains an offline layout"),
        ):
            record = step(name, command, success=False)
            if message not in Path(record["stderr"]).read_text():
                raise ValueError("negative control failed for an unexpected reason: " + name)
            report["negative_controls"].append(name)
        invalid = output / "invalid_input"
        shutil.copytree(small, invalid)
        (invalid / "degrees.u32le").unlink()
        (invalid / "degrees.u32le").symlink_to(Path(small) / "degrees.u32le")
        record = step("symlink_input", [binary, "offline", str(invalid), "original_example", "csr_degree",
                                      str(output / "negative_symlink")], success=False)
        if "regular non-symlink admitted input required" not in Path(record["stderr"]).read_text():
            raise ValueError("symlink input failed for an unexpected reason")
        report["negative_controls"].append("symlink_input")
        if any(artifact.identity(Path(pin["path"])) != pin for pin in report["pins"]):
            raise ValueError("control source, dependencies, compiler or inputs changed during validation")
        report["status"] = analysis.STATUS
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        save()
        raise
    finally:
        if lease is not None:
            lease.release()
        report["memory_events_after"] = (current() / "memory.events").read_text()
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("captures", "audit", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    print(run(root, *(path.resolve() for path in (args.captures, args.audit, args.output)))["status"], flush=True)
