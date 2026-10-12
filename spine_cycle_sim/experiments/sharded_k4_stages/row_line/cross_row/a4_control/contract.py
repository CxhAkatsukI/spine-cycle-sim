"""Predeclared one-round diagnostic, not resource or publication matching."""

from pathlib import Path

from ...a4_control.contract import BOUNDARY, DOC, LIMITS
from ....sst_candidate import load_profile
from ..model_contract import PROFILE_ID

VERSION = "cross_row_a4_v1"
STATUS = "passed_cross_row_A4_functional_traffic_control_not_FPGA_or_resource_match"
BASIS = DOC / "adapter_optimization/row_line/a4_control/evidence"
BASIS_SHA = "a24a3543ad12abd72c7dc92d9e85dbf3f6c9444f35b8f56751b768eb8f4b249f"
PRE_EDIT_SHA = "5fb7b23690ed312d86057b2c36dcebbbfd02a277d923fe23bdf3c56d91743478"
HARNESS_CHANGE = "cpp/tests/routed_regraph/round_execution.hpp"
HARNESS = Path("cpp/tests/routed_regraph/cross_row")
TARGETS = ("original_regraph_sssp_real_round", "routed_regraph_cross_row_round")
ARMS = ("original", "whole_line", "cross_row")


def profile(root):
    return load_profile(root, root / f"configs/architectures/{PROFILE_ID}.json")


def metadata(arm):
    if arm not in ARMS[1:]:
        raise ValueError("unknown candidate arm")
    return {"version": VERSION, "cross_row_pipeline": int(arm == "cross_row"),
            "row_line_reads": 1, "empty_segment_exit_cycles": 0, "fixed_rounds": 1,
            "hardware_timing_admitted": False, "strict_resource_match_admitted": False}


def run_specs():
    return [(mode, latency, reverse, arm) for mode, latency in
            (("cold", 64), ("warm_update", 64), ("warm_update", 128))
            for reverse in (0, 1) for arm in ARMS]


def label(mode, latency, reverse, arm):
    return f"{mode}_lat{latency}_reverse{reverse}_{arm}"
