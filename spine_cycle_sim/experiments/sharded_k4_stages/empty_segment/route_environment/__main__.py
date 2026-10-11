"""Fresh route with pinned explicit environment, smoke checks and unchanged budgets."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...execution import identity
from ...link_runtime import run_link
from ..route import admit, prepare
from .contract import reconstruct, require_unchanged
from .probe import run as preflight


def execute(output: Path, manifest: dict, environment: dict, contract: dict) -> dict:
    if (output / "route.resources.json").exists():
        raise FileExistsError("existing route execution record")
    require_unchanged(contract, environment)
    if any(identity(Path(pin["path"])) != pin for pin in manifest["pins"]):
        raise ValueError("route input changed before launch")
    record = run_link(manifest["command"], output, output / "route", environment=environment,
                      timeout=manifest["timeout_seconds"], tree_memory_gib=manifest["tree_memory_gib"],
                      reserve_gib=manifest["reserve_gib"])
    unchanged = all(identity(Path(pin["path"])) == pin for pin in manifest["pins"])
    require_unchanged(contract, environment)
    xclbin = output / "candidate.hw.xclbin"
    success = (record["exit_code"] == 0 and record["stop_reason"] == "process_exit"
               and not record["cleanup_snapshot_error"] and unchanged and xclbin.is_file())
    result = {"status": "LINK_PASS_AWAITING_TIMING_AND_BOARD" if success else "LINK_FAILED",
              "resources": record, "inputs_unchanged": unchanged,
              "xclbin": identity(xclbin) if xclbin.is_file() else None}
    atomic_write_json(output / "summary.json", result)
    return result


def run(build: Path, production: Path, output: Path, *, requested: bool) -> dict:
    # Do not catch preparation's fresh-path refusal and write into historical evidence.
    manifest = prepare(build, production, output)
    stage = "environment"
    try:
        (output / "tmp").mkdir()
        environment, contract = reconstruct(build, output)
        atomic_write_json(output / "environment.json", contract)
        pins = {pin["path"]: pin for pin in manifest["pins"]}
        extra = [*contract["pins"], identity(output / "environment.json")]
        extra += [identity(path) for path in sorted(Path(__file__).parent.glob("*.py"))]
        for pin in extra:
            if pins.setdefault(pin["path"], pin) != pin:
                raise ValueError("conflicting route/environment source pin")
        manifest.update(pins=list(pins.values()), environment_contract=contract["contract"],
                        execution_requested=requested)
        atomic_write_json(output / "manifest.json", manifest)
        stage = "preflight"
        preflight(output, environment, contract)
        manifest["pins"].append(identity(output / "preflight/results.json"))
        atomic_write_json(output / "manifest.json", manifest)
        stage = "admission"
        result = admit(output)
        code = 2 if requested and result["status"] == "ADMISSION_REJECTED_NOT_STARTED" else 0
        if requested and result["status"] == "MEMORY_ADMITTED_NOT_STARTED":
            stage = "execution"
            result = execute(output, manifest, environment, contract)
            code = 0 if result["status"] == "LINK_PASS_AWAITING_TIMING_AND_BOARD" else 1
        result.update(exit_code=code, execution_requested=requested)
    except Exception as error:
        result = {"status": "ROUTE_EXECUTION_FAILED" if stage == "execution" else "ROUTE_PREPARATION_FAILED",
                  "stage": stage, "error": str(error), "route_started": None if stage == "execution" else False,
                  "execution_requested": requested, "exit_code": 1}
    if result["exit_code"] == 1:
        atomic_write_json(output / "failure.json", result)
    atomic_write_json(output / "execution.json", result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("build", "production", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    result = run(args.build.resolve(), args.production.resolve(), args.output.resolve(), requested=args.execute)
    print(json.dumps(result, sort_keys=True))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
