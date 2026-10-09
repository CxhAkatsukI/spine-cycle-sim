"""Admit original request-dependent controls and finite Little input paths."""

from __future__ import annotations

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.validation import validate_probe
from .analysis import same_typed


def rows(stdout: str, prefix: str) -> list[dict]:
    result = [json.loads(line.removeprefix(prefix)) for line in stdout.splitlines()
              if line.startswith(prefix)]
    if not result or any(not isinstance(row, dict) for row in result):
        raise ValueError(f"missing structured records: {prefix}")
    return result


def protocol_rows(stdout: str, contract: dict) -> list[dict]:
    observed = rows(stdout, "ORIGINAL_SCATTER_CASE ")
    expected = []
    by_id = {row["id"]: row for row in contract["cases"]}
    for name in contract["source_protocol_cases"]:
        case = by_id[name]
        expected.append({"id": name, "checked_words": len(case["rounds"]) * 32,
                         "source_response_lines": len(case["requests"]) * 256,
                         "request_rounds": case["requests"]})
    if not same_typed(observed, expected):
        raise ValueError("original source request/response matrix differs from contract")
    return observed


def admit_protocol(directory: Path, root: Path, contract: dict) -> dict:
    report_path = directory / "report.json"
    report = json.loads(report_path.read_text())
    canonical = root / "configs/experiments/regraph_upstream_scatter_protocol_v2.json"
    source_contract = json.loads(canonical.read_text())
    if (report.get("evidence_class") != "upstream_source_functional_only" or
            report.get("all_functional_probes_passed") is not True or
            report.get("device_cycles") is not None or
            report.get("contract_sha256") != sha256_file(canonical) or
            not same_typed(json.loads((directory / "contract.json").read_text()), source_contract) or
            len(report.get("probes", [])) != 1):
        raise ValueError("protocol requires the fixed passing source-functional control")
    row, expected = report["probes"][0], source_contract["probes"][0]
    if (row.get("id") != expected["id"] or row.get("status") != "FUNCTIONAL_PASS_NOT_TIMING" or
            not same_typed(row.get("observed"), expected["expected"]) or
            not same_typed(row.get("expected"), expected["expected"]) or
            not report.get("analysis_code") or not row.get("dependencies")):
        raise ValueError("protocol source or functional result mismatch")
    for phase in ("compile", "run"):
        if row[phase]["exit_code"] != 0 or row[phase]["timed_out"]:
            raise ValueError("protocol execution was incomplete")
    for identity in report["analysis_code"]:
        if sha256_file(root / identity["path"]) != identity["sha256"]:
            raise ValueError("protocol control code changed")
    for identity in row["dependencies"]:
        if sha256_file(Path(identity["path"])) != identity["sha256"]:
            raise ValueError("original protocol dependency changed")
    stdout = Path(row["run"]["stdout"]).read_text()
    validate_probe(stdout, expected["expected"])
    return {"source_report_sha256": sha256_file(report_path),
            "cases": protocol_rows(stdout, contract),
            "summary": row["observed"], "evidence_class": report["evidence_class"]}


def analyze_frontend(stdout: str, repeated: str, protocol: dict, contract: dict) -> dict:
    if stdout != repeated:
        raise ValueError("frontend repetition changed state, timing or counters")
    if not same_typed(rows(stdout, "FRONTEND_CONFIG "), [contract["configuration"]]):
        raise ValueError("frontend binary configuration differs from fixed contract")
    cases = rows(stdout, "FRONTEND_CASE ")
    if [row.get("id") for row in cases] != [row["id"] for row in contract["cases"]]:
        raise ValueError("frontend matrix missing, duplicated or reordered")
    counter_fields = (
        "cycles", "edge_bytes", "source_bytes", "normal_requests", "source_loaded",
        "source_discarded", "scatter_stalls", "edge_stalls", "source_response_stalls",
        "axi_stalls", "axi_beats", "checked_words", "first_merged", "last_scatter_done",
        "little", "fifo_depth", "memory_latency", "outstanding")
    for row, expected in zip(cases, contract["cases"], strict=True):
        if (row.get("completed") is not True or not row.get("cycles") or
                any(type(row.get(key)) is not int or row[key] < 0 for key in counter_fields)):
            raise ValueError("incomplete frontend or invalid counter types")
        little = expected["little"]
        gather = row["id"] == "a4_memory_to_merged"
        exact = {
            "little": little, "gather": gather,
            "edge_bytes": len(expected["rounds"]) * 4 * 64 * little,
            "source_bytes": len(expected["requests"]) * 16384 * little,
            "normal_requests": len(expected["requests"]) * little,
            "checked_words": 65536 if gather else len(expected["rounds"]) * 32,
            "request_rounds": [expected["requests"]] * little,
            "fifo_depth": 1 if row["id"] == "depth1_slow_sink" else 8,
            "memory_latency": 128 if row["id"] == "memory_latency128" else 64,
            "outstanding": 1 if row["id"] == "one_outstanding" else 16,
        }
        if not same_typed({key: row.get(key) for key in exact}, exact):
            raise ValueError("frontend work, topology, request trace or resources mismatch")
        lines = row["normal_requests"] * 256
        if (row["source_loaded"] + row["source_discarded"] != lines or
                row["axi_beats"] * 64 != row["edge_bytes"] + row["source_bytes"] or
                row["last_scatter_done"] > row["cycles"]):
            raise ValueError("frontend source-line or memory-beat conservation failed")
    indexed = {row["id"]: row for row in cases}
    baseline = indexed["source_windows012"]
    reverse = {**indexed["reverse_registration"], "id": baseline["id"]}
    if not same_typed(reverse, baseline):
        raise ValueError("registration order changed frontend timing or counters")
    for name in ("depth1_slow_sink", "one_outstanding", "memory_latency128"):
        if indexed[name]["cycles"] <= baseline["cycles"]:
            raise ValueError("finite-resource sensitivity did not change timing")
    pressure = indexed["depth1_slow_sink"]
    if not pressure["scatter_stalls"] or not pressure["source_response_stalls"]:
        raise ValueError("downstream backpressure did not reach the source memory service")
    if not same_typed(rows(stdout, "FRONTEND_REJECTION "), contract["expected_rejections"]):
        raise ValueError("allocation boundary was silently bypassed")
    for source in protocol["cases"]:
        model = indexed[source["id"]]
        if (not same_typed(model["request_rounds"], [source["request_rounds"]]) or
                model["checked_words"] != source["checked_words"] or
                model["source_loaded"] + model["source_discarded"] != source["source_response_lines"]):
            raise ValueError("model does not match admitted original source protocol")
    return {
        "status": "FINITE_MEMORY_FRONTEND_FUNCTIONAL_PASS_TIMING_PREDICTED",
        "cases": cases, "expected_rejections": contract["expected_rejections"],
        "original_protocol_checked_words": sum(row["checked_words"] for row in protocol["cases"]),
        "repeat_stdout_and_all_counters_identical": True,
        "publication_rate_error_pct": None, "FPGA_cycle_error_pct": None,
    }
