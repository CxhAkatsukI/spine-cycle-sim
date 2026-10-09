"""Keep functional source acceptance separate from device timing evidence."""

from __future__ import annotations

import json
import re


SOURCE_KINDS = {
    "grasu_cache_probe.cpp": "grasu_cache",
    "regraph_little_probe.cpp": "regraph_little",
    "regraph_big_probe.cpp": "regraph_big",
}


def validate_contract(contract: dict) -> None:
    if contract.get("schema_version") != 1 or contract.get("evidence_class") != \
            "upstream_source_functional_only":
        raise ValueError("unsupported upstream control contract")
    for field in ("memory_limit_gib", "reserve_gib", "compile_timeout_seconds",
                  "run_timeout_seconds"):
        value = contract.get(field)
        if type(value) is not int or value <= 0:
            raise ValueError(f"{field} must be a positive integer")
    if contract["reserve_gib"] < 16:
        raise ValueError("this study requires at least 16 GiB memory reserve")
    if not isinstance(contract.get("generator_python"), str) or not contract["generator_python"]:
        raise ValueError("pin the upstream generator interpreter")
    topologies = contract.get("topologies")
    probes = contract.get("probes")
    for rows in (topologies, probes):
        if not isinstance(rows, list) or not rows:
            raise ValueError("predeclare a nonempty matrix")
        ids = [row.get("id") for row in rows]
        if any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name)
               for name in ids) or len(set(ids)) != len(ids):
            raise ValueError("matrix ids must be unique safe path components")
    topology_map = {row["id"]: row for row in topologies}
    for topology in topologies:
        little, big = topology.get("little"), topology.get("big")
        if (type(little) is not int or type(big) is not int or little < 1 or big < 0
                or little + big > 14):
            raise ValueError("invalid original U280 topology")
    for probe in probes:
        if probe.get("source") not in SOURCE_KINDS:
            raise ValueError("use a supported source-functional probe")
        if "capture_merged" in probe and (
                probe["capture_merged"] is not True or
                probe["source"] != "regraph_little_probe.cpp"):
            raise ValueError("merged capture requires an explicit Little source control")
        expected = probe.get("expected", {})
        if expected.get("kind") != SOURCE_KINDS[probe["source"]] or expected.get("passed") is not True:
            raise ValueError("probe/source kind or expected outcome mismatch")
        if expected["kind"].startswith("regraph"):
            topology = topology_map.get(probe.get("topology"))
            if topology is None or any(expected.get(field) != topology[field]
                                       for field in ("little", "big")):
                raise ValueError("probe topology must match its predeclared source generation")
            if expected["kind"] == "regraph_big" and topology["big"] == 0:
                raise ValueError("zero-Big topology cannot run a Big probe")
    if not isinstance(contract.get("not_claimed"), list) or not contract["not_claimed"]:
        raise ValueError("declare remaining evidence limitations")


def validate_probe(stdout: str, expected: dict) -> dict:
    records = [line.removeprefix("PUBLICATION_PROBE ") for line in stdout.splitlines()
               if line.startswith("PUBLICATION_PROBE ")]
    if len(records) != 1:
        raise ValueError("probe needs exactly one machine-readable result")
    result = json.loads(records[0])
    if (not isinstance(result, dict) or result != expected or result.get("passed") is not True
            or any(type(result[field]) is not type(value) for field, value in expected.items())):
        raise ValueError(f"probe result differs from predeclared functional contract: {result}")
    if "WARNING [HLS SIM]" in stdout or "ERROR [HLS SIM]" in stdout:
        raise ValueError("HLS stream warning/error prevents source-functional admission")
    return result
