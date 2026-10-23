"""Reject incomplete arms and retain failed rows instead of projecting values."""

import json
import math
from pathlib import Path
from statistics import median


def records(step, prefix):
    if step["exit_code"] or step["timed_out"]:
        raise ValueError("bounded process failed or timed out; inspect retained logs")
    text = Path(step["stdout"]).read_text()
    if "REFRESH_COMPLETE" not in text:
        raise ValueError("missing completion marker")
    return [json.loads(line[len(prefix):]) for line in text.splitlines() if line.startswith(prefix)]


def device(step):
    rows = records(step, "WARM_RESULT ")
    if len(rows) != 1 or not rows[0].get("correctness") or not rows[0].get("ledger_closed"):
        raise ValueError("one complete correctness/ledger-admitted arm required")
    row = rows[0]
    if row["cycles"] <= 0 or row["read_bytes"] + row["write_bytes"] <= 0:
        raise ValueError("empty device window")
    return row


def host(step):
    rows = records(step, "HOST_RESULT ")
    if len(rows) != 5 or {row["repeat"] for row in rows} != set(range(5)):
        raise ValueError("five host repetitions required")
    if len({(r["initial_h2d_bytes"], r["update_h2d_bytes"]) for r in rows}) != 1:
        raise ValueError("host preparation changed its transfer sizes")
    if any(not math.isfinite(r[k]) or r[k] < 0 for r in rows
           for k in ("nanoseconds", "initial_h2d_bytes", "update_h2d_bytes")):
        raise ValueError("finite nonnegative host measurements required")
    if any(r.get("bootstrap_complete") is not True for r in rows):
        raise ValueError("complete physical bootstrap preparation required")
    if any(r.get("batch_preparation_complete") is not True for r in rows):
        raise ValueError("complete batch preparation required")
    for r in rows:
        if r.get("arm") == "spine" and (r.get("constructor_payload_calls", 0) <= 0 or
                r["initial_h2d_bytes"] != r["graph_bytes"] + r["directory_bytes"] + r["metadata_bytes"]):
            raise ValueError("Spine bootstrap payload capture did not conserve bytes")
    return dict(samples=rows, median_ns=median(r["nanoseconds"] for r in rows),
                initial_h2d_bytes=rows[0]["initial_h2d_bytes"], update_h2d_bytes=rows[0]["update_h2d_bytes"])


def energy(directory):
    files = sorted((directory / "dram").glob("channel*/dramsim3.json"))
    if len(files) != 32:
        raise ValueError("all 32 common-budget channel energy reports required")
    total = 0.0
    for path in files:
        contents = json.loads(path.read_text())
        rows = contents.values() if isinstance(contents, dict) else contents
        for row in rows:
            if not isinstance(row, dict) or "total_energy" not in row:
                raise ValueError("unexpected DRAMSim3 aggregate format")
            value = float(row["total_energy"])
            if not math.isfinite(value) or value < 0:
                raise ValueError("invalid DRAMSim3 energy")
            total += value
    if not total > 0:
        raise ValueError("empty DRAMSim3 energy")
    return total


def energy_details(directory):
    """Keep command/background components so time-dependent energy is visible."""
    total = energy(directory)
    fields = ("act_energy", "act_stb_energy", "pre_stb_energy", "read_energy",
              "write_energy", "ref_energy", "refb_energy", "sref_energy")
    components = dict.fromkeys(fields, 0.0)
    commands = dict(num_read_cmds=0, num_write_cmds=0)
    for path in sorted((directory / "dram").glob("channel*/dramsim3.json")):
        contents = json.loads(path.read_text())
        rows = contents.values() if isinstance(contents, dict) else contents
        for row in rows:
            for key in fields:
                value = row[key]
                value = sum(value.values()) if isinstance(value, dict) else value
                if not math.isfinite(value) or value < 0:
                    raise ValueError("invalid energy component")
                components[key] += value
            for key in commands:
                commands[key] += row[key]
    if not math.isclose(sum(components.values()), total, rel_tol=1e-9, abs_tol=1e-3):
        raise ValueError("energy components do not conserve total")
    return dict(total_energy_pj=total, **{k + "_pj": v for k, v in components.items()}, **commands)


def comparison(case, arms):
    result = {key: case[key] for key in ("figure", "dataset", "algorithm", "updates")}
    result.update(status="PREDICTION_ONLY", baseline_admitted=False)
    for arm in ("spine", "gr"):
        result[arm] = arms[arm]
    if case["figure"] == 8:
        for arm in ("spine", "gr"):
            row = arms[arm]
            h = row["host"]
            # Historical Fig. 8 convention: setup layout, logical initial upload,
            # batch upload, one launch/sync, then update-only device work.
            row["setup_seconds"] = h["median_ns"] / 1e9 + (h["initial_h2d_bytes"] + h["update_h2d_bytes"]) / 12e9 + 10e-6
            row["setup_inclusive_seconds"] = row["setup_seconds"] + row["cycles"] / 150e6
            row["updates_per_second"] = case["updates"] / row["setup_inclusive_seconds"]
        result["speedup"] = arms["gr"]["setup_inclusive_seconds"] / arms["spine"]["setup_inclusive_seconds"]
    else:
        result["accepted_bytes_ratio"] = (arms["gr"]["read_bytes"] + arms["gr"]["write_bytes"]) / (arms["spine"]["read_bytes"] + arms["spine"]["write_bytes"])
        result["hbm_energy_ratio"] = arms["gr"]["energy_pj"] / arms["spine"]["energy_pj"]
    return result
