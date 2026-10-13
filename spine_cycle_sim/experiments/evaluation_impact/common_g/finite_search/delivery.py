"""Package the entire finite-stage matrix, including performance mismatches."""

import argparse
import json
from pathlib import Path

from ..delivery import package_control
from .analysis import analyze


def package(output, matrix, previous):
    return package_control(output, matrix, previous, analyze=analyze,
        required_status="G_FINITE_SEARCH_PREDICTIONS_CHECKED",
        status="G_FINITE_SEARCH_CHECKPOINT_HARDWARE_OPEN", previous_name="previous_metadata.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "matrix", "previous"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = package(args.output, args.matrix, args.previous)
    print(json.dumps({"status": result["status"], "prediction_rows": result["prediction_rows"]}))
