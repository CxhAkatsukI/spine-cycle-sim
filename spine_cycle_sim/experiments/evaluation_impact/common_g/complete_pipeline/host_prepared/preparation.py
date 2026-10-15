"""Freeze unchanged production host headers and real-topology source inputs."""

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.shared_workloads import load_slice
from ...sharded.real_inputs import contract as real_contract
from ..preparation import command as composition_command, prepare as composition_prepare
from ...study import ROOT


def batch_facts(graph, updates):
    state = {(r.src, r.dst): r.weight for r in graph.records}
    if len(state) != len(graph.records) or any(r.diff != 1 for r in graph.records):
        raise ValueError("initial graph must have unique positive pairs")
    ends = (0, 0, len(updates.records) // 2, len(updates.records))
    rows = []
    for batch in range(3):
        for r in updates.records[ends[batch]:ends[batch + 1]]:
            key = (r.src, r.dst)
            if r.diff == -1 and state.get(key) == r.weight:
                del state[key]
            elif r.diff == 1 and key not in state:
                state[key] = r.weight
            else:
                raise ValueError("physical update is not a successful exact mutation")
        rows.append({"batch": batch, "updates": ends[batch + 1] - ends[batch], "edges": len(state)})
    return rows


def prepare(output, upstream, integration):
    real = real_contract()
    pins = composition_prepare(output, upstream, integration)
    source = output / "source"
    groups = {
        "host": [integration / "include" / name for name in
                 ("weighted_pma_graph.hpp", "weighted_pma_runtime_plan.hpp")],
        "host_prepared": sorted((ROOT / "cpp/tests/evaluation_impact/common_g/complete_pipeline/host_prepared").glob("*.*")),
        "runner/host_prepared": sorted(Path(__file__).parent.glob("*.py")),
        "runner/real_inputs": [ROOT / "spine_cycle_sim/experiments/evaluation_impact/common_g/sharded/real_inputs.py",
                               ROOT / "spine_cycle_sim/experiments/shared_workloads.py"],
    }
    for group, paths in groups.items():
        (source / group).mkdir(parents=True)
        for path in paths:
            frozen = source / group / path.name
            shutil.copy2(path, frozen)
            if sha256_file(path) != sha256_file(frozen):
                raise ValueError("source changed during freeze")
            pins.append({"original": str(path), "path": str(frozen), "sha256": sha256_file(frozen)})
    for pin in real["input_pins"]:
        original = Path(pin["path"])
        frozen = source / pin["member"]
        frozen.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, frozen)
        if sha256_file(frozen) != pin["sha256"]:
            raise ValueError("frozen real input changed")
        pins.append({"original": str(original), "path": str(frozen), "sha256": pin["sha256"]})
    cases = []
    for name, case in real["cases"].items():
        graph, updates = (load_slice(Path(case[key])) for key in ("graph", "updates"))
        for partition in ((65536, 1024) if name == "AU-mixed-512" else (65536,)):
            case_id = name + ("-partition-smoke" if partition == 1024 else "")
            path = source / "inputs" / (case_id + ".txt")
            records = (*graph.records, *updates.records)
            path.write_text(f"{graph.vertices} {len(graph.records)} {len(updates.records)} {partition}\n" +
                            "".join(f"{r.src} {r.dst} {r.weight} {r.diff}\n" for r in records), encoding="ascii")
            pins.append({"path": str(path), "sha256": sha256_file(path)})
            cases.append({"case": case_id, "input": str(path), "vertices": graph.vertices,
                          "shards": (graph.vertices + partition - 1) // partition,
                          "partition_vertices": partition,
                          "partition_scope": "native_65536" if partition == 65536 else "1024_functional_smoke_only",
                          "positive_updates": sum(r.diff == 1 for r in updates.records),
                          "batches": batch_facts(graph, updates)})
    contract = {"cases": cases, "input_kind": real["graph_kind"], "limitations": real["limitations"],
                "host_headers": "unchanged weighted partition builder, lane-aware 23-channel plan and packing",
                "reservation": "trace-aware future positive variants; fixed mapping/layout across three batches",
                "cache_capacity_per_half": 131072, "batch_scope": "empty, first half, remaining half; resident PMA",
                "cold_updates_expected": 0, "metadata_buffers": "all search arguments alias per-shard row/binary storage"}
    atomic_write_json(output / "contract.json", contract)
    pins.append({"path": str(output / "contract.json"), "sha256": sha256_file(output / "contract.json")})
    return pins, contract


def command(source: Path, include: Path, compiler: str, binary: Path):
    argv = composition_command(source, include, compiler, binary)
    argv[argv.index(str(source / "control.cpp"))] = str(source / "host_prepared/control.cpp")
    argv[argv.index("-MMD")] = "-MD"
    for vendor in (include, include / "etc"):
        index = argv.index(f"-I{vendor}")
        argv[index:index + 1] = ["-isystem", str(vendor)]
    return argv
