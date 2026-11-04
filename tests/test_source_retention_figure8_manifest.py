import csv
import json

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    figure8_inputs,
    figure8_manifest,
)


@pytest.fixture
def frozen(tmp_path):
    graph = tmp_path / "graph.slice"
    graph.write_text("# vertices=3\n0 1 42 1\n")
    rows = []
    for dataset, batch in figure8_manifest.CASES:
        updates = tmp_path / f"{dataset}_u{batch}.slice"
        updates.write_text("# vertices=3\n" + "1 2 17 1\n" * batch)
        for arm in ("spine", "gr"):
            run = tmp_path / f"{dataset}_u{batch}_{arm}"
            run.mkdir()
            (run / "config.json").write_text(json.dumps({
                "mode": "update", "arm": arm, "graph": str(graph),
                "updates": str(updates),
            }))
            rows.append(dict(dataset=dataset, updates=batch, arm=arm, source=1,
                             algorithm="update_only", vertices=3, initial_edges=1,
                             evidence=str(run), report_sha256="same"))
        figure8_inputs.prepare(graph, updates, tmp_path / f"{dataset}_u{batch}.graph",
                               vertices=3, edges=1, batch_size=batch)
    arms = tmp_path / "arms.csv"
    with arms.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return arms, tmp_path


def test_records_all_pairs_with_content_identities(frozen):
    result = figure8_manifest.manifest(*frozen)
    assert [(row["dataset"], row["updates"]) for row in result["cases"]] == list(
        figure8_manifest.CASES)
    row = result["cases"][0]
    assert row["graph"]["bytes"] > 0
    assert row["spine_config"]["sha256"] != row["gr_config"]["sha256"]
    assert len(row["native_g_input"]["sha256"]) == 64


def test_rejects_native_content_change_with_unchanged_dimensions(frozen):
    _, native_dir = frozen
    native = native_dir / "AU_u64.graph"
    native.write_text(native.read_text().replace("0 1 42", "0 1 41"))
    with pytest.raises(ValueError, match="native graph differs"):
        figure8_manifest.manifest(*frozen)


def test_rejects_arms_using_different_batches(frozen):
    _, native_dir = frozen
    config_path = native_dir / "AU_u64_gr" / "config.json"
    config = json.loads(config_path.read_text())
    config["updates"] = str(native_dir / "AU_u512.slice")
    config_path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="do not use the same inputs"):
        figure8_manifest.manifest(*frozen)


def test_rejects_duplicate_arm(frozen):
    arms, _ = frozen
    lines = arms.read_text().splitlines()
    arms.write_text("\n".join([*lines, lines[1], ""]))
    with pytest.raises(ValueError, match="duplicate arm"):
        figure8_manifest.manifest(*frozen)
