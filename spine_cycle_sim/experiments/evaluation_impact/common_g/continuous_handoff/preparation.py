"""Freeze the resident G host and the single-partition SSSP handoff contract."""

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..continuous_board.preparation import command as g_command, prepare as prepare_g
from ..study import ROOT


def policies(path):
    """Independent net-edge policy check; never supplies hardware result state."""
    records = [tuple(map(int, line.split())) for line in path.read_text().splitlines()]
    vertices, initial, updates, partition = records[0]
    if partition != 65536 or not 0 < vertices <= partition or len(records) != initial + updates + 1:
        raise ValueError("handoff requires a complete single native partition input")
    state = {}
    for src, dst, weight, diff in records[1:initial + 1]:
        if not 0 <= src < vertices or not 0 <= dst < vertices or not 0 < weight < 4096 or \
                diff != 1 or (src, dst) in state:
            raise ValueError("invalid initial weighted graph")
        state[src, dst] = weight
    changes = records[initial + 1:]
    ends = (0, 0, updates // 2, updates)
    result = []
    for start, end in zip(ends, ends[1:]):
        before = state.copy()
        for src, dst, weight, diff in changes[start:end]:
            key = (src, dst)
            if not 0 <= src < vertices or not 0 <= dst < vertices or not 0 < weight < 4096:
                raise ValueError("update outside weighted ABI")
            if diff == -1 and state.get(key) == weight:
                del state[key]
            elif diff == 1 and key not in state:
                state[key] = weight
            else:
                raise ValueError("update is not an exact physical mutation")
        fallback = any(key not in state or state[key] > weight for key, weight in before.items())
        seeds = {0} if fallback else {src for (src, dst), weight in state.items()
                                     if (src, dst) not in before or weight < before[src, dst]}
        result.append({"fallback": fallback, "seed_sources": len(seeds)})
    return result


def warm_control(source, target):
    records = [tuple(map(int, line.split())) for line in source.read_text().splitlines()]
    vertices, initial, updates, partition = records[0]
    if updates % 2:
        raise ValueError("weight changes must be paired physical records")
    old = {(src, dst): weight for src, dst, weight, _ in records[1:initial + 1]}
    chosen, seen = [], set()
    changes = records[initial + 1:]
    for deletion, insertion in zip(changes[::2], changes[1::2], strict=True):
        src, dst, weight, diff = deletion
        key = (src, dst)
        if diff != -1 or insertion[:2] != key or insertion[3] != 1:
            raise ValueError("non-paired weight-change source")
        if insertion[2] < weight and old.get(key) == weight and key not in seen:
            chosen.extend((deletion, insertion))
            seen.add(key)
            if len(seen) == 64:
                break
    if len(seen) != 64:
        raise ValueError("insufficient distinct trace-derived decreases for declared warm control")
    target.write_text(f"{vertices} {initial} {len(chosen)} {partition}\n" +
                      "".join(" ".join(map(str, row)) + "\n" for row in [*records[1:initial + 1], *chosen]),
                      encoding="ascii")
    return vertices, initial


def prepare(output, upstream, integration):
    pins, original = prepare_g(output, upstream, integration)
    source = output / "source"
    groups = {
        "continuous_handoff": sorted((ROOT / "cpp/tests/evaluation_impact/common_g/continuous_handoff").glob("*.?pp")),
        "runner/continuous_handoff": sorted(Path(__file__).parent.glob("*.py")),
        "handoff_abi": [integration / "tools/sharded_k4_native_host.cpp",
                        integration / "kernels/regraph_stream_little_gs/little_gs_stream.cpp",
                        integration / "kernels/regraph_frontend_mux/regraph_frontend_mux.cpp"],
    }
    for group, paths in groups.items():
        (source / group).mkdir(parents=True, exist_ok=True)
        for path in paths:
            frozen = source / group / path.name
            shutil.copy2(path, frozen)
            digest = sha256_file(frozen)
            if sha256_file(path) != digest:
                raise ValueError("handoff source changed during freeze")
            pins.append({"original": str(path), "path": str(frozen), "sha256": digest})
    cases = []
    for case in original["cases"]:
        if case["shards"] != 1:
            raise ValueError("multishard convergence must have a separate implementation and gate")
        expected = policies(Path(case["input"]))
        cases.append({**case, "batches": [{**row, **policy} for row, policy in
                                         zip(case["batches"], expected, strict=True)]})
    for dataset in ("AU", "SU", "WK"):
        source_case = next(case for case in original["cases"] if case["case"] == dataset + "-weight_change-4096")
        name = dataset + "-warm-decrease-64"
        path = source / "inputs" / (name + ".txt")
        vertices, edges = warm_control(Path(source_case["input"]), path)
        if vertices != source_case["vertices"]:
            raise ValueError("warm derivation changed vertices")
        pins.append({"path": str(path), "sha256": sha256_file(path)})
        cases.append({**source_case, "case": name, "input": str(path), "positive_updates": 64,
                      "derived_from": source_case["case"],
                      "derivation": "first 64 distinct initial-weight-matching decreases in original pair order",
                      "batches": [{"batch": batch, "updates": 0 if batch == 0 else 64, "edges": edges, **policy}
                                  for batch, policy in enumerate(policies(path))]})
    contract = {**original, "cases": cases, "algorithm": "weighted SSSP", "source_vertex": 0,
                "round_limit": 2048, "initial_state": "old_graph_converged",
                "scope": "three resident G batches followed by adapter/R to convergence; no PMA restoration",
                "timing_boundary": "batch net-policy/lowering/packing, G update DMA and publication, seed/fallback DMA, all R rounds and result readback",
                "diagnostic_costs_separate": ["one-time parsing/builder/reservation/program/old-state upload",
                                              "independent Dijkstra and trajectory oracle", "full PMA/metadata/replica verification"],
                "fallback": "net removal or weight increase resets distance state and recomputes on the updated resident PMA",
                "warm_seed": "host net-edge detection and per-source active-bit writes, included in E2E",
                "warm_controls": "AU/SU/WK first 64 distinct decreases from frozen weight-change inputs; functional controls, not new original traces",
                "excludes": ["native multi-partition convergence", "CC/ResPR/FullPR",
                             "cold G updates", "new capacity growth", "original-publication performance match"]}
    atomic_write_json(output / "handoff_contract.json", contract)
    pins.append({"path": str(output / "handoff_contract.json"),
                 "sha256": sha256_file(output / "handoff_contract.json")})
    return pins, contract


def command(source, xrt, compiler, binary):
    argv = g_command(source, xrt, compiler, binary)
    argv[argv.index(str(source / "continuous_board/control.cpp"))] = str(source / "continuous_handoff/control.cpp")
    return argv
