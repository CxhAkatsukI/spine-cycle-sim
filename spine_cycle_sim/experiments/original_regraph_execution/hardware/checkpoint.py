"""Read-only original-R checkpoint contract; no clock or board admission."""

import csv
import json
import math
from pathlib import Path

from spine_cycle_sim.experiments.sharded_k4_stages.bitstream import parse_routed_timing
from . import artifact, study

IMPL = Path("_x/link/vivado/vpl/prj/prj.runs/impl_1")
FILES = ("level0_wrapper_postroute_physopt.dcp", "level0_i_ulp_my_rm_partial.bit",
         "_new_clk_freq", "clockInfo.txt", "level0_wrapper.tcl",
         "hw_bb_locked_timing_summary_postroute_physopted.rpt")
CLAIMS = ("board_admitted", "board_programmed", "hardware_timing_measured",
          "publication_match", "author_device_source_equivalence_verified",
          "timing_at_scaled_clock_verified", "checkpoint_bitstream_pairing_verified")
STATUS = "ORIGINAL_R_CHECKPOINT_INSPECTED_NOT_BOARD_ADMITTED"


def clock_requests(path: Path) -> dict[str, float]:
    rows = {}
    for line in path.read_text().splitlines():
        domain, index, name, value = line.split(":")
        frequency = float(value)
        key = f"{domain}:{index}:{name}"
        if key in rows or not math.isfinite(frequency) or frequency <= 0:
            raise ValueError("unique positive finite recorded clock required")
        rows[key] = frequency
    if "kernel:0:ulp_ucs/aclk_kernel_00" not in rows:
        raise ValueError("original-R recorded DATA clock required")
    return rows


def read_table(path: Path, fields: list[str]) -> list[dict]:
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != fields:
            raise ValueError("unexpected checkpoint table schema")
        rows = list(reader)
    if not rows or any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("complete checkpoint table required")
    return rows


def analyze(output: Path, prebuilt: Path, audit: Path) -> dict:
    previous = json.loads((audit / "results.json").read_text())
    if previous["status"] != study.STATUS or previous["errors"]:
        raise ValueError("successful original-R offline audit required")
    binary = prebuilt / "xclbin_hw_pr/graph_fpga.hw..xclbin"
    if artifact.identity(binary) not in previous["pins"]:
        raise ValueError("prebuilt differs from offline audit")
    design = read_table(output / "query/design.tsv", ["tool_version", "design", "part"])
    clocks = read_table(output / "query/clocks.tsv", ["name", "period_ns", "waveform", "generated"])
    if len(design) != 1 or not design[0]["part"].startswith("xcu55c-"):
        raise ValueError("one original U55C checkpoint required")
    names = set()
    for row in clocks:
        period = float(row["period_ns"])
        if row["name"] in names or not math.isfinite(period) or period <= 0:
            raise ValueError("unique positive finite checkpoint clocks required")
        names.add(row["name"])
        row["frequency_mhz"] = 1000 / period
    original = artifact.identity(prebuilt / IMPL / FILES[1])
    extracted = artifact.identity(output / "embedded.bit")
    if original["sha256"] != extracted["sha256"]:
        raise ValueError("xclbin BITSTREAM does not exactly match saved partial bitstream")
    timing_path = output / "query/timing.rpt"
    try:
        timing = {"checkpoint_native_constraints_passed": True, **parse_routed_timing(timing_path)}
    except ValueError as error:
        timing = {"checkpoint_native_constraints_passed": False, "reason": str(error)}
    return {"status": STATUS, "design": design[0], "checkpoint_clocks": clocks,
            "recorded_scaled_clocks_mhz": clock_requests(prebuilt / IMPL / "_new_clk_freq"),
            "data_clock_mhz_from_xclbin": previous["artifact"]["data_clock_mhz_from_xclbin"],
            "embedded_partial_bitstream_matches_saved_file": True,
            "partial_bitstream": original, "extracted_bitstream": extracted,
            "checkpoint_native_timing": timing, "timing_report": artifact.identity(timing_path),
            "route_report": artifact.identity(output / "query/route_status.rpt"),
            "constraints_modified": False, "implementation_or_bitstream_rewritten": False,
            "limitations": ["Saved bitstream equality does not prove that the checkpoint produced it.",
                            "Native checkpoint constraints are not a scaled-clock timing check.",
                            "Prebuilt equivalence to the clean author device source remains unverified."],
            **dict.fromkeys(CLAIMS, False)}
