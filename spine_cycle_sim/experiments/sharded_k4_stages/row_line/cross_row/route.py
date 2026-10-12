"""Fresh V3 link with shared environment preflight and unchanged memory guards."""

import argparse
import json
from pathlib import Path

from ..route import run_prepared
from .route_preparation import prepare


def run(build: Path, basis: Path, study: Path, host: Path, integration: Path,
        output: Path, *, requested: bool) -> dict:
    manifest = prepare(build, basis, study, host, integration, output)
    return run_prepared(build, output, manifest, requested=requested)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    names = ("build", "basis", "study", "host", "integration", "output")
    for name in names:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    result = run(**{name: getattr(args, name).resolve() for name in names}, requested=args.execute)
    print(json.dumps(result, sort_keys=True))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
