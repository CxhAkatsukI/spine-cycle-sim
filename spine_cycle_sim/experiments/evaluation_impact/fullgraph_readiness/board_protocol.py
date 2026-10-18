"""Explicit host contracts sharing the bounded, exclusive FPGA executor."""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Experiment:
    name: str
    boundary: str
    pass_status: str
    prepare: Callable
    command: Callable
    analyze: Callable
    environment: Callable
    writes_result_file: bool = True


def gr_environment(device, bdf):
    return {"XCL_DEVICE_INDEX": str(device), "GRASU_REGRAPH_EXPECT_BDF": bdf,
            "GRASU_SHARDED_EVENT_TRACE": "1", "GRASU_UPDATE_REPEATS": "1"}


def gr_experiment():
    from . import board_analysis, board_preparation, board_study
    return Experiment("sharded_g_plus_r", board_analysis.BOUNDARY, board_study.PASS,
                      board_preparation.prepare, board_preparation.command,
                      board_analysis.analyze, gr_environment)
