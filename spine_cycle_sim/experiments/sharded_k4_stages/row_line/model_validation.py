"""Independent bounded fixture inventory and whole-system traffic admission."""

from pathlib import Path
import struct

from ..sst_input_audit import _words
from .model_contract import PROFILE_ID


def inventory(path: Path) -> dict:
    if not 28 <= path.stat().st_size <= 64 * 1024**2:
        raise ValueError("resident smoke fixture exceeds the declared 64-MiB bound")
    with path.open("rb") as stream:
        magic, version, vertices, partitions, cache, rounds, active = struct.unpack("<7I", stream.read(28))
        if (magic != 0x4b345331 or version != 1 or not 0 < vertices <= 300000
                or partitions != (vertices + 65535) // 65536 or not 1 <= rounds <= 256
                or active > vertices or not cache):
            raise ValueError("unsupported bounded resident fixture geometry")
        stream.seek((vertices * 3 + active) * 4, 1)
        tails = []
        edges = 0
        for partition in range(partitions):
            updates, slots = struct.unpack("<2I", stream.read(8))
            bounds = _words(stream, vertices * 2)
            end, last = 0, -1
            for vertex in range(vertices):
                begin, following = bounds[vertex * 2:vertex * 2 + 2]
                if begin != end or following < begin or following > slots or following % 16:
                    raise ValueError("fixture rows are not contiguous aligned PMA extents")
                if following > begin:
                    last = vertex
                end = following
            if end != slots:
                raise ValueError("fixture row extent differs from PMA slots")
            words = _words(stream, slots)
            edges += sum(not (word & 0x80000000) for word in words)
            visited = last + 1
            tails.append({"partition": partition, "physical_updates": updates, "slots": slots,
                          "visited_rows": visited, "last_occupied_source": last,
                          "reference_reads_per_round": min(vertices, ((visited + 7) // 8) * 8),
                          "candidate_reads_per_round": (visited + 7) // 8})
        if stream.tell() != path.stat().st_size:
            raise ValueError("resident fixture has trailing or truncated data")
    return {"vertices": vertices, "partitions": partitions, "rounds": rounds,
            "pma_slots": sum(row["slots"] for row in tails), "live_edges_per_round": edges, "tails": tails}


def require_result(result: dict, geometry: dict, arm: str) -> dict:
    if arm not in ("original", "candidate"):
        raise ValueError("unknown whole-line arm")
    if (result.get("profile_id") != PROFILE_ID
            or result.get("boundary") != "resident_compute_no_host_launch_gaps"
            or result.get("evidence") != "simulator_prediction_not_hardware_timing_admission"
            or any(result.get(key) is not True for key in ("success", "done", "replicas_equal", "ledger_closed"))
            or result.get("failed") is not False or result.get("mismatches") != 0):
        raise ValueError("complete candidate correctness and ledger gate failed")
    if any(result.get(key) != geometry[key] for key in ("vertices", "partitions", "pma_slots", "live_edges_per_round")):
        raise ValueError("model and independently inventoried fixture differ")
    rounds = geometry["rounds"]
    if len(result["rounds"]) != rounds or result["expected_rounds"] != rounds:
        raise ValueError("convergence rounds differ")
    c = result["counters"]
    padded = geometry["partitions"] * 65536
    expected = {"extent_reads": geometry["partitions"] * rounds,
                "row_reads": sum(row[f"{('reference' if arm == 'original' else 'candidate')}_reads_per_round"]
                                 for row in geometry["tails"]) * rounds,
                "segment_reads": geometry["pma_slots"] // 16 * rounds,
                "packets": geometry["pma_slots"] // 8 * rounds,
                "live_edges": geometry["live_edges_per_round"] * rounds,
                "dummy_edges": (geometry["pma_slots"] - geometry["live_edges_per_round"]) * rounds,
                "source_lines": c["source_blocks"] * 256,
                "source_terminators": geometry["partitions"] * rounds,
                "gather_rows": padded // 2 * rounds, "mux_rows": padded // 2 * rounds,
                "apply_reads": padded // 16 * rounds, "apply_writes": padded // 16 * rounds,
                "source_writes": padded // 8 * rounds, "status_writes": rounds}
    parents = ("extent_reads", "row_reads", "segment_reads", "source_blocks", "apply_reads",
               "apply_writes", "source_writes", "status_writes")
    beats = tuple("source_lines" if key == "source_blocks" else key for key in parents)
    expected.update(axi_requests=sum(c[key] for key in parents), axi_completions=sum(c[key] for key in parents),
                    axi_beats=sum(c[key] for key in beats), axi_completed_beats=sum(c[key] for key in beats))
    changed = [key for key, value in expected.items() if c.get(key) != value]
    reads = sum(c[key] for key in ("extent_reads", "row_reads", "segment_reads", "source_lines", "apply_reads"))
    writes = sum(c[key] for key in ("apply_writes", "source_writes", "status_writes"))
    if changed or result["backend_reads"] != reads or result["backend_writes"] != writes:
        raise ValueError(f"independent traffic conservation failed: {changed}")
    arbitration = result["arbitration"]
    if (not arbitration["ledger_closed"] or arbitration["pending_intents"] or arbitration["pending_grants"]
            or any(arbitration[key] != c["axi_beats"] for key in
                   ("unique_intents", "grants", "consumed_grants"))):
        raise ValueError("memory arbitration did not drain")
    return {"status": "PASS", "directory_requests": c["extent_reads"] + c["row_reads"],
            "directory_bytes": (c["extent_reads"] + c["row_reads"]) * 64,
            "predicted_cycles": c["end_cycle"] - c["start_cycle"]}


def compare(reference: dict, candidate: dict, geometry: dict) -> dict:
    admitted = {arm: require_result(value, geometry, arm)
                for arm, value in (("original", reference), ("candidate", candidate))}
    changed = [key for key in reference["counters"] if key not in
               {"row_reads", "axi_requests", "axi_completions", "axi_beats", "axi_completed_beats", "start_cycle", "end_cycle"}
               and reference["counters"][key] != candidate["counters"][key]]
    if changed or [r["active_vertices"] for r in reference["rounds"]] != [r["active_vertices"] for r in candidate["rounds"]]:
        raise ValueError(f"candidate changed work or convergence: {changed}")
    return {"status": "FUNCTIONAL_AND_TRAFFIC_PASS_NOT_HARDWARE_TIMING", "arms": admitted,
            "work_and_round_activity_equal": True, "hardware_timing_admitted": False}
