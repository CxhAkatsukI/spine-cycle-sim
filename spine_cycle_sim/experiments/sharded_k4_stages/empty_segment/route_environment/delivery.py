"""Seal an environment-checked memory non-start, without admitting FPGA timing."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from ...execution import identity
from .probe import SOURCE

LABELS = ("vitis_version", "vivado_version", "gcc_version", "gxx_version", "thread_compile", "thread_execute")


def recheck(run: Path) -> dict:
    manifest, environment, probe, admission, execution = (
        json.loads((run / name).read_text()) for name in
        ("manifest.json", "environment.json", "preflight/results.json", "admission.json", "execution.json"))
    if (manifest["environment_contract"] != environment["contract"]
            or manifest["status"] != "PREPARED_NOT_ROUTED"
            or admission["status"] != "ADMISSION_REJECTED_NOT_STARTED"
            or admission["route_started"] is not False or execution["route_started"] is not False
            or execution["exit_code"] != 2 or execution["execution_requested"] is not True
            or admission["command"] != manifest["command"]
            or execution != {**admission, "execution_requested": True, "exit_code": 2}
            or (manifest["tree_memory_gib"], manifest["reserve_gib"], manifest["timeout_seconds"]) != (40, 16, 14400)
            or (admission["tree_memory_gib"], admission["reserve_gib"]) != (40, 16)
            or not 0 < admission["available_bytes"] < admission["required_bytes"] == 56 * 1024**3):
        raise ValueError("route non-start contract differs")
    pins = {pin["path"]: pin for pin in manifest["pins"]}
    for path in (run / "environment.json", run / "preflight/results.json"):
        if pins.get(str(path)) != identity(path):
            raise ValueError("preflight/environment not bound to route admission")
    if any(identity(Path(pin["path"])) != pin for pin in pins.values()):
        raise ValueError("route/environment input changed after execution")
    for pin in environment["pins"]:
        if pins.get(pin["path"]) != pin:
            raise ValueError("environment input not included in route pins")
    if (probe["status"] != "PREFLIGHT_PASS_NOT_ROUTED"
            or [item["label"] for item in probe["commands"]] != list(LABELS)
            or probe["source"] != identity(run / "preflight/thread.cpp")
            or (run / "preflight/thread.cpp").read_text() != SOURCE
            or probe["executable"] != identity(run / "preflight/thread")):
        raise ValueError("preflight matrix/source/executable differs")
    for item in probe["commands"]:
        prefix = run / "preflight" / item["label"]
        saved = json.loads(prefix.with_suffix(".resources.json").read_text())
        if (saved != {k: v for k, v in item.items() if k != "label"}
                or item["exit_code"] != 0 or item["stop_reason"] != "process_exit"
                or item["cleanup_snapshot_error"] is not None
                or (item["tree_memory_gib"], item["reserve_gib"], item["timeout_seconds"]) != (4, 16, 90)
                or item["peak_tree_rss_kib"] * 1024 > 4 * 1024**3
                or item["minimum_available_bytes"] < 16 * 1024**3
                or item["wall_seconds"] > 95):
            raise ValueError("preflight watchdog differs: " + item["label"])
    for label in LABELS[:2]:
        if "2024.1" not in (run / "preflight" / (label + ".stdout.txt")).read_text():
            raise ValueError("vendor preflight version differs")
    shim = environment["effective"]["values"]["CPLUS_INCLUDE_PATH"] + "/bits/gthr-default.h"
    if shim not in (run / "preflight/thread_compile.stderr.txt").read_text():
        raise ValueError("preflight did not exercise the compatibility shim")
    if any((run / name).exists() for name in ("route.resources.json", "candidate.hw.xclbin", "summary.json", "failure.json")):
        raise ValueError("non-start archive contains route execution")
    return {"status": "ENVIRONMENT_PREFLIGHT_PASS_ROUTE_MEMORY_REFUSED", "admission": admission,
            "probe": probe, "environment": environment, "route_started": False}


def deliver(run: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError("fresh environment delivery required")
    checked = recheck(run)
    manifest = json.loads((run / "manifest.json").read_text())
    files = [(path, "run/" + str(path.relative_to(run))) for path in sorted(run.rglob("*")) if path.is_file()]
    # The eleven XOs and vendor executables remain indexed, not duplicated in this package.
    for index, pin in enumerate(manifest["pins"]):
        path = Path(pin["path"])
        if not path.is_relative_to(run) and path.suffix in (".py", ".sh", ".h", ".cfg") and path.stat().st_size < 2 * 1024**2:
            files.append((path, f"inputs/{index:03d}_" + path.name))
    files.append((Path(__file__), "packaging/delivery.py"))
    destination.mkdir(parents=True)
    archive = destination / "raw_environment_admission.tar.gz"
    entries = seal(files, archive)
    checked["archive"], checked["files"] = identity(archive), entries
    checked["not_admitted"] = ["routed_timing", "FPGA_speedup", "original_A4_matching", "exhaustive_vendor_toolchain_closure"]
    atomic_write_json(destination / "verification.json", checked)
    return checked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("run", "destination"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    result = deliver(args.run.resolve(), args.destination.resolve())
    print(json.dumps({"status": result["status"]}))


if __name__ == "__main__":
    main()
