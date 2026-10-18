"""Bind prepared full-graph hosts to an explicitly admitted algorithm artifact."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.sharded_k4_stages import bitstream
from . import analysis, preparation, recheck


def stamp_pins(pins):
    stamped = {}
    for pin in pins:
        actual = preparation.identity(Path(pin["path"]))
        if actual["sha256"] != pin["sha256"] or ("stat" in pin and actual != pin):
            raise ValueError("preflight or admitted artifact identity changed")
        if pin["path"] in stamped and stamped[pin["path"]] != actual:
            raise ValueError("conflicting input identity")
        stamped[pin["path"]] = actual
    return list(stamped.values())


def prepare(preflight, admission, algorithm):
    if algorithm not in preparation.ALGORITHMS:
        raise ValueError("this matrix is SSSP, CC or residual PageRank, not fixed-round FullPR")
    report_path = preflight / "results.json"
    report = json.loads(report_path.read_text())
    if report.get("status") != analysis.PASS:
        raise ValueError("complete three-smoke/24-input offline preparation required")
    recheck.recheck(report, lambda name: (preflight / name).read_text())
    guard = preflight / "source/tools/weighted_pma_native_host.cpp"
    code = guard.read_text()
    if 'std::getenv("GRASU_REGRAPH_EXPECT_BDF")' not in code or "CL_DEVICE_PCIE_BDF" not in code or \
            code.index("CL_DEVICE_PCIE_BDF") > code.index("return device;", code.index("select_xilinx_device()")):
        raise ValueError("host predates the pre-context PCIe lease guard")
    checked = json.loads(admission.read_text())
    status = ("ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD" if algorithm == "weighted_sssp" else
              "ALGORITHM_ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD")
    if checked.get("status") != status or checked.get("errors", []) or \
            (algorithm != "weighted_sssp" and checked.get("algorithm") != algorithm) or \
            any(checked.get(key, False) is not False for key in ("board_admitted", "publication_match", "rtl_admitted")):
        raise ValueError("successful strict routed admission for the requested algorithm required")
    binary = preflight / algorithm
    pins = stamp_pins([preparation.identity(report_path), preparation.identity(admission),
                       *report["pins"], *checked["pins"], checked["candidate"], checked["timing"]["report"]])
    if not any(pin["path"] == str(binary) for pin in report["pins"]):
        raise ValueError("preflight binary was not frozen")
    if bitstream.parse_routed_timing(Path(checked["timing"]["report"]["path"])) != checked["timing"]:
        raise ValueError("routed timing report differs from admitted timing")
    rows = [row for row in report["matrix"] if row["algorithm"] == algorithm]
    if [row["dataset"] for row in rows] != list(preparation.DATASETS):
        raise ValueError("exact eight-graph order required")
    smoke = next(row for row in recheck.smoke_rows(preflight) if row["algorithm"] == algorithm)
    return {"binary": str(binary), "candidate": checked["candidate"], "algorithm": algorithm,
            "host_revision": report["source_revision"], "artifact_admission": checked,
            "rows": rows, "smoke": smoke, "pins": pins}


def command(plan, row, result):
    argv = [plan["binary"], plan["candidate"]["path"], row["graph"], str(result)]
    return argv if row["algorithm"] == "residual_pagerank" else [*argv, str(row["source"]), "256"]
