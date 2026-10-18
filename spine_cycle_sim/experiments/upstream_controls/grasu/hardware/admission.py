"""Revalidate sealed original-G source/ABI/HLS/timing locally, without a board."""

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages import bitstream
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import runner_pins
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from . import configuration as config, delivery, gates, records

PASS = "ORIGINAL_G_SOURCE_ABI_CLOCK_TIMING_PASS_AWAITING_BOARD"


def review(returned, output, *, receipt_sha256):
    receipt = delivery.verify(returned, receipt_sha256)
    execution, manifest = records.completed(returned / "route", remote_route=Path(receipt["remote_attempt"]),
                                           remote_packet=Path(receipt["remote_packet"]))
    indexed = {row["member"]: row["source"] for row in receipt["files"]}
    remote_pins = {row["path"]: row["sha256"] for row in manifest["pins"]}
    required = ("route/environment.json", "packet/packet.json", "packet/link.cfg",
                *["packet/source/" + name for name in config.SOURCE_HASHES])
    if receipt.get("checked_remote_pin_count") != len(manifest["pins"]) or \
            execution.get("manifest") != indexed["route/manifest.json"] or \
            execution.get("xclbin") != indexed["route/original_grasu.hw.xclbin"] or \
            execution.get("host") != receipt.get("host") or any(
                remote_pins.get(indexed[member]["path"]) != indexed[member]["sha256"] for member in required):
        raise ValueError("original G return differs from source/manifest/artifact closure")
    pins = [identity(returned / "receipt.json"),
            *[identity(returned / row["member"]) for row in receipt["files"]], *runner_pins()]
    unchanged(pins)
    output.mkdir(parents=True, exist_ok=False)
    result = {"status": "CHECKING_ORIGINAL_G", "errors": [], **dict.fromkeys(config.FLAGS, False)}
    try:
        for name, row in zip(config.KERNELS, execution["xos"]):
            member = "route/xo/" + name + ".hw.xo"
            checked = gates.inspect_xo(returned / member, name)
            if row["abi"]["xo"] != indexed[member] or any(
                    checked[key] != row["abi"][key] for key in checked if key != "xo"):
                raise ValueError("original G exported ABI differs from completed build")
            member = "route/hls/" + name + "/" + name + "_csynth.xml"
            checked = gates.inspect_hls((returned / member).parent, name)
            if row["hls"]["report"] != indexed[member] or any(
                    checked[key] != row["hls"][key] for key in checked if key != "report"):
                raise ValueError("original G HLS record differs from completed build")
        binary = returned / "route/original_grasu.hw.xclbin"
        bitstream._dump(binary, output / "metadata")
        checked = gates.inspect_routed(output / "metadata", returned / "route")
        unchanged(pins)
        result.update(checked, status=PASS, candidate=identity(binary), pins=pins,
                      scope="original_source_U55C_150MHz_not_original_publication_or_board_measurement")
    except BaseException as error:
        result["status"] = "FAILED_RETAINED"
        result["errors"].append(repr(error))
        raise
    finally:
        atomic_write_json(output / "summary.json", result)
    return result
