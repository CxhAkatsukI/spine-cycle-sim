"""Predeclared paired timing diagnostics with finite parallelism and retained failures."""

from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import multiprocessing
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from .execution import identity
from .sst_timing import run_sst_case


def _execute(arguments: dict) -> dict:
    label = arguments.pop("label")
    try:
        result = run_sst_case(**arguments)
        return {"id": label, "status": result["status"], "summary": str(arguments["output"] / "summary.json")}
    except Exception as error:
        return {"id": label, "status": "FAIL", "error": str(error), "output": str(arguments["output"])}


def run_timing_matrix(*, root: Path, integration: Path, plugin_dir: Path, exporter: Path,
                      contract: Path, output: Path, jobs: int) -> dict:
    if jobs not in (1, 2):
        raise ValueError("the bounded timing matrix permits one or two workers")
    matrix = json.loads(contract.read_text())
    if (matrix["schema_version"] != 1 or matrix["arms"] != ["candidate", "original"]
            or matrix["memory_limit_gib"] != 8 or matrix["reserve_gib"] != 16):
        raise ValueError("unexpected paired timing contract")
    if available_memory_bytes() < (jobs * 8 + 16) * 1024**3:
        raise RuntimeError("insufficient memory for aggregate worker limits plus reserve")
    tasks = []
    for arm in matrix["arms"]:
        for case in matrix["cases"]:
            graph = Path(case["graph"])
            if sha256_file(graph) != case["graph_sha256"]:
                raise ValueError(f"frozen graph changed: {case['id']}")
            tasks.append({"label": f"{case['id']}_{arm}", "root": root, "integration": integration,
                          "plugin_dir": plugin_dir, "exporter": exporter,
                          "profile_path": root / matrix["profile"], "graph": graph, "source": case["source"],
                          "board_run": Path(case["board_pair"]) / f"r0_{arm}",
                          "output": output / f"{case['id']}_{arm}", "arm": arm,
                          "timeout": matrix["timeout_seconds"], "max_cycles": matrix["max_cycles"]})
    output.mkdir(parents=True, exist_ok=False)
    contract_pin = identity(contract)
    atomic_write_json(output / "matrix.json", {"contract": contract_pin, "jobs": jobs,
                                               "matrix": matrix, "expected": [task["label"] for task in tasks]})
    rows = []
    with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context("spawn")) as executor:
        futures = [executor.submit(_execute, task) for task in tasks]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            atomic_write_json(output / "progress.json", {"completed": rows, "expected_count": len(tasks)})
            print(row["id"], row["status"], flush=True)
    unchanged = identity(contract) == contract_pin
    summary = {"schema_version": 1, "status": "FUNCTIONAL_MATRIX_PASS_TIMING_UNADMITTED"
               if unchanged and all(row["status"] == "FUNCTIONAL_PASS_TIMING_DIAGNOSTIC" for row in rows)
               else "MATRIX_HAS_FAILURES", "rows": sorted(rows, key=lambda row: row["id"]),
               "hardware_timing_admitted": False, "contract_unchanged": unchanged}
    atomic_write_json(output / "summary.json", summary)
    return summary
