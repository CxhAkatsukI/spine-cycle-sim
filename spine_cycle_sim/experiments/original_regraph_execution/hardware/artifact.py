"""Inspect a prebuilt original-R xclbin without programming a board."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.bitstream import SECTIONS, normalized_topology, parse_routed_timing


def identity(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular immutable artifact required")
    return {"path": str(path.resolve()), "sha256": sha256_file(path)}


def dump_command(binary: Path, directory: Path, utility: Path) -> list[str]:
    command = [str(utility), "--input", str(binary)]
    for section, name in SECTIONS.items():
        command += ["--dump-section", f"{section}:JSON:{directory / (name + '.json')}"]
    # XRT exports this JSON payload as RAW, not the section converter's JSON format.
    command += ["--dump-section", f"SYSTEM_METADATA:RAW:{directory / 'system.json'}"]
    return command


def inspect(directory: Path, timing: Path) -> dict:
    sections = {name: json.loads((directory / (name + ".json")).read_text()) for name in SECTIONS.values()}
    topology = normalized_topology(sections)
    if len([row for row in topology["clock"] if row[0] == "DATA"]) != 1:
        raise ValueError("one artifact DATA clock required")
    actual = next(row[2] for row in topology["clock"] if row[0] == "DATA")
    names = [row[0] for row in topology["kernels"]]
    expected = [f"littleKernelScatterGather:littleKernelScatterGather_{index}" for index in range(1, 12)]
    expected += [f"bigKernelScatterGather:bigKernelScatterGather_{index}" for index in range(1, 4)]
    expected += [f"{name}:{name}_1" for name in ("kernelLittleGSMerger", "kernelBigGSMerger",
                                                "kernelApply", "kernelHBMWrapper")]
    if sorted(names) != sorted(expected):
        raise ValueError("artifact is not the declared original 11-Little/3-Big example")
    try:
        timing_result = {"saved_report_passed": True, **parse_routed_timing(timing)}
    except ValueError as error:
        timing_result = {"saved_report_passed": False, "reason": str(error), "report": identity(timing)}
    json.loads((directory / "system.json").read_text())
    # A passing report alone does not link a checkpoint/clock to this xclbin.
    return {"status": "ARTIFACT_INSPECTED_NOT_BOARD_ADMITTED", "topology": topology,
            "data_clock_mhz_from_xclbin": actual, "saved_timing": timing_result,
            "system_metadata": identity(directory / "system.json"),
            "checkpoint_bitstream_timing_clock_pairing_verified": False,
            "author_device_source_equivalence_verified": False,
            "board_admitted": False, "publication_match": False}
