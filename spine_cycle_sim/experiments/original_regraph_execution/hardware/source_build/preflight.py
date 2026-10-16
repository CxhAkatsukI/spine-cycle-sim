"""Freeze an author-generated topology and commands without launching FPGA tools."""

import argparse
from pathlib import Path
import subprocess
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from .. import artifact
from . import configuration as config, execution, placement as physical, snapshot


def run(root: Path, upstream: Path, output: Path, *, topology: str = config.DEFAULT_TOPOLOGY,
        placement: str = physical.DEFAULT) -> dict:
    physical.validate(topology, placement)
    little, big = config.counts(topology)
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARED", "errors": [], "pins": [],
              "configuration": topology, "little": little, "big": big, "placement": placement,
              "compiler_launched": False, "board_programmed": False,
              "hardware_timing_measured": False, "publication_match": False}

    def save():
        atomic_write_json(output / "results.json", report)

    save()
    try:
        group = current()
        report["containment"] = verify(group, memory_gib=2)
        report["available_before_bytes"] = available_memory_bytes()
        if report["available_before_bytes"] < 34 * 1024**3:
            raise RuntimeError("source-only preflight needs its 2-GiB limit plus 32-GiB reserve")
        report["source_revision"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=10).strip()
        report["worktree_status"] = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True, timeout=10).splitlines()
        report["pins"] = execution.runner_pins() + [
            artifact.identity(config.GENERATOR_PYTHON), artifact.identity(Path(sys.executable).resolve())]
        report["generator_python_version"] = subprocess.check_output(
            [str(config.GENERATOR_PYTHON), "--version"], text=True, timeout=10).strip()
        prepared = snapshot.prepare(root, upstream, output, topology)
        report["source_snapshot"] = prepared
        source = Path(prepared["source"])
        placed = physical.prepare(source, output, topology, placement)
        report["physical_configuration"] = placed
        entries = snapshot.prepare_entries(source, output, topology)
        report["pins"] += prepared["pins"] + placed["pins"] + entries
        report["commands_not_executed"] = {
            "compilations": {name: config.compile_command(source, output, name, topology)
                             for name in config.kernels(topology)},
            "link": config.link_command(source, output, topology, connectivity=Path(placed["config"]))}
        snapshot.unchanged(report["pins"])
        report["status"] = "AUTHOR_TOPOLOGY_SNAPSHOT_PASS_AWAITING_COMPILE_ABI_ROUTE_BOARD"
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        save()
        raise
    finally:
        report["memory_events_after"] = (current() / "memory.events").read_text()
        save()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("upstream", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--topology", choices=tuple(config.TOPOLOGIES), default=config.DEFAULT_TOPOLOGY)
    parser.add_argument("--placement", choices=physical.CHOICES, default=physical.DEFAULT)
    args = parser.parse_args()
    result = run(Path(__file__).resolve().parents[5], args.upstream.resolve(),
                 args.output.resolve(), topology=args.topology, placement=args.placement)
    print(result["status"], flush=True)


if __name__ == "__main__":
    main()
