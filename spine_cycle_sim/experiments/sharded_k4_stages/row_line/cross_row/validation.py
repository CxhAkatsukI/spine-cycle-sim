"""Exact production ABI, packet gates and immutable whole-line reference."""

from collections import Counter
import re

from ...routing import adapter_interface
from ..validation import FLAGS as REFERENCE_FLAGS, compare_traffic
from ..occupied_rows.study import BASE, BASE_SHA, XO_HASHES


FLAGS = REFERENCE_FLAGS | {"GRASU_REGRAPH_CROSS_ROW_PIPELINE": "1"}
REFERENCE_SHA = XO_HASHES["candidate"]
STATUS = "CROSS_ROW_PRODUCTION_AXI_PASS_NOT_ROUTED"
CLAIM = "finite_cross_row_production_HLS_synthetic_AXI_RTL_not_FPGA_or_calibration"


def require_xos(reference, candidate):
    before, old_flags = adapter_interface(reference)
    after, new_flags = adapter_interface(candidate)
    for actual, expected in ((old_flags, REFERENCE_FLAGS), (new_flags, FLAGS)):
        if {key: value for key, value in actual.items() if key.startswith("GRASU_")} != expected:
            raise ValueError("exact production flags required, without test-only depths")
    if before != after:
        raise ValueError("cross-row candidate changed the external ABI")
    return {"interface": after, "flags": {"reference": old_flags, "candidate": new_flags}}


def require_functional(text):
    records = re.findall(r"^ROW_PREFETCH_EQUIVALENCE status=PASS cases=(\d+) packets=(\d+) "
                         r"skip_empty=1 row_line=1 cross_row=1$", text, re.M)
    if Counter(records) != {("254", "1482"): 3}:
        raise ValueError("all three cross-row format/packet matrices required")


def compare(reference, candidate, frozen):
    if reference != frozen["arms"]["candidate"]:
        raise ValueError("whole-line reference must reproduce all original RTL handshakes")
    return compare_traffic(reference, candidate)
