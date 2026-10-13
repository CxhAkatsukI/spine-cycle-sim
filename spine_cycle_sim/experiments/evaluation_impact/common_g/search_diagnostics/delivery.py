"""Package exact replay and read-only port evidence without claiming calibration."""

import argparse
import json
from pathlib import Path

from ..delivery import package_control
from .analysis import analyze


def package(output, matrix, previous):
    return package_control(output, matrix, previous, analyze=analyze,
        required_status="G_READ_ONLY_DIAGNOSTICS_EXACT_REPLAY",
        status="G_DIAGNOSTICS_REPLAYED_BASELINE_OPEN", previous_name="previous_concurrency.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "matrix", "previous"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = package(args.output.resolve(), args.matrix.resolve(), args.previous.resolve())
    print(json.dumps({"status": result["status"], "prediction_rows": result["prediction_rows"]}))
