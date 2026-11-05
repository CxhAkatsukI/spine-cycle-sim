"""Retime only Spine's CPU-qualified host; keep the frozen, clock-matched G+R sample."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import runner_pins
from ..board_execution import pair_resources
from . import clock_profile, clocks, dual_clock_resident, host_correction, repackage_hbm
from . import resident_board as board, resident_results
from .follow import unchanged
from .runtime import check_memory, execute, identity, save


def reference(path, comparator):
    old = json.loads(path.read_text())
    gate_paths = old["stage_gates"]["pins"][:3]
    r, g, route_manifest = (Path(pin["path"]) for pin in gate_paths)
    gate = dual_clock_resident.admit(r, g, route_manifest.parent)
    if (old["status"], old["stage_gates"], old["attempts"], old["repetitions_per_arm"],
            old["warmups"], old["boundary"]) != (dual_clock_resident.MEASURED, gate,
                ["spine", "gr"], 1, 0, dual_clock_resident.BOUNDARY):
        raise ValueError("one measured, matched-clock resident reference pair required")
    if identity(comparator)["sha256"] != resident_results.COMPARATOR_SHA256:
        raise ValueError("frozen comparator required")
    rows = old["row"]["rows"]
    pins = [identity(path), *old["inputs"], old["row"]["comparison_log"],
            *(pin for row in rows.values() for pin in (row["stdout"], row["stderr"])), rows["gr"]["ranks"]]
    unchanged(pins)
    for row in rows.values():
        clock_profile.validate_after(row["clock_preparation"], row["clock_evidence"], gate["resident_mhz"])
    return old, gate, pins


def validate_correction_log(text):
    cache, = [line for line in text.splitlines() if line.startswith("RESIDENT_CORRECTION_CACHE ")]
    correction, = [line for line in text.splitlines() if line.startswith("RESIDENT_CORRECTION ")]
    fields = lambda line: dict(item.split("=", 1) for item in line.split()[1:])
    first, second = fields(cache), fields(correction)
    if (first["scope"], first["included_in_dynamic_wall"], second["mode"],
            second["host_update_and_state_upload_in_dynamic_wall"]) != (
                "old_graph_only_single_batch", "0", "old_incoming_fp32_replay", "1"):
        raise ValueError("correction cache timing scope differs")
    return dict(resident_cache_bytes=int(first["bytes"]),
                old_graph_cache_preparation_ms=float(first["preparation_ms"]),
                dense_dangling_fallback=bool(int(second["dense_dangling_fallback"])))


def run(args):
    group = check_memory(args.memory_gib, require_live_reserve=False)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(status="PREDECLARED", fresh_samples=dict(spine=1, gr=0),
                  gr_sample_reused=True, repetitions_per_arm=1, attempts=[],
                  qualification=identity(args.qualification), reference_pair=identity(args.reference_pair),
                  boundary=dual_clock_resident.BOUNDARY, nominal_timing_pass=False,
                  limitation="single-batch host cache; old-graph index preparation excluded and reported")
    write = lambda: save(args.output / "results.json", report)
    write()
    try:
        qualified = host_correction.admit(args.qualification, args.spine_host)
        old, gate, pins = reference(args.reference_pair, args.comparator)
        if identity(args.spine_image)["sha256"] != board.SPINE_IMAGE_SHA256:
            raise ValueError("unchanged Spine kernel image required")
        case = old["case"]
        profile = gate["resident_mhz"]
        repackage_hbm.run(args.spine_image, args.verifier, profile[2],
                         args.output / "spine-clock-copy", profile=profile)
        args.spine_image = args.output / "spine-clock-copy/control.xclbin"
        args.gr_host = Path(gate["host"]["path"])
        pins += [*qualified, identity(args.spine_image), identity(args.verifier), *runner_pins()]
        report.update(case=case, dataset=case["dataset"], pins=pins, stage_gates=gate,
                      bdf=gate["bdf"], device=gate["device"], memory_gib=args.memory_gib)
        directory = args.output / case["dataset"]
        directory.mkdir()
        command = board.commands(args, Path(gate["image"]["path"]), case, directory,
                                 bdf=gate["bdf"], device=gate["device"])["spine"]
        expected = clocks.image(args.spine_image, args.output, "spine")

        def admission(status, memory):
            report.update(status=status, board_memory=memory)
            write()

        with pair_resources.admit(gate["device"], gate["bdf"], group, args.board_wait_seconds,
                admission, legacy_lock=board.LEGACY_LOCK, memory_gib=args.memory_gib) as (node, fd):
            unchanged(pins)
            prepared = clock_profile.prepare(args.spine_image, expected, profile, directory,
                "spine", fd, node, gate["bdf"], memory_gib=args.memory_gib)
            report.update(status="RUNNING_SPINE", attempts=["spine"])
            write()
            row = execute(command, directory, "spine", fd, node, gate["bdf"],
                          memory_gib=args.memory_gib, timeout=1800)
            row["clock_preparation"] = prepared
            row["clock_evidence"] = clocks.capture(gate["bdf"], expected, directory, "spine")
            clock_profile.validate_after(prepared, row["clock_evidence"], profile)
        rows = dict(spine=row, gr=old["row"]["rows"]["gr"])
        report["correction"] = validate_correction_log(Path(row["stdout"]["path"]).read_text())
        pair = resident_results.analyze(case, rows, args.comparator, directory, gate["bdf"])
        report.update(rows=rows, pair=pair, comparison_log=identity(directory / "pair.json"),
                      old_pair=old["row"]["pair"])
        unchanged(pins)
        report["status"] = ("MEASURED_SPINE_HOST_RETIME_REUSED_GR" if pair["meets_propagation_screen"]
                            else "RETAINED_WITHOUT_REQUIRED_PROPAGATION")
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events"] = (group / "memory.events").read_text()
        write()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("qualification", "reference-pair", "spine-host", "spine-image", "comparator", "verifier", "output"):
        parser.add_argument("--" + name, type=lambda s: Path(s).resolve(), required=True)
    parser.add_argument("--memory-gib", type=int, choices=(8, 16, 24, 32), required=True)
    parser.add_argument("--board-wait-seconds", type=int, default=21600)
    args = parser.parse_args()
    if not 1 <= args.board_wait_seconds <= 21600:
        raise ValueError("finite board admission wait required")
    print(run(args)["status"], flush=True)
