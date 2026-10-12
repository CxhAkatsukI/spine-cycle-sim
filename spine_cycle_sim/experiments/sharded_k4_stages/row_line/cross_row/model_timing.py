"""Compare the fixed structural model to all twelve RTL shapes; do not fit parameters."""

import argparse
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.refactor_equivalence import source_snapshot, verify_source_snapshot
from ...execution import identity
from ...link_runtime import run_link
from ...sst_candidate import load_profile
from .model_contract import BASIS, PROFILE_ID, TARGET

SHAPES = ((0, 0, 1, 1, 0), (1, 0, 1, 1, 0), (8, 0, 1, 1, 0), (9, 0, 1, 1, 0),
          (17, 0, 1, 1, 0), (17, 0, 1, 64, 0), (17, 0, 1, 128, 0), (17, 0, 3, 64, 0),
          (17, 1, 1, 64, 0), (17, 2, 1, 64, 0), (17, 3, 1, 64, 0), (17, 0, 1, 64, 1000))


def compare(rows: list[dict], rtl: dict) -> dict:
    if (rtl.get("status") != "CROSS_ROW_PRODUCTION_AXI_PASS_NOT_ROUTED"
            or rtl.get("FPGA_timing_admitted") is not False
            or rtl.get("xo", {}).get("sha256") != TARGET["candidate_adapter_xo_sha256"]):
        raise ValueError("frozen V3 RTL identity or evidence boundary differs")
    expected_keys = [(i, arm) for i in range(12) for arm in (False, True)]
    if [(row.get("trial"), row.get("candidate")) for row in rows] != expected_keys:
        raise ValueError("complete ordered twelve-case/two-arm model matrix required")
    result = []
    for arm, candidate in (("reference", False), ("candidate", True)):
        evidence = rtl["arms"][arm]
        if len(evidence) != 12:
            raise ValueError("complete RTL matrix required")
        for i, (v, placement, segments, latency, stall) in enumerate(SHAPES):
            measured, predicted = evidence[i], rows[i * 2 + int(candidate)]
            if (tuple(measured[k] for k in ("vertices", "placement", "length", "latency", "stall"))
                    != (v, placement, segments, latency, stall) or measured["trial"] != i
                    or predicted.get("exact_packets_and_traffic") is not True):
                raise ValueError("model/RTL geometry or packet admission differs")
            occupied = sum(placement == 0 or (placement == 1 and source + 1 == v)
                           or (placement == 2 and source == 0) or (placement == 3 and source % 7 == 0)
                           for source in range(v))
            extent, reads, packets = predicted["extent_reads"], predicted["segment_reads"], predicted["packets"]
            if (extent != int(v != 0) or reads != occupied * segments or packets != reads * 2
                    or predicted["live_edges"] != reads * 10 or predicted["dummy_edges"] != reads * 6
                    or measured["row_requests"] != predicted["row_reads"] + extent
                    or measured["pma_requests"] != reads or measured["packets"] != packets
                    or measured["row_transfer_bytes"] != (predicted["row_reads"] + extent) * 64
                    or measured["pma_transfer_bytes"] != reads * 64):
                raise ValueError("model/RTL physical traffic differs")
            actual, model = measured["cycles"], predicted["adapter_done"]
            if actual <= 0 or model <= 0:
                raise ValueError("invalid completion time")
            ape = abs(model - actual) / actual
            result.append({"trial": i, "arm": arm, "rtl_cycles": actual, "model_cycles": model,
                           "absolute_percentage_error": ape * 100, "within_10_percent": ape <= .1,
                           "exact_packets_and_traffic": True})
    return {"status": "STRUCTURAL_TIMING_DIAGNOSTIC_NOT_CALIBRATION", "rows": result,
            "all_rows_within_10_percent": all(row["within_10_percent"] for row in result),
            "hardware_timing_admitted": False, "fitted_parameters": [],
            "scope_limits": ["RTL start-to-done versus registered C++ invocation-to-done",
                             "RTL ordered AXI responder versus FixedAxiPort and MockMemory",
                             "C++ depth-32 output FIFO versus direct RTL sink",
                             "71-cycle minimum read-to-use retained, not inferred from these rows",
                             "no real HBM banks, refresh, routed interconnect or ReGraph downstream"]}


def run(root: Path, binary: Path, rtl_result: Path, output: Path) -> dict:
    profile = root / f"configs/architectures/{PROFILE_ID}.json"
    basis = root / BASIS["path"]
    load_profile(root, profile)
    contract = root / "configs/experiments/grasu_component_refactor_v1.json"
    source = source_snapshot(root, contract, json.loads(contract.read_text()))
    test_files = sorted(path for path in (root / "cpp/tests").rglob("*") if path.suffix in (".cpp", ".hpp"))
    test_files += sorted((root / "tests").glob("test_sharded_k4_cross_row_model*.py"))
    pins = [identity(path) for path in (binary, rtl_result, profile, basis, *test_files)]
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for row in source["files"]:
            stream.add(root / row["path"], arcname=row["path"], recursive=False)
        for path in (profile, basis, *test_files):
            stream.add(path, arcname=path.relative_to(root), recursive=False)
    shutil.copyfile(rtl_result, output / "rtl_results.json")
    atomic_write_json(output / "manifest.json", {"pins": pins, "source": source,
                      "source_archive": identity(archive), "binary": identity(binary), "rtl": identity(rtl_result),
                      "profile": identity(profile), "basis": identity(basis),
                      "test_files": [identity(path) for path in test_files],
                      "claim": "same_logical_input_not_identical_memory_or_endpoint_timing"})
    record = run_link([str(binary), "--rtl-matrix"], root, output / "probe", timeout=90,
                      tree_memory_gib=3, reserve_gib=16)
    if record["exit_code"] != 0 or record["stop_reason"] != "process_exit":
        raise ValueError("structural probe failed; raw attempt retained")
    rows = [json.loads(line) for line in (output / "probe.stdout.txt").read_text().splitlines()]
    report = compare(rows, json.loads(rtl_result.read_text()))
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("frozen timing inputs changed")
    verify_source_snapshot(root, source)
    atomic_write_json(output / "results.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "rtl-result", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        report = run(Path(__file__).resolve().parents[5], args.binary.resolve(), args.rtl_result.resolve(), output)
        print(report["status"], flush=True)
    except Exception as error:
        if output.is_dir():
            atomic_write_json(output / "failure.json", {"status": "FAILED_RETAINED", "error": repr(error)})
        raise


if __name__ == "__main__":
    main()
