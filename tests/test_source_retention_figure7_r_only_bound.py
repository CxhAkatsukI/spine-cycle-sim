import json
from decimal import Decimal

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import figure7_r_only_bound as audit


@pytest.fixture
def pair(tmp_path):
    graph = "/frozen/pk.graph"
    row = dict(algorithm="weighted_sssp", dataset="PK", status="RESIDENT_PAIR_PASS",
               gr_wall_ms="12.5", spine_wall_ms="5.5")
    summary = dict(algorithm=row["algorithm"], boundary=audit.BOUNDARY, measured_pairs=1,
                   excluded_warmup_pairs=0, gr_wall_ms=12.5, spine_wall_ms=5.5,
                   vertices=3, logical_updates=1, physical_updates=1)
    pins = [dict(path=name, sha256=digest) for name, digest in audit.HOST_SOURCES.items()]
    case = tmp_path / "sssp-pk"
    sample = case / "sample-1"
    sample.mkdir(parents=True)
    receipt = dict(status=row["status"], boundary=audit.BOUNDARY, board_tested=True, summary=summary,
                   config=dict(dataset="PK", expected_pins=pins, graph=graph), samples=[dict(warmup=False)])
    (case / "results.json").write_text(json.dumps(receipt))
    (sample / "gr.stdout.txt").write_text(
        "GRASU_SHARDED_UPDATE_REPEAT_CONFIG repeats=1\n"
        "WEIGHTED_PMA_NATIVE_SHARDED_INPUT final_edges=17\n"
        "WEIGHTED_PMA_NATIVE_SHARDED_TIMING grasu_ms=6.5 barrier_ms=7 setup_inclusive_ms=12.5\n"
        "WEIGHTED_PMA_NATIVE_SHARDED_RESULT status=PASS resident_state=old_graph_converged "
        "hardware_converged=1 oracle_converged=1 vertices=3 logical_updates=1 physical_updates=1 "
        "k4_frontends=4 executed_supersteps=2 final_edges=17\n"
    )
    (sample / "spine.stdout.txt").write_text(
        f"SPINE_RESIDENT_BENCHMARK_PASS boundary={audit.BOUNDARY} case={graph}:final "
        "wall_ms=5.5 vertices=3 logical_updates=1 physical_updates=1\n"
    )
    return row, tmp_path, sample


def test_zero_r_bound_uses_g_span_only(pair):
    row, run, sample = pair
    result = audit.audit_row(row, run)
    assert result["survives_zero_post_update_cost"] is True
    assert result["remaining_budget_to_tie_ms"] == Decimal("-1")
    gr_log = sample / "gr.stdout.txt"
    gr_log.write_text(gr_log.read_text().replace("grasu_ms=6.5", "grasu_ms=4.5"))
    result = audit.audit_row(row, run)
    assert result["survives_zero_post_update_cost"] is False
    assert result["remaining_budget_to_tie_ms"] == Decimal("1")


def test_full_scan_floor_does_not_count_padding_or_extra_rounds(pair):
    row, run, sample = pair
    gr_log = sample / "gr.stdout.txt"
    gr_log.write_text(gr_log.read_text().replace("final_edges=17", "final_edges=4800001")
                      .replace("grasu_ms=6.5", "grasu_ms=4.5")
                      .replace("executed_supersteps=2", "executed_supersteps=8 pma_slots_total=9000000"))
    result = audit.audit_row(row, run)
    expected = Decimal(150001) / 150000
    assert result["k4_one_scan_floor_ms"] == expected
    assert result["g_plus_k4_one_scan_floor_ms"] == Decimal("4.5") + expected
    assert result["survives_zero_post_update_cost"] is False
    assert result["survives_one_k4_full_scan"] is True


@pytest.mark.parametrize("old,new", [("k4_frontends=4", "k4_frontends=5"),
                                    ("executed_supersteps=2", "executed_supersteps=0"),
                                    ("INPUT final_edges=17", "INPUT final_edges=99")])
def test_rejects_mismatched_scan_contract(pair, old, new):
    row, run, sample = pair
    gr_log = sample / "gr.stdout.txt"
    gr_log.write_text(gr_log.read_text().replace(old, new))
    with pytest.raises(ValueError, match="frozen raw timing"):
        audit.audit_row(row, run)


@pytest.mark.parametrize("old,new", [("pk.graph", "wrong.graph"), ("wall_ms=5.5", "wall_ms=5.6")])
def test_rejects_mismatched_raw_pair(pair, old, new):
    row, run, sample = pair
    spine_log = sample / "spine.stdout.txt"
    spine_log.write_text(spine_log.read_text().replace(old, new))
    with pytest.raises(ValueError, match="frozen raw timing"):
        audit.audit_row(row, run)
