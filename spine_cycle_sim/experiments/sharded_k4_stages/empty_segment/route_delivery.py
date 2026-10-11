"""Package a prepared route's recorded memory rejection without claiming a run."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from ..execution import identity


def deliver(run: Path, production: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError("fresh route evidence destination required")
    manifest = json.loads((run / "manifest.json").read_text())
    admission = json.loads((run / "admission.json").read_text())
    candidate = json.loads((production / "results.json").read_text())
    if (manifest["status"] != "PREPARED_NOT_ROUTED"
            or admission["status"] != "ADMISSION_REJECTED_NOT_STARTED" or admission["route_started"] is not False
            or (manifest["tree_memory_gib"], manifest["reserve_gib"]) != (40, 16)
            or (admission["tree_memory_gib"], admission["reserve_gib"]) != (40, 16)
            or not 0 < admission["available_bytes"] < admission["required_bytes"] == 56 * 1024**3
            or admission["command"] != manifest["command"]
            or candidate["status"] != "production_XO_ABI_pass_not_routed"
            or candidate["xo"] not in manifest["pins"]
            or json.loads((production / "verification.json").read_text())["status"] != "production_XO_ABI_rechecked_not_routed"):
        raise ValueError("route admission or production dependency differs")
    if any(identity(Path(pin["path"])) != pin for pin in manifest["pins"]):
        raise ValueError("route preparation input changed")
    if any((run / name).exists() for name in ("route.resources.json", "candidate.hw.xclbin", "summary.json", "failure.json")):
        raise ValueError("route evidence contains an execution; use a separate run delivery")
    files = [(run / name, name) for name in ("manifest.json", "admission.json", "link.cfg")]
    files += [(Path(__file__), "packaging/route_delivery.py")]
    destination.mkdir(parents=True)
    archive = destination / "raw_preparation.tar.gz"
    entries = seal(files, archive)
    result = {"status": admission["status"], "archive": identity(archive), "files": entries,
              "admission": admission, "production_dependency": identity(production / "verification.json"),
              "route_started": False, "original_XOs": "hash_indexed_not_bundled",
              "not_admitted": ["routed_timing", "FPGA_speedup", "original_A4_matching"]}
    atomic_write_json(destination / "verification.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "production", "destination"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = deliver(args.run.resolve(), args.production.resolve(), args.destination.resolve())
    print(json.dumps({"status": result["status"]}))


if __name__ == "__main__":
    main()
