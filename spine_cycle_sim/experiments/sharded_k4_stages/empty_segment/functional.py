"""Freeze and run the production adapter's twelve C++ equivalence gates."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from ..execution import identity
from ..link_runtime import run_link

SOURCES = ("kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp",
           "kernels/pma_to_regraph_adapter/row_prefetch.hpp",
           "tests/pma_to_regraph_adapter_tb.cpp", "tests/pma_adapter_row_prefetch_tb.cpp",
           "scripts/check_pma_to_regraph_adapter.sh", "scripts/env.sh")


def worker(integration: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    pins = [{"archive_path": name, **identity(integration / name)} for name in SOURCES]
    pins += [{"archive_path": "runner/" + name, **identity(Path(__file__).parent / name)}
             for name in ("functional.py",)]
    for pin in pins:
        copy = output / "sources" / pin["archive_path"]
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pin["path"], copy)
    manifest = {"source": pins, "compiler": subprocess.check_output(
        ["g++", "--version"], text=True), "claim": "CXX_packet_equivalence_not_RTL_or_board"}
    atomic_write_json(output / "manifest.json", manifest)
    execution = run_bounded(["bash", "scripts/check_pma_to_regraph_adapter.sh", "--out-dir",
                             str(output / "checks")], integration, output / "execution",
                            timeout=180, memory_gib=8, reserve_gib=16)
    if execution["exit_code"] or execution["timed_out"]:
        raise RuntimeError("functional execution failed; raw outputs retained")
    if any(sha256_file(Path(pin["path"])) != pin["sha256"] for pin in pins):
        raise ValueError("functional source changed during execution")


def deliver(output: Path, watchdog: dict, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError("fresh functional evidence destination required")
    if (watchdog["exit_code"] or watchdog["stop_reason"] != "process_exit"
            or watchdog["cleanup_snapshot_error"] is not None):
        raise ValueError("functional process-tree gate failed")
    manifest = json.loads((output / "manifest.json").read_text())
    for pin in manifest["source"]:
        if sha256_file(output / "sources" / pin["archive_path"]) != pin["sha256"]:
            raise ValueError("frozen functional source changed")
    checks = output / "checks"
    # sha256sum records include absolute paths; compare the captured basename
    # to its owning source/output, never follow an untrusted recorded path.
    paths = {Path(pin["path"]).name: Path(pin["path"]) for pin in manifest["source"]}
    paths.update({path.name: path for path in checks.iterdir() if path.is_file()})
    for row in (checks / "SHA256SUMS").read_text().splitlines():
        digest, name = row.split(maxsplit=1)
        if sha256_file(paths[Path(name).name]) != digest:
            raise ValueError("functional output/source checksum differs")
    text = (checks / "test.log").read_text()
    for skip in (0, 1):
        if text.count(f"ROW_PREFETCH_EQUIVALENCE status=PASS cases=254 packets=1482 skip_empty={skip}") != 3:
            raise ValueError("all three output-format equivalence gates required")
    execution = json.loads((output / "execution.resources.json").read_text())
    if execution["exit_code"] or execution["timed_out"]:
        raise ValueError("functional child gate failed")
    files = [(path, str(path.relative_to(output))) for path in sorted(output.rglob("*"))
             if path.is_file() and "checks" not in path.relative_to(output).parts]
    files += [(checks / name, "checks/" + name) for name in ("test.log", "manifest.env", "SHA256SUMS")]
    files += [(path, "watchdog/" + path.name) for path in sorted(
        output.parent.glob(output.name + "_watchdog.*")) if path.is_file()]
    destination.mkdir(parents=True)
    archive = destination / "raw_functional.tar.gz"
    members = seal(files, archive)
    result = {"status": "twelve_CXX_configs_passed_not_RTL_or_board", "archive": identity(archive),
              "files": members, "manifest": manifest, "execution": execution,
              "watchdog": watchdog, "compiled_executables": "hash_indexed_not_bundled"}
    atomic_write_json(destination / "verification.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "output", "destination"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    integration, output, destination = (getattr(args, name).resolve()
                                        for name in ("integration", "output", "destination"))
    if args.worker:
        worker(integration, output)
        return
    if output.exists() or destination.exists():
        raise FileExistsError("fresh functional run and delivery required")
    command = [sys.executable, "-m", __package__ + ".functional", "--worker",
               "--integration", str(integration), "--output", str(output),
               "--destination", str(destination)]
    watchdog = run_link(command, Path.cwd(), output.with_name(output.name + "_watchdog"),
                        timeout=240, tree_memory_gib=3, reserve_gib=16)
    print(json.dumps({"status": deliver(output, watchdog, destination)["status"]}))


if __name__ == "__main__":
    main()
