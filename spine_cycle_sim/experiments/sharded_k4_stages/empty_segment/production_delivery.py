"""Seal production XO, generated RTL, synthesis reports and bounded execution."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from ..execution import identity
from .production_validation import recheck


def raw_files(run: Path) -> list[tuple[Path, str]]:
    paths = [run / name for name in ("manifest.json", "results.json", "adapter.hw.xo")]
    for directory in ("sources", "functional_gate", "reports", "logs"):
        paths.extend((run / directory).rglob("*"))
    paths.extend(run.glob("compile.*"))
    report = Path(json.loads((run / "results.json").read_text())["analysis"]["report"]["path"])
    solution = report.parents[2]
    if (report.name != "pma_to_regraph_adapter_csynth.xml"
            or not solution.is_relative_to(run / "build") or not solution.is_dir()):
        raise ValueError("production synthesis solution differs")
    for directory in ("syn/verilog", "syn/report"):
        paths.extend((solution / directory).rglob("*"))
    paths += [solution / ".autopilot/db/burst.xml"]
    paths += [solution.parent / "hls.app"]
    files = []
    for path in sorted(set(paths)):
        if path.is_symlink():
            raise ValueError("symlink in production raw evidence")
        if path.is_file():
            files.append((path, str(path.relative_to(run))))
    for path in sorted(run.parent.glob(run.name + "_watchdog.*")):
        if path.is_file() and not path.is_symlink():
            files.append((path, "watchdog/" + path.name))
    return files


def deliver(run: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError("fresh production delivery directory required")
    gate = recheck(run)
    files = raw_files(run)
    destination.mkdir(parents=True)
    archive = destination / "raw_production.tar.gz"
    entries = seal(files, archive)
    shutil.copyfile(run / "results.json", destination / "results.json")
    result = {"status": "production_XO_ABI_rechecked_not_routed", "archive": identity(archive),
              "files": entries, "results": identity(destination / "results.json"),
              "source_snapshots_rechecked": True, "abi": gate["report"]["xo_contract"],
              "prerequisite_paired_report": gate["manifest"]["paired_gate"],
              "not_admitted": ["routed_timing", "FPGA_speedup", "original_A4_matching", "simulator_timing"]}
    atomic_write_json(destination / "verification.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = deliver(args.run.resolve(), args.destination.resolve())
    print(json.dumps({"status": result["status"], "archive": result["archive"]}))


if __name__ == "__main__":
    main()
