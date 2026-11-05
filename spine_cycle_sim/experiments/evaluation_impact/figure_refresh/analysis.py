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


def persistent_device(step, *, arm, updates, batch_count):
    """Check a rolling update-only device ledger, not setup-inclusive timing."""
    if not 1 < batch_count <= updates:
        raise ValueError("persistent update requires multiple nonempty batches")
    total = device(step)
    if arm not in {"spine", "gr"} or total.get("arm") != arm or total.get("physical_image_checked") is not True:
        raise ValueError("persistent result must match the arm and pass the final physical-image check")
    rows = records(step, "WARM_BATCH ")
    if len(rows) != batch_count:
        raise ValueError("missing or extra persistent batch records")
    work = ("cycles", "read_bytes", "write_bytes")
    for index, row in enumerate(rows):
        expected = (index + 1) * updates // batch_count - index * updates // batch_count
        if row.get("batch") != index or row.get("updates") != expected:
            raise ValueError("persistent batch order or mutation count mismatch")
        if any(type(row.get(key)) is not int or row[key] < 0 for key in work) or row["cycles"] == 0:
            raise ValueError("invalid persistent batch counters")
    if any(sum(row[key] for row in rows) != total[key] for key in work):
        raise ValueError("persistent batch counters do not conserve device totals")
    return {"device": total, "batches": rows}


def persistent_spine_device(step, *, updates, batch_count):
    return persistent_device(step, arm="spine", updates=updates, batch_count=batch_count)


def persistent_host(step, *, arm, updates, batch_count):
    rows = records(step, "HOST_RESULT ")
    if arm not in {"spine", "gr"} or len(rows) != 1:
        raise ValueError("one explicit-arm persistent host sample required")
    row = rows[0]
    if (row.get("arm"), row.get("repeat"), row.get("updates"), row.get("batches")) != (
            arm, 0, updates, batch_count):
        raise ValueError("persistent host identity or batch scope mismatch")
    values = ("nanoseconds", "initial_nanoseconds", "batch_nanoseconds", "initial_h2d_bytes", "update_h2d_bytes")
    if any(type(row.get(k)) is not int or row[k] < 0 for k in values):
        raise ValueError("finite nonnegative integer host counters required")
    if row["nanoseconds"] != row["initial_nanoseconds"] + row["batch_nanoseconds"]:
        raise ValueError("persistent host time ledger does not conserve totals")
    width = 16 if arm == "spine" else 8
    expected = [((i + 1) * updates // batch_count - i * updates // batch_count) * width
                for i in range(batch_count)]
    if (row.get("batch_h2d_bytes") != expected or row["update_h2d_bytes"] != updates * width
            or row["initial_h2d_bytes"] <= 0):
        raise ValueError("persistent host transfer ledger does not match actual batch ABI")
    if any(row.get(key) is not True for key in ("bootstrap_complete", "batch_preparation_complete")):
        raise ValueError("persistent host preparation is incomplete")
    return row


def persistent_comparison(arms, *, updates, batch_count):
    result = dict(status="PERSISTENT_PAIRED_SETUP_PREDICTION", baseline_admitted=False,
        updates=updates, batches=batch_count, host_samples_per_arm=1,
        assumptions=dict(clock_hz=150e6, transfer_bytes_per_second=12e9,
                         launch_sync_seconds_per_batch=10e-6))
    for arm in ("spine", "gr"):
        row = arms[arm]
        h = row["host"]
        transfer = (h["initial_h2d_bytes"] + h["update_h2d_bytes"]) / 12e9
        device_seconds = row["device"]["cycles"] / 150e6
        seconds = h["nanoseconds"] / 1e9 + transfer + batch_count * 10e-6 + device_seconds
        result[arm] = dict(host_seconds=h["nanoseconds"] / 1e9, transfer_seconds=transfer,
            device_seconds=device_seconds, setup_inclusive_seconds=seconds,
            updates_per_second=updates / seconds)
    result["speedup_gr_over_spine"] = result["gr"]["setup_inclusive_seconds"] / result["spine"]["setup_inclusive_seconds"]
    return result


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
