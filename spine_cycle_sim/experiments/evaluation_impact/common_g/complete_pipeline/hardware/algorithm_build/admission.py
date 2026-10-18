"""Read-only local admission of sealed algorithm links, before board execution."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages import bitstream
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ....search_pipeline.synthesis import unchanged
from . import artifacts, commands, inputs, topology


def review(returned, sources, output, *, receipt_sha256):
    receipt = artifacts.verify(returned, receipt_sha256)
    source = inputs.verify(sources)
    source_pin = identity(sources / "sources.json")
    execution, manifest = artifacts.completed(returned / "route")
    compiled = json.loads((returned / "compile/manifest.json").read_text())
    checked = json.loads((returned / "route/placement-review.json").read_text())
    indexed = {row["member"]: row["source"] for row in receipt["files"]}
    remote_pins = {row["path"]: row["sha256"] for row in manifest["pins"]}
    expected_kernel_types = commands.PURE if manifest["algorithm"] == "connected_components" else commands.PR
    if indexed["sources.json"]["sha256"] != source_pin["sha256"] or \
            compiled.get("source_manifest") != indexed["sources.json"] or \
            any(row.get("integration_revision") != source["integration_revision"] for row in
                (receipt, execution, manifest, compiled)) or \
            any(row.get("algorithm") != manifest["algorithm"] for row in (receipt, execution, compiled)) or \
            set(checked["interfaces"]) != expected_kernel_types or \
            {row["kernel"] for row in compiled["compiles"]} != expected_kernel_types or \
            len(compiled["compiles"]) != len(expected_kernel_types) or \
            execution.get("host") != receipt.get("host") or \
            execution["route"].get("cwd") != receipt.get("remote_route") or \
            execution.get("manifest") != indexed["route/manifest.json"] or \
            execution.get("xclbin") != indexed["route/candidate.hw.xclbin"] or \
            receipt.get("checked_remote_pin_count") != len(manifest["pins"]):
        raise ValueError("returned link differs from requested algorithm/source closure")
    for member in ("sources.json", "compile/manifest.json", "compile/execution.json",
                   "route/placement-review.json", "route/environment.json", "route/link.cfg"):
        pin = indexed[member]
        if remote_pins.get(pin["path"]) != pin["sha256"]:
            raise ValueError("missing remote input verification: " + member)
    compiler = json.loads((returned / "route/environment.json").read_text())["tools"]["v++"]["invocation"]
    remote_route = Path(receipt["remote_route"])
    expected_command = [compiler, "--target", "hw", "--link", "--kernel_frequency", "150",
                        "--config", str(remote_route / "link.cfg"), "-o",
                        str(remote_route / "candidate.hw.xclbin"),
                        *[row["xo"] for row in compiled["compiles"]],
                        "--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]
    if manifest["command"] != expected_command:
        raise ValueError("returned link command does not cover the declared algorithm XOs")
    pins = [identity(returned / "receipt.json"), source_pin,
            *[identity(returned / row["member"]) for row in receipt["files"]],
            *[identity(path) for path in sorted(Path(__file__).parent.glob("*.py"))]]
    unchanged(pins)
    output.mkdir(parents=True, exist_ok=False)
    result = {"status": "CHECKING_ROUTED_ARTIFACT", "errors": [], **dict.fromkeys(artifacts.FLAGS, False)}
    try:
        binary = returned / "route/candidate.hw.xclbin"
        sections = bitstream._dump(binary, output / "metadata")
        result.update(topology.check(sections, (returned / "route/link.cfg").read_text(), checked))
        timing = bitstream.parse_routed_timing(returned / "route/timing.rpt")
        unchanged(pins)
        result.update(status="ALGORITHM_ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD",
                      algorithm=manifest["algorithm"], integration_revision=source["integration_revision"],
                      candidate=identity(binary), timing=timing, pins=pins,
                      scope="algorithm_source_clock_CU_HBM_stream_timing_not_board_or_publication")
    except BaseException as error:
        result["status"] = "FAILED_RETAINED"
        result["errors"].append(repr(error))
        raise
    finally:
        atomic_write_json(output / "summary.json", result)
    return result
