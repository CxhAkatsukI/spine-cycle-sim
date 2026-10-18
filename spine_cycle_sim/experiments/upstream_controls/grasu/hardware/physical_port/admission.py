"""Admit the explicitly adapted original-G profile, never an FPGA measurement."""

import argparse

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages import bitstream
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import runner_pins
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from .. import configuration as config, gates
from . import delivery, route_inputs

PASS = "ORIGINAL_G_EXTERNAL_PORT_ABI_CLOCK_TIMING_PASS_AWAITING_BOARD"


def verify_scope(remote, receipt):
    if receipt["unit"] != remote.unit or receipt["invocation"] != remote.invocation or \
            receipt["roots"]["packet"] != str(remote.capsule) or \
            receipt["roots"]["continuation"] != str(remote.attempt):
        raise ValueError("external-port returned service or packet scope changed")


def review(returned, output, *, receipt_sha256):
    receipt = delivery.verify(returned, receipt_sha256)
    pins = [identity(returned / "receipt.json"),
            *[identity(returned / row["member"]) for row in receipt["files"]], *runner_pins()]
    unchanged(pins)
    output.mkdir(parents=True, exist_ok=False)
    result = dict(status="CHECKING_EXTERNAL_PORT_CONTROL", errors=[], profile=route_inputs.PROFILE,
        source_modified=False, physical_interconnect_changed=True, **dict.fromkeys(config.FLAGS, False))
    try:
        binary = returned / "route/original_grasu.hw.xclbin"
        bitstream._dump(binary, output / "metadata")
        checked = gates.inspect_routed(output / "metadata", returned / "route")
        unchanged(pins)
        result.update(checked, status=PASS, candidate=identity(binary), pins=pins,
            scope="original_kernels_external_metadata_4to1_U55C_150MHz_not_publication_or_board_measurement")
    except BaseException as error:
        result.update(status="FAILED_RETAINED", errors=[repr(error)])
        raise
    finally:
        atomic_write_json(output / "summary.json", result)
    return result


if __name__ == "__main__":
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("returned", "output"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    print(review(**vars(parser.parse_args()))["status"], flush=True)
