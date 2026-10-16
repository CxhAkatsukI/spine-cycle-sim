"""Declare the three board matrices; retain each existing numerical validator."""

from pathlib import Path

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ..continuous_board.execution import study as board
from ..continuous_handoff import execution as handoff
from ..metadata_refresh import analysis as metadata, delivery
from ..native_board import execution as native, analysis
from . import route


def metadata_identity(preflight):
    report = delivery.validate(preflight)
    source = (preflight / "source/continuous_board/xrt.hpp").read_text()
    if 'std::getenv("CONTINUOUS_G_EXPECT_BDF")' not in source or "CL_DEVICE_PCIE_BDF" not in source or \
            source.index("CL_DEVICE_PCIE_BDF") > source.index("cl::Program(context"):
        raise ValueError("metadata host lacks the pre-programming device guard")
    contract = {**report["contract"], "cases": [report["contract"]["case"]]}
    return {**report, "contract": contract}, [identity(preflight / "results.json"), identity(preflight / "probe"),
                                               *report["pins"]]


def metadata_analyze(case, stdout, stderr, *, bdf):
    if case != metadata.CASE:
        raise ValueError("metadata board case changed")
    return metadata.analyze(stdout, stderr, bdf=bdf)


def plans(native_preflight, metadata_preflight, gr_preflight):
    sources = tuple(sorted(Path(__file__).parent.glob("*.py")))
    rows = (
        ("native_g", native_preflight, native.host_identity, analysis.analyze,
         "NATIVE_G_BOARD_MATRIX_PASS_NOT_BASELINE_ADMISSION", 1,
         "five-shard native hot/cold G, full physical PMA/padding; not original-G performance"),
        ("metadata_refresh", metadata_preflight, metadata_identity, metadata_analyze, metadata.BOARD_PASS, 1,
         "same OpenCL BOs across two directory generations; single-segment row consumption, not binary-search refresh"),
        ("resident_gr", gr_preflight, handoff.host_identity, handoff.events.analyze, handoff.BOARD_PASS, 9,
         handoff.BOUNDARY),
    )
    return [(name, preflight, board.Experiment(host, analyze, status, boundary, sources, route.review), count)
            for name, preflight, host, analyze, status, count, boundary in rows]
