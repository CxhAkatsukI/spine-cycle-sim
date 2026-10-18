"""Replay the distinct remote-SSSP link contract before checkpoint diagnostics."""

import json
import socket
from pathlib import Path

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ..remote import capsule, delivery


def completed(route):
    execution, manifest, preflight = (json.loads((route / name).read_text()) for name in
                                    ("execution.json", "manifest.json", "preflight/results.json"))
    delivery.completed(execution, manifest, preflight)
    relocation = manifest["relocation"]
    root = Path(relocation["path"]).parent
    packet, parent = capsule.verify(root)
    contract = json.loads((route / "environment.json").read_text())
    expected = {"capsule": identity(root / "capsule.json"),
                "manifest": identity(route / "manifest.json"),
                "xclbin": identity(route / "candidate.hw.xclbin")}
    child = execution["route"]
    if any(execution.get(key) != value for key, value in expected.items()) or \
            relocation != expected["capsule"] or execution.get("host") != socket.gethostname() or \
            any(record.get("parent") != packet["parent"] for record in (execution, manifest)) or \
            manifest.get("clock_mhz") != 150 or manifest.get("policy") != capsule.POLICY or \
            manifest.get("command") != capsule.command(packet, parent, root, route,
                                                       contract["tools"]["v++"]["invocation"]):
        raise ValueError("remote SSSP link differs from its frozen production capsule")
    if json.loads((route / "route.resources.json").read_text()) != child or \
            child.get("command") != manifest["command"] or child.get("cwd") != str(route) or \
            child.get("tree_memory_gib") != 40 or child.get("reserve_gib") != 32 or \
            child.get("timeout_seconds") != packet["timeout_seconds"]:
        raise ValueError("remote SSSP raw link record or finite policy differs")
    for row in preflight["commands"]:
        raw = json.loads((route / f"preflight/{row['label']}.resources.json").read_text())
        if raw != {key: value for key, value in row.items() if key != "label"}:
            raise ValueError("remote SSSP raw environment record differs")
    indexed = {pin["path"]: pin["sha256"] for pin in manifest["pins"]}
    required = [root / "capsule.json", route / "environment.json", route / "link.cfg",
                *[root / row["member"] for row in packet["files"]]]
    if any(indexed.get(str(path)) != identity(path)["sha256"] for path in required):
        raise ValueError("remote SSSP source/configuration closure is incomplete")
    raw = [route / "preflight/results.json", route / "route.resources.json",
           *[route / f"preflight/{row['label']}.resources.json" for row in preflight["commands"]]]
    return execution, {**manifest, "algorithm": "weighted_sssp",
                       "pins": [*manifest["pins"], *map(identity, raw)]}
