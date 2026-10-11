"""Freeze a bounded completion observation and isolated model-only controls."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .execution import identity


def package_completion_checkpoint(root: Path, data: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if (output / "raw_completion.tar.gz").exists() or (output / "completion.json").exists():
        raise FileExistsError("completion observation is already frozen")
    parent = root / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst"
    probe = data / "wk_original_20m"
    isolated = data / "isolated_axi_final"
    state = json.loads((probe / "result.json").read_text())
    config = json.loads((probe / "run_config.json").read_text())
    manifest = json.loads((probe / "manifest.json").read_text())
    controls = json.loads((isolated / "run.stdout.txt").read_text())
    pins = json.loads((isolated / "manifest.json").read_text())
    parent_manifest = json.loads(Path(manifest["parent"]["path"]).read_text())
    expected_plugin = json.loads((parent / "sst.json").read_text())["legacy"]["candidate_identity"]["plugin_sha256"]
    if (config["max_cycles"] != 20000000 or state["observed_cycles"] != config["max_cycles"]
            or state["success"] or state["done"] or state["failed"]
            or config["arm"] != "original" or config["fixture"] != parent_manifest["config"]["fixture"]
            or manifest["plugin"]["plugin_sha256"] != expected_plugin):
        raise ValueError("expected intentionally capped original WK observation is missing")
    records = {}
    for name, directory in (("probe", probe), ("build", isolated), ("run", isolated)):
        prefix = "sst" if name == "probe" else name
        record = json.loads((directory / f"{prefix}.resources.json").read_text())
        if record["exit_code"] or record["timed_out"]:
            raise ValueError("completion observation process failed")
        records[name] = record
    rows = {row["case"]: row for row in controls["rows"]}
    if (len(rows) != 3 or len(controls["rows"]) != 3
            or set(rows) != {"held_stream", "drained_stream", "ordinary_read"}
            or rows["held_stream"]["write_issue"] < 200
            or any(rows[name]["write_issue"] >= 200 for name in ("drained_stream", "ordinary_read"))
            or not all(row["registration_order_equal"] for row in rows.values())):
        raise ValueError("complete isolated stall and non-stall controls required")
    all_pins = [pins[name] for name in ("source", "core", "parent")] + [manifest["parent"], manifest["fixture"]]
    if any(identity(Path(pin["path"])) != pin for pin in all_pins):
        raise ValueError("observation source, core or input changed")
    files = {}
    for directory in (probe, data / "isolated_axi", isolated):
        for path in directory.rglob("*"):
            if path.is_file(): files["campaign/" + str(path.relative_to(data))] = path
    for name in ("source", "core"):
        files["tested/" + Path(pins[name]["path"]).name] = Path(pins[name]["path"])
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    archive_path = output / "raw_completion.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, path in sorted(files.items()): archive.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"]))["sha256"] != pin["sha256"] for pin in index):
        raise ValueError("completion observation changed during packaging")
    atomic_write_json(output / "completion_raw_index.json", {"archive": identity(archive_path), "files": index})
    result = {"schema_version": 1, "status": "MODEL_CROSS_OPERATION_STALL_REPRODUCED_NOT_FIXED",
              "hardware_timing_admitted": False, "model_changed": False,
              "parent_evidence": identity(parent / "sst_raw_index.json"),
              "capped_probe": state, "isolated_controls": controls, "resources": records,
              "limits": ["capped_probe_is_not_a_complete_workload_correctness_run",
                         "isolated_controls_measure_model_behavior_not_FPGA_AXI_channels",
                         "removing_this_stall_does_not_explain_overall_model_underprediction"]}
    atomic_write_json(output / "completion.json", result)
    return result
