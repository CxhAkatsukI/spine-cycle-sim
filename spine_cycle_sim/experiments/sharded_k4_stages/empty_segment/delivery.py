"""Seal both unsuccessful and effective empty-helper controls without retiming."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from ..execution import identity
from .validation import recheck


def raw_files(run: Path) -> list[tuple[Path, str]]:
    files = [(run / name, name) for name in ("manifest.json", "results.json")]
    for path in sorted((run / "sources").rglob("*")):
        if path.is_file():
            files.append((path, str(path.relative_to(run))))
    for path in sorted(run.parent.glob(run.name + "_watchdog.*")):
        files.append((path, "watchdog/" + path.name))
    for variant in ("combined", "skip_empty"):
        directory = run / variant
        paths = list(directory.glob("cosim.*")) + [directory / "project/hls.app"]
        for child in ("syn/verilog", "syn/report", "sim/report", "sim/tv"):
            paths.extend((directory / "project/solution" / child).rglob("*"))
        paths.extend((directory / "project/solution/sim/verilog").glob("*.transaction.xml"))
        for path in sorted(set(paths)):
            if path.is_symlink():
                raise ValueError("symlink in C/RTL raw evidence")
            if path.is_file():
                files.append((path, str(path.relative_to(run))))
    return files


def deliver(runs: list[Path], destination: Path) -> dict:
    if len(runs) != 2 or destination.exists():
        raise ValueError("two ordered historical controls and fresh destination required")
    reports = [recheck(run) for run in runs]
    old, new = reports
    base = old["runs"]["combined"]["analysis"]["cases"]
    if old["runs"]["skip_empty"]["analysis"]["cases"] != base or new["runs"]["combined"]["analysis"]["cases"] != base:
        raise ValueError("first control no longer unchanged, or extraction changed baseline timing")
    changes = [{**case, "candidate_cycles": candidate["rtl_cycles"],
                "baseline_over_candidate": case["rtl_cycles"] / candidate["rtl_cycles"]}
               for case, candidate in zip(base, new["runs"]["skip_empty"]["analysis"]["cases"], strict=True)]
    destination.mkdir(parents=True)
    entries = {}
    for run, report in zip(runs, reports, strict=True):
        archive = destination / (run.name + ".tar.gz")
        index = seal(raw_files(run), archive)
        shutil.copyfile(run / "results.json", destination / (run.name + ".json"))
        entries[run.name] = {"archive": identity(archive), "files": index,
                             "results": identity(destination / (run.name + ".json")),
                             "execution_source_bytes_rechecked": True}
    packaging_sources = [{"archive_path": "packaging/" + path.name, **identity(path)}
                         for path in sorted(Path(__file__).parent.glob("*.py"))]
    archive = destination / "packaging_sources.tar.gz"
    packaging = seal([(Path(pin["path"]), pin["archive_path"]) for pin in packaging_sources], archive)
    result = {"status": "paired_RTL_control_rechecked_not_routed_not_board",
              "runs": entries, "cases": changes,
              "packaging": {"archive": identity(archive), "files": packaging},
              "not_admitted": ["FPGA_speedup", "HBM_timing", "original_A4_matching", "new_simulator_timing"]}
    atomic_write_json(destination / "verification.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = deliver([run.resolve() for run in args.run], args.destination.resolve())
    print(json.dumps({"status": result["status"]}))


if __name__ == "__main__":
    main()
