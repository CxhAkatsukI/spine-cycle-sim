"""Prepare a fresh route and report execution failures through the CLI exit code.

Execution inherits the caller's environment; it does not source link_command.sh.
Before a future real route, initialize Vitis 2024.1 settings and the frozen
script's CPATH, C_INCLUDE_PATH, CPLUS_INCLUDE_PATH (including gcc_compat),
LIBRARY_PATH and COMPILER_PATH. Environment reconstruction/validation remains
open. The existing executor relocates TMPDIR, TMP and TEMP into the new run.
"""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ..execution import identity
from ..routing import execute_route
from .route import admit, prepare


def run(build: Path, production: Path, output: Path, *, execute: bool = False) -> dict:
    wrapper = identity(Path(__file__))
    # Keep preparation outside the handler: an existing evidence path is never ours to update.
    manifest = prepare(build, production, output)
    stage = "pinning"
    try:
        pins = {pin["path"]: pin for pin in manifest["pins"]}
        if pins.setdefault(wrapper["path"], wrapper) != wrapper:
            raise ValueError("route execution wrapper differs from a prepared source pin")
        manifest["pins"] = list(pins.values())
        manifest["execution_wrapper"] = wrapper
        manifest["execution_requested"] = execute
        manifest["environment_contract"] = "inherited_not_shell_replayed_or_validated"
        atomic_write_json(output / "manifest.json", manifest)
        stage = "admission"
        result = admit(output)
        exit_code = 0
        if execute:
            if result["status"] == "ADMISSION_REJECTED_NOT_STARTED":
                exit_code = 2
            elif result["status"] == "MEMORY_ADMITTED_NOT_STARTED":
                stage = "execution"
                result = execute_route(output)
                exit_code = 0 if result["status"] == "LINK_PASS_AWAITING_TIMING_AND_BOARD" else 1
            else:
                raise ValueError("unexpected route admission status")
        result = {**result, "execution_requested": execute, "exit_code": exit_code}
        if exit_code == 1:
            atomic_write_json(output / "failure.json", result)
    except Exception as error:
        result = {"status": "ROUTE_EXECUTION_FAILED" if stage == "execution" else "ROUTE_PREPARATION_FAILED",
                  "stage": stage, "error": str(error), "execution_requested": execute,
                  "route_started": None if stage == "execution" else False, "exit_code": 1}
        atomic_write_json(output / "failure.json", result)
    atomic_write_json(output / "execution.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("build", "production", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    result = run(args.build.resolve(), args.production.resolve(), args.output.resolve(), execute=args.execute)
    print(json.dumps(result))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
