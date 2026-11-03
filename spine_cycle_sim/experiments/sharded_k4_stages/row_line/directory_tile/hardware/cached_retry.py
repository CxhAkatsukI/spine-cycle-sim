"""Prepare a fresh, time-bounded retry of an exact timed-out adapter link."""

import argparse
import json
from pathlib import Path
import re
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import service_state
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from . import replacement
from .component import unchanged

MAX_CACHE_BYTES = 8 * 1024**3
RETRY_SECONDS = 43200


def seed_cache(source, destination):
    if source.is_symlink() or not source.is_dir():
        raise ValueError("expected a local Vivado IP cache directory")
    paths = sorted(source.rglob("*"))
    if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in paths):
        raise ValueError("cache must contain regular files and directories only")
    files = [p for p in paths if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    if not 0 < total <= MAX_CACHE_BYTES or not any(p.suffix == ".dcp" for p in files):
        raise ValueError("nonempty checkpoint cache within the copy budget required")
    destination.mkdir(exist_ok=False)
    rows = []
    for path in files:
        relative = path.relative_to(source)
        copied = destination / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        pin = identity(path)
        shutil.copy2(path, copied)
        if path.samefile(copied) or identity(copied)["sha256"] != pin["sha256"] or identity(path) != pin:
            raise ValueError("cache changed during copy or has a shared writable inode")
        rows.append({"relative": str(relative), "sha256": pin["sha256"]})
    return {"source": str(source), "destination": str(destination), "bytes": total, "files": rows}


def validate_seed(output, inventory):
    destination = output / "ip_cache"
    paths = list(destination.rglob("*"))
    if (destination.is_symlink() or any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in paths)
            or {str(p.relative_to(destination)) for p in paths if p.is_file()} !=
            {row["relative"] for row in inventory["files"]}):
        raise ValueError("cached retry seed member set changed")
    if any(identity(destination / row["relative"])["sha256"] != row["sha256"] for row in inventory["files"]):
        raise ValueError("cached retry seed content changed")


def prepare(previous, output, *, unit, invocation):
    previous, output = previous.resolve(), output.resolve()
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit)
            or not re.fullmatch(r"[0-9a-f]{32}", invocation) or output.is_relative_to(previous)):
        raise ValueError("exact previous service and separate output required")
    state = service_state(unit)
    if (state["LoadState"], state["InvocationID"], state["ActiveState"], state["SubState"],
            state["MainPID"]) != ("loaded", invocation, "failed", "failed", "0"):
        raise ValueError("previous invocation must be terminal and failed")
    manifest_path, execution = previous / "manifest.json", previous / "execution/execution.json"
    old = json.loads(manifest_path.read_text())
    result = json.loads(execution.read_text())
    resources = result.get("resources", {})
    if (result["status"] != "FAILED_RETAINED" or result["kind"] != "LINK"
            or resources.get("stop_reason") != "timeout" or "cleanup_snapshot_error" not in resources
            or resources["cleanup_snapshot_error"] is not None):
        raise ValueError("only a link timeout with verified worker cleanup may be retried")
    if old["timeout_seconds"] != 21600:
        raise ValueError("only the original six-hour route is eligible for this retry")
    launch = previous / "execution/manifest.json"
    executed = json.loads(launch.read_text())
    if executed["command"] != old["command"] or identity(manifest_path) not in executed["pins"]:
        raise ValueError("previous prepared and executed link differ")
    unchanged(old["pins"])

    production = Path(old["production"])
    stdout = previous / "execution/job.stdout.txt"
    if "Starting logic optimization" in stdout.read_text():
        cache, cache_evidence = previous / "ip_cache", stdout
    else:
        cache, cache_evidence = production / "ip_cache", production / "results.json"
        report = json.loads(cache_evidence.read_text())
        if report["status"] != "ROUTED_NOT_BOARD_TESTED" or report["steps"][-1]["exit_code"] != 0:
            raise ValueError("no completed compatible production cache available")

    pins = [identity(p) for p in (manifest_path, launch, execution, cache_evidence, Path(__file__))]
    new = replacement.prepare(production, Path(old["packet"]), output)
    command = list(old["command"])
    command[command.index("--config") + 1] = str(output / "link.cfg")
    command[command.index("-o") + 1] = str(output / "candidate.hw.xclbin")
    if new["command"] != command:
        raise ValueError("retry changed the prior link command beyond output paths")
    seed = output / "ip-cache-seed.json"
    inventory = seed_cache(cache, output / "ip_cache")
    atomic_write_json(seed, dict(inventory, scope="compiler intermediates only; Vivado validates cache fingerprints"))
    unchanged(old["pins"] + pins)
    new.update(status="CACHED_RETRY_PREPARED_NOT_ROUTED", timeout_seconds=RETRY_SECONDS,
               pins=new["pins"] + pins + [identity(seed)],
               retry_of=str(previous), retry_service=state)
    atomic_write_json(output / "manifest.json", new)
    return new


def run(output, *, admission_wait=0):
    manifest = json.loads((output / "manifest.json").read_text())
    if manifest["status"] != "CACHED_RETRY_PREPARED_NOT_ROUTED" or manifest["timeout_seconds"] != RETRY_SECONDS:
        raise ValueError("completed cache seed and bounded retry plan required")
    unchanged(manifest["pins"])
    validate_seed(output, json.loads((output / "ip-cache-seed.json").read_text()))
    return replacement.run(output, admission_wait=admission_wait)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--unit")
    parser.add_argument("--invocation")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--admission-wait", type=int, default=0)
    args = parser.parse_args()
    if args.execute:
        print(run(args.output.resolve(), admission_wait=args.admission_wait)["status"], flush=True)
    else:
        if not all((args.previous, args.unit, args.invocation)):
            parser.error("preparation requires --previous, --unit and --invocation")
        print(prepare(args.previous, args.output, unit=args.unit, invocation=args.invocation)["status"], flush=True)
