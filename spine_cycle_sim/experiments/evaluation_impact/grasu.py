"""Replay original G against independent source state and frozen finite observations."""

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..grasu_finite.analysis import analyze, equivalent
from ..grasu_finite.preparation import prepare
from ..upstream_controls.grasu.analysis import analyze as analyze_source


def replay(root, old, binary, output, execute):
    contract = old["contract"]
    source = root / contract["source_probe"]
    if sha256_file(source) != contract["source_probe_sha256"]:
        raise ValueError("original source probe changed")
    for item in old["source_binaries"]:
        for pin in [item, *item["dependencies"]]:
            if sha256_file(Path(pin["path"])) != pin["sha256"]:
                raise ValueError("original source dependency changed")
    inputs, source_rows, rows = {}, [], []
    for case in sorted({row["case"] for row in contract["matrix"]}):
        inputs[str(case)] = prepare(output / "inputs" / str(case), case)
        capture = output / "source" / str(case)
        capture.mkdir(parents=True)
        record = execute([str(source), str(case), str(capture / "protocol.u32le"), str(capture / "state.u32le")],
                         "g_source_" + str(case))
        observed = analyze_source(capture, case, Path(record["stdout"]), Path(record["stderr"]))
        equivalent(old["source_rows"][case], observed)
        source_rows.append(observed)
    for row in contract["matrix"]:
        for repetition in range(contract["repetitions"]):
            capture = output / "finite" / row["id"] / str(repetition)
            capture.mkdir(parents=True)
            memory = contract["memory"] | row
            record = execute([str(binary), str(output / "inputs" / str(row["case"])), str(capture),
                str(memory["fifo_depth"]), str(memory["latency"]), str(memory["bank_credits"]),
                str(row.get("reverse", 0)), str(contract["limits"]["max_cycles_per_batch"]), "1"],
                f'g_{row["id"]}_{repetition}')
            observed = analyze(capture, row["case"], Path(record["stdout"]), Path(record["stderr"]))
            previous = next(r["result"] for r in old["rows"] if r["id"] == row["id"] and r["repetition"] == repetition)
            equivalent(previous, observed)
            if observed["oracle_state_sha256"] != source_rows[row["case"]]["state_sha256"]:
                raise ValueError("finite G differs from original source state")
            rows.append({"id": row["id"], "repetition": repetition, "result": observed})
    return {"status": "ORIGINAL_G_SOURCE_AND_FINITE_REPLAY_PASS_NOT_CURRENT_G_SPEED_MATCH",
        "inputs": inputs, "source_rows": source_rows, "rows": rows,
        "publication_timing_match": None, "current_g_vs_original_g_timing_match": None,
        "note": "Fresh current-core build of independent original G; not production GraSU sharded update."}
