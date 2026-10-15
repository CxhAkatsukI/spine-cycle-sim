"""Bounded, independently leased original-R checkpoint inspection."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes, run_bounded
from . import artifact, checkpoint, study

POLICY = {"tree_memory_gib": 20, "reserve_gib": 24,
          "background_memory_gib": 8, "allow_bounded_builds": True}
VIVADO = Path("/data/yxx/tools/xilinx/Vivado/2024.1/bin/vivado")
UTILITY = Path("/opt/xilinx/xrt/bin/xclbinutil")


def environment(path: Path, output: Path) -> dict:
    captured = json.loads(path.read_text())
    if captured["effective"]["license_value_sha256"]:
        raise ValueError("license-bearing environment needs an explicit reviewed loader")
    values = captured["effective"]["values"]
    if (not isinstance(values, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                           for key, value in values.items()) or
            any("LICENSE" in key.upper() for key in values) or
            values.get("XILINX_VIVADO") != str(VIVADO.parents[1])):
        raise ValueError("reviewed string-valued Vivado environment required")
    scratch = output / "tmp"
    scratch.mkdir()
    return {**values, **dict.fromkeys(("TEMP", "TMP", "TMPDIR"), str(scratch))}


def run(prebuilt: Path, audit: Path, captured_environment: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARED", "errors": [], "policy": POLICY,
              "pins": [], **dict.fromkeys(checkpoint.CLAIMS, False)}
    lease = None
    def save():
        atomic_write_json(output / "results.json", report)
    save()
    try:
        group = current()
        report["containment"] = verify(group, memory_gib=POLICY["tree_memory_gib"])
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        report["admission"] = lease.sample(available_memory_bytes(), other_builds(), POLICY, commit=True)
        save()
        if not report["admission"]["admitted"]:
            raise RuntimeError("finite peer budgets plus reserve do not fit; no tool launched")
        script = Path(__file__).with_name("checkpoint.tcl")
        binary = prebuilt / "xclbin_hw_pr/graph_fpga.hw..xclbin"
        paths = [prebuilt / checkpoint.IMPL / name for name in checkpoint.FILES]
        paths += [binary, audit / "results.json", captured_environment, script, VIVADO, UTILITY]
        paths += [Path(pin["path"]) for pin in study.runner_pins()]
        report["pins"] = [artifact.identity(path) for path in sorted(set(paths))]
        effective = environment(captured_environment, output)
        atomic_write_json(output / "environment.json", {"values": effective, "license_hashes": {}})
        shutil.copyfile(script, output / "checkpoint.tcl")
        query = output / "query"
        query.mkdir()
        save()
        report["extraction"] = run_bounded([str(UTILITY), "--input", str(binary), "--dump-section",
            f"BITSTREAM:RAW:{output / 'embedded.bit'}"], output, output / "extract",
            timeout=120, memory_gib=2, reserve_gib=32)
        if report["extraction"]["exit_code"] or report["extraction"]["timed_out"]:
            raise ValueError("read-only embedded bitstream extraction failed")
        command = [str(VIVADO), "-mode", "batch", "-notrace", "-source", str(output / "checkpoint.tcl"),
                   "-log", str(output / "vivado.log"), "-journal", str(output / "vivado.jou"),
                   "-tclargs", str(prebuilt / checkpoint.IMPL / checkpoint.FILES[0]), str(query)]
        report["status"] = "READ_ONLY_QUERY_RUNNING"
        save()
        report["execution"] = run_link(command, output, output / "query_run", timeout=1200,
            tree_memory_gib=20, reserve_gib=32, environment=effective)
        if report["execution"]["exit_code"] or report["execution"]["stop_reason"] != "process_exit":
            raise ValueError("read-only checkpoint query failed or was safely stopped")
        report["analysis"] = checkpoint.analyze(output, prebuilt, audit)
        if any(artifact.identity(Path(pin["path"])) != pin for pin in report["pins"]):
            raise ValueError("checkpoint, prebuilt, environment or runner changed during query")
        report["status"] = checkpoint.STATUS
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
    for name in ("prebuilt", "audit", "environment", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(run(*(path.resolve() for path in (args.prebuilt, args.audit, args.environment, args.output)))["status"], flush=True)
