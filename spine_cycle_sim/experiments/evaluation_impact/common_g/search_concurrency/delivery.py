"""Archive the complete concurrency control without promoting timing claims."""

import argparse
import json
from pathlib import Path

from ..delivery import package_control
from .analysis import analyze


def package(output, matrix, previous):
    return package_control(output, matrix, previous, analyze=analyze,
        required_status="G_SEARCH_CONCURRENCY_VALIDATED_REFERENCE_TIMING_OPEN",
        status="G_SEARCH_CONCURRENCY_CHECKPOINT_REFERENCE_TIMING_OPEN",
        previous_name="previous_cached_hot.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("output", "matrix", "previous"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    result = package(args.output, args.matrix, args.previous)
    print(json.dumps({"status": result["status"], "prediction_rows": result["prediction_rows"]}))
