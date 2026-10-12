"""Fresh whole-line route using existing explicit environment and memory guards."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ..empty_segment.route import admit
from ..empty_segment.route_environment.__main__ import execute
from ..empty_segment.route_environment.contract import reconstruct
from ..empty_segment.route_environment.probe import run as preflight
from ..execution import identity
from .route_preparation import prepare


def run(build: Path, study: Path, host: Path, integration: Path, output: Path, *, requested: bool) -> dict:
    manifest = prepare(build, study, host, integration, output)
    return run_prepared(build, output, manifest, requested=requested)


def run_prepared(build: Path, output: Path, manifest: dict, *, requested: bool) -> dict:
    """Execute only after the owning candidate's fresh preparation succeeds."""
    stage = "environment"
    try:
        (output / "tmp").mkdir()
        environment, contract = reconstruct(build, output)
        atomic_write_json(output / "environment.json", contract)
        pins = {pin["path"]: pin for pin in manifest["pins"]}
        owner = Path(__file__).parent.parent / "empty_segment"
        extra = [*contract["pins"], identity(output / "environment.json"), identity(owner / "route.py")]
        extra += [identity(path) for path in sorted((owner / "route_environment").glob("*.py"))]
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
    for name in ("build", "study", "host", "integration", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    result = run(**{name: getattr(args, name).resolve() for name in (
        "build", "study", "host", "integration", "output")}, requested=args.execute)
    print(json.dumps(result, sort_keys=True))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
