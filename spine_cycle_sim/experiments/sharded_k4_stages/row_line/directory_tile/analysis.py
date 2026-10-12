"""Admit unchanged physical work plus independently counted directory prefetch."""

from array import array
from pathlib import Path
import sys

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ..cross_row.a4_control.analysis import basis_case
from ..continuous_directory.analysis import records
from .contract import MAX_OVER_A4

ARMS = ("original", "cross_row", "tile")
SCENARIOS = (("cold", 64), ("warm_update", 64), ("warm_update", 128))


def metadata(arm, tile_rows=128, packet_pipeline=False, bank_stream=False, bank_read_beats=False,
             bank_fifo_lines=128):
    result = {"version": "directory_tile_v1", "directory_cache_rows": tile_rows if arm == "tile" else 8,
            "cross_row_pipeline": 1, "row_line_reads": 1, "fixed_rounds": 1,
            "hardware_timing_admitted": False, "strict_resource_match_admitted": False}
    if arm == "tile" and packet_pipeline:
        result["packet_pipeline"] = True
    if arm == "tile" and bank_stream:
        result["bank_stream"] = True
    if arm == "tile" and bank_read_beats:
        result["bank_read_beats"] = True
    if arm == "tile" and bank_fifo_lines != 128:
        result["bank_fifo_lines"] = bank_fifo_lines
    return result


def directory_lines(input_dir):
    def words(name):
        result = array("I")
        with (input_dir / name).open("rb") as stream:
            result.frombytes(stream.read())
        if sys.byteorder != "little":
            result.byteswap()
        return result
    offsets, destinations = words("csr_offsets.u32le"), words("csr_destinations.u32le")
    vertices = len(offsets) - 1
    last = [-1] * ((vertices + 65535) // 65536)
    if offsets[0] or offsets[-1] != len(destinations):
        raise ValueError("CSR extent differs")
    for source in range(vertices):
        if offsets[source] > offsets[source + 1]:
            raise ValueError("nonmonotonic CSR offsets")
        for edge in range(offsets[source], offsets[source + 1]):
            destination = destinations[edge]
            if destination >= vertices:
                raise ValueError("destination outside physical-ID graph")
            last[destination // 65536] = source
    return {rows: sum((min(vertices, (source // rows + 1) * rows) + 7) // 8
                       for source in last if source >= 0) for rows in (8, 128, 1024)}


def admit(text, state, basis, spec, historical, lines, tile_rows=128, packet_pipeline=False, bank_stream=False,
          bank_read_beats=False, bank_fifo_lines=128):
    mode, latency, reverse, arm = spec
    old = basis_case(basis, mode, latency, reverse, "original" if arm == "original" else "cross_row")
    groups = records(text)
    if arm == "original":
        if not same_typed(groups, records(historical)):
            raise ValueError("original A4 exact numerical replay changed")
    else:
        if (set(groups) != {"MODEL_CONTROL", "REAL_ROUND", "INVOCATION"}
                or not same_typed(groups["MODEL_CONTROL"], [metadata(arm, tile_rows, packet_pipeline, bank_stream,
                                                                 bank_read_beats, bank_fifo_lines)])
                or len(groups["REAL_ROUND"]) != 1):
            raise ValueError("candidate declaration or record cardinality differs")
        counters = groups["REAL_ROUND"][0]
        expected = dict(old["counters"])
        if expected["row_reads"] != lines[8]:
            raise ValueError("independent legacy directory count differs")
        if arm == "tile":
            expected["row_reads"] = lines[tile_rows]
            expected["read_bytes"] += (lines[tile_rows] - lines[8]) * 64
            expected["cycles"] = counters.get("cycles")
        if (type(counters.get("cycles")) is not int or not 0 < counters["cycles"] <= 100000000
                or not same_typed(counters, expected)):
            raise ValueError("reference replay or conserved physical work differs")
        invocations = groups["INVOCATION"]
        fields = {"round", "partition", "worker", "adapter", "start", "end"}
        if (len(invocations) != 8 or any(set(row) != fields or type(row["adapter"]) is not bool
                or any(type(row[k]) is not int for k in fields - {"adapter"})
                or row["round"] != 1 or row["worker"] != row["partition"] % 4
                or not 0 <= row["start"] < row["end"] <= counters["cycles"] for row in invocations)
                or sorted((row["partition"], row["adapter"]) for row in invocations)
                != sorted((p, a) for p in range(4) for a in (False, True))):
            raise ValueError("complete bounded worker invocations required")
        if arm == "cross_row" and not same_typed(invocations, old["invocations"]):
            raise ValueError("V3 invocation schedule changed")
    outputs = []
    for pin in old["outputs"]:
        path = state / Path(pin["path"]).name
        if path.is_symlink() or path.stat().st_size != pin["bytes"] or sha256_file(path) != pin["sha256"]:
            raise ValueError("full state or source replica differs")
        outputs.append({"path": path.name, "bytes": pin["bytes"], "sha256": pin["sha256"]})
    if {p.name for p in state.iterdir()} != {p["path"] for p in outputs}:
        raise ValueError("unexpected state output")
    cycles = groups["REAL_ROUND"][0]["cycles"]
    a4 = basis_case(basis, mode, latency, reverse, "original")["paths"][0]["cycles"]
    v3 = basis_case(basis, mode, latency, reverse, "cross_row")["counters"]["cycles"]
    return {"mode": mode, "latency": latency, "reverse": reverse, "arm": arm,
            "cycles": cycles, "candidate_over_A4": cycles / a4, "v3_over_candidate": v3 / cycles,
            "records": groups, "outputs": outputs}


def matrix(cases):
    keys = [(row["mode"], row["latency"], row["reverse"], row["arm"]) for row in cases]
    expected = [(mode, latency, reverse, arm) for mode, latency in SCENARIOS
                for reverse in (0, 1) for arm in ARMS]
    if keys != expected:
        raise ValueError("complete predeclared matrix required")
    for mode, latency in SCENARIOS:
        for arm in ARMS:
            pair = [row for row in cases if (row["mode"], row["latency"], row["arm"]) == (mode, latency, arm)]
            if not same_typed(*[{k: v for k, v in row.items() if k != "reverse"} for row in pair]):
                raise ValueError("registration order changed complete result")
    warm = [row for row in cases if row["mode"] == "warm_update" and row["arm"] == "tile" and not row["reverse"]]
    if warm[1]["cycles"] <= warm[0]["cycles"]:
        raise ValueError("memory latency sensitivity was bypassed")
    passed = all(row["candidate_over_A4"] <= MAX_OVER_A4 for row in warm)
    return {"status": "PREDICTION_TARGET_MET_NOT_FPGA" if passed else "PREDICTION_TARGET_NOT_MET",
            "target_met": passed, "maximum_over_A4": MAX_OVER_A4,
            "hardware_timing_admitted": False, "publication_match_admitted": False}
