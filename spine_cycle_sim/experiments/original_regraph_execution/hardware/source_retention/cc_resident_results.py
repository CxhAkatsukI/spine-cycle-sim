"""Replay one host-pack-to-readback CC pair after external artifact admission."""

import math

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.board_analysis import single


def _require(record, expected, message):
    if any(record.get(key) != str(value) for key, value in expected.items()):
        raise ValueError(message)


def _wall(record, earlier, later):
    start_to_inner, start_to_end = (float(record[key]) for key in (earlier, later))
    if not 0 < start_to_inner <= start_to_end < math.inf:
        raise ValueError("invalid CC timing interval")
    return start_to_end


def analyze(workload, gr_stdout, spine_stdout, *, bdf):
    """Check the log contract; the caller still owns image, board and input pins."""
    vertices, edges, updates = (workload[key] for key in ("vertices", "edges", "updates"))
    gr, spine = gr_stdout.splitlines(), spine_stdout.splitlines()
    _require(single(gr, "GRASU_REGRAPH_DEVICE"), {"bdf": bdf}, "unexpected G+R board")
    _require(single(gr, "GRASU_SHARDED_UPDATE_REPEAT_CONFIG"),
             {"repeats": 1, "restore_pma_between_repeats": 1}, "expected one G+R sample")
    dims = dict(vertices=vertices, logical_updates=updates, physical_updates=updates,
                final_edges=edges + updates, resident_state="old_graph_converged",
                oracle_converged=1)
    initial = single(gr, "CC_PMA_NATIVE_SHARDED_INPUT")
    result = single(gr, "CC_PMA_NATIVE_SHARDED_RESULT")
    _require(initial, dict(dims, static_edges=edges), "G+R workload or old state differs")
    _require(result, dict(dims, status="PASS", mismatches=0, hardware_converged=1,
                          k4_frontends=4, shared_regraph_downstream=1, conversion_cost="absent"),
             "G+R result does not match the resident CC oracle or configuration")
    gr_steps = int(result["executed_supersteps"])
    if not 1 <= gr_steps <= 256:
        raise ValueError("invalid G+R resident superstep count")
    gr_wall = single(gr, "SHARDED_RESIDENT_BATCH_WALL")
    _require(gr_wall, dict(algorithm="CC_PMA_NATIVE", status="PASS", layout="trace_aware",
                           physical_update_mapping="offline"), "expected matching G+R wall scope")
    gr_ms = _wall(gr_wall, "pack_upload_and_host_seed_ms", "pack_to_final_readback_ms")

    spine_ms, spine_rounds, hot = validate_spine(workload, spine)
    speedup = gr_ms / spine_ms
    if not math.isfinite(speedup) or speedup <= 0:
        raise ValueError("invalid paired speedup")
    return {"boundary": "resident_old_graph_host_pack_to_final_readback",
            "gr_ms": gr_ms, "spine_ms": spine_ms, "gr_over_spine": speedup,
            "gr_supersteps": gr_steps, "spine_rounds": spine_rounds,
            "spine_hot_layout": hot, "gr_layout": "trace_aware", "gr_physical_update_mapping": "offline"}


def validate_spine(workload, spine):
    vertices, updates = workload["vertices"], workload["updates"]
    spine_wall = single(spine, "CC_RESIDENT_WALL")
    hot = spine_wall.get("hot")
    if hot not in ("0", "1"):
        raise ValueError("missing Spine CC layout mode")
    context = dict(sample=0, order=0, hot=hot, full=0, batch=0)
    _require(spine_wall, dict(context, vertices=vertices, physical_records=updates),
             "Spine CC wall receipt does not match the workload")
    _require(single(spine, "CC_BOOTSTRAP_PASS"), dict(context, valid=1),
             "Spine CC bootstrap was not validated")
    update = single(spine, "CC_UPDATE_PASS")
    _require(update, dict(context, valid=1, physical_records=updates, logical_deletions=0),
             "Spine CC did not validate the requested insertion batch")
    _require(single(spine, "CC_REPAIR_PASS"),
             dict(vertices=vertices, updates=1, all_raw_labels_checked=1,
                  all_raw_graphs_checked=1, all_round_work_checked=1),
             "Spine CC graph, label and work checks are required")
    spine_rounds = int(update["rounds"])
    if spine_rounds < 0:
        raise ValueError("invalid Spine CC propagation-round count")
    spine_ms = _wall(spine_wall, "batch_resident_to_final_readback_ms",
                     "host_pack_to_final_readback_ms")
    return spine_ms, spine_rounds, hot == "1"
