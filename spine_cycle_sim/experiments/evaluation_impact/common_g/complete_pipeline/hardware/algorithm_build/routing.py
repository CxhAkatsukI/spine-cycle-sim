"""Prepare one explicit placement change; preserve every compiled kernel and ABI."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ....search_pipeline.synthesis import unchanged
from ..remote.capsule import configuration
from . import commands, inspection, review

PASS = "EXPORT_AND_STORAGE_SCREEN_PASS_NOT_RTL_OR_ROUTE_ADMISSION"


def relocate_little(contents):
    kernels, placements = inspection.topology(contents)
    if len(kernels.get("lksg_stream", [])) != 4 or placements.get("lksg_stream_4") != "SLR0":
        raise ValueError("expected four Little CUs and explicit fourth-CU SLR0 placement")
    section, lines, count = "", [], 0
    for original in contents.splitlines():
        key, equal, value = original.partition("=")
        if original.strip().startswith("["):
            section = original.strip()[1:-1]
        if section == "connectivity" and equal and key.strip() == "slr" and \
                value.partition("#")[0].strip() == "lksg_stream_4:SLR0":
            original = "slr=lksg_stream_4:SLR1"
            count += 1
        lines.append(original)
    changed = "\n".join(lines) + "\n"
    groups, new_placements = inspection.topology(changed)
    if count != 1 or groups != kernels or new_placements != {**placements, "lksg_stream_4": "SLR1"}:
        raise ValueError("single-CU placement relocation changed topology")
    return changed


def prepare(compilation, storage, output, platform, compiler):
    original = review.run(compilation, storage, output / "original-review")
    if original["status"] not in (PASS, "STORAGE_CONFLICT_REQUIRES_PLACEMENT_REVIEW"):
        raise ValueError("original export has a non-placement resource conflict")
    manifest = json.loads((compilation / "manifest.json").read_text())
    compiles = manifest["compiles"]
    configs = [path for path in (compilation / "packet/config").glob("*.cfg")
               if "[connectivity]" in path.read_text()]
    if len(configs) != 1:
        raise ValueError("one compiled connectivity file required")
    contents = relocate_little(configs[0].read_text())
    config = output / "link.cfg"
    config.write_text(configuration(contents, output, platform))
    capacity, pins = review.capacities(storage)
    checked = inspection.inspect(config, compiles, capacity["physical"], capacity["platform"])
    if checked["status"] != PASS or checked["connections"]["automatic_memory_masters"]:
        raise ValueError("explicit memory placement and all resource screens must pass")
    pins.extend(original["inputs"])
    pins.append(identity(output / "original-review/results.json"))
    pins.extend(checked.pop("pins"))
    atomic_write_json(output / "placement-review.json", checked)
    pins.append(identity(output / "placement-review.json"))
    expected = commands.PURE if manifest["algorithm"] == "connected_components" else commands.PR
    if {row["kernel"] for row in compiles} != expected or len(compiles) != len(expected):
        raise ValueError("all original algorithm XOs required")
    argv = [str(compiler), "--target", "hw", "--link", "--kernel_frequency", "150",
            "--config", str(config), "-o", str(output / "candidate.hw.xclbin"),
            *[row["xo"] for row in compiles], "--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]
    unchanged(pins)
    return {"algorithm": manifest["algorithm"], "integration_revision": manifest["integration_revision"],
            "command": argv, "pins": pins, "clock_mhz": 150,
            "placement_change": {"instance": "lksg_stream_4", "from": "SLR0", "to": "SLR1"},
            "scope": "experimental_link_before_algorithm_RTL_admission_not_performance_evidence",
            "rtl_admitted": False, "board_admitted": False, "publication_match": False}
