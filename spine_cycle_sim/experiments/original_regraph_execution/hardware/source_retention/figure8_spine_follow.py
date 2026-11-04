"""Measure one changed Fig. 8 Spine host against a frozen, checked G arm."""

import argparse
import json
from pathlib import Path
import time

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import board_memory
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import containment
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from . import clocks, figure8_au_pair as au, figure8_matrix as matrix
from .active_min_admission import checked
from .runtime import check_memory, identity, save


def replay_prior(prior, key):
    if (prior["boundary"] != au.BOUNDARY or prior["requested_runs_per_arm"] != 1
            or prior["warmups"] != 0):
        raise ValueError("expected a native one-shot setup comparison")
    manifest = prior["manifest"]
    cases = matrix.load_cases(manifest, manifest["sha256"])
    case = cases[key]
    hosts, reference, libraries, anchor_timers, anchor_arms = matrix.load_anchor(
        prior["anchor"], cases[matrix.ANCHOR])
    old, = [row for row in prior["cases"] if (row["dataset"], row["updates"]) == key]
    graph = checked(case["native_g_input"])
    if old["input"] != case["native_g_input"]:
        raise ValueError("case input differs from the pinned manifest")
    if key == matrix.ANCHOR:
        if (old["status"] != "REUSED_MEASURED_ANCHOR" or old["attempts"] or old["arms"]
                or old["timers"] != anchor_timers
                or old["speedup_gr_over_spine"] != matrix.ratio(anchor_timers)):
            raise ValueError("case differs from the independently replayed AU/512 pair")
        return case, {**old, "arms": anchor_arms}, hosts, reference, libraries
    if old["status"] != "MEASURED_SETUP_ONLY" or old["attempts"] != ["spine", "gr"]:
        raise ValueError("case lacks an admitted one-shot pair")
    arms = old["arms"]
    oracle = arms["gr"]["pma_oracle"]
    au.pma_oracle(oracle)
    commands = {
        "spine": matrix.spine_command(hosts["spine"]["path"], reference["spine"]["binary"]["path"], graph),
        "gr": au.gr_command(hosts["gr"]["path"], reference["gr"]["binary"]["path"], graph, oracle["path"]),
    }
    for arm, value in arms.items():
        run = value["run"]
        checked(run["stderr"])
        matrix.same_clock(clocks.replay(value["clock_evidence"]), reference[arm])
        if (run["command"] != matrix.AFFINITY + list(map(str, commands[arm]))
                or value["timer"] != matrix.inspect(run, arm, case)):
            raise ValueError(f"frozen {arm} command or timings differ from raw evidence")
    return case, old, hosts, reference, libraries


def run(args):
    predecessor = identity(args.prior)
    if predecessor["sha256"] != args.prior_sha256 or not 1 <= args.wait_seconds <= 3600:
        raise ValueError("predecessor identity or wait bound is invalid")
    key = args.dataset, args.updates
    case, old, hosts, reference, libraries = replay_prior(json.loads(checked(predecessor).read_text()), key)
    new_host = identity(args.spine_host)
    if new_host["sha256"] == hosts["spine"]["sha256"]:
        raise ValueError("Spine executable did not change; refusing to rerun")
    memory = board_memory.policy()
    group = check_memory(memory["tree_memory_gib"], require_live_reserve=False)
    board_memory.validate(containment.verify(group)["limits"], memory)
    reservation = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    args.output.mkdir(parents=True, exist_ok=False)
    row = dict(dataset=key[0], updates=key[1], input=old["input"], attempts=[],
               arms={"gr": old["arms"]["gr"]})
    report = dict(row=row, predecessor=predecessor, previous_spine_host=hosts["spine"],
                  spine_host=new_host, previous_spine=old["arms"]["spine"],
                  boundary=au.BOUNDARY, runner=identity(__file__), memory=memory)

    def checkpoint():
        save(args.output / "results.json", report)

    try:
        matrix.measure(case, row, args.output, time.monotonic() + args.wait_seconds, reservation,
                       memory, {**hosts, "spine": new_host}, reference, libraries, checkpoint,
                       arms=("spine",))
        checked(new_host)
        row["status"] = "MEASURED_HOST_REVISION_SETUP_ONLY"
    except BaseException as error:
        row.update(status="FAILED_RETAINED", error=repr(error))
        row.pop("speedup_gr_over_spine", None)
        raise
    finally:
        reservation.release()
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events"] = (group / "memory.events").read_text()
        checkpoint()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("prior", "output", "spine-host"):
        parser.add_argument("--" + option, required=True, type=lambda path: Path(path).resolve())
    parser.add_argument("--prior-sha256", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--updates", required=True, type=int)
    parser.add_argument("--wait-seconds", type=int, default=300)
    run(parser.parse_args())
