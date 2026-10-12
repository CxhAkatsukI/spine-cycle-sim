"""Preserve edge work; account for directory prefetch and actual HLS schedule."""

from collections import Counter
import re
import xml.etree.ElementTree as ET

from ...adapter_axi.analysis import ROW_BASE, TRIALS as BASE_TRIALS
from .contract import TILE_ROWS, TRIALS

ALL_TRIALS = BASE_TRIALS + TRIALS


def model_schedule(result):
    """Require the realized topology before selecting its finite model."""
    tile = result.get("tile_rows", TILE_ROWS)
    packet = result.get("packet_pipeline", False)
    bank = result.get("bank_stream", False)
    bank_lines = result.get("bank_fifo_lines", 128)
    depths = {"load_directory_tile_loop": 3, "read_tiled_sources_loop": 2 if bank else 74}
    if packet:
        depths["publish_packet_loop"] = 2
    if bank:
        depths.update(load_join_directory_loop=2, read_cached_bank_loop=3, read_external_bank_loop=3)
    if (result.get("status") != "HLS_SCHEDULE_PASS_NOT_BOARD" or
            tile not in (128, 1024) or type(packet) is not bool or type(bank) is not bool or
            (packet and tile != 1024) or (bank and not packet) or
            type(bank_lines) is not int or bank_lines not in (128, 256) or (bank_lines != 128 and not bank) or
            any(result.get("schedule", {}).get(key, {}).get("ii") != 1 or
                result["schedule"][key].get("depth") != depth for key, depth in depths.items())):
        raise ValueError("realized directory/edge schedule required; model is not an II override")
    return tile, packet, bank


def functional(text, packet_pipeline=False, bank_stream=False):
    rows = re.findall(r"^ROW_PREFETCH_EQUIVALENCE status=PASS cases=(\d+) packets=(\d+) "
                      r"skip_empty=1 row_line=1 cross_row=1$", text, re.M)
    expected_cases = 435 if bank_stream else 443 if packet_pipeline else 362
    if len(rows) != 3 or len(Counter(rows)) != 1 or int(rows[0][0]) != expected_cases or int(rows[0][1]) <= 1482:
        raise ValueError("three extended edge-format packet gates required")


def compare(reference, candidate, tile_rows=TILE_ROWS, trials=ALL_TRIALS, bank_stream=False):
    if len(reference) != len(trials) or len(candidate) != len(trials):
        raise ValueError("complete boundary/tail matrix required")
    results = []
    for old, new in zip(reference, candidate):
        keys = ("trial", "vertices", "placement", "length", "latency", "stall", "packets",
                "pma_beats", "pma_transfer_bytes")
        if any(old[key] != new[key] for key in keys):
            raise ValueError("tile changes edge work or the declared experiment")
        def beats(row, directory):
            return [(request["address"] + lane * request["size"], request["size"])
                    for request in row["requests"] if (request["address"] >= ROW_BASE) == directory
                    for lane in range(request["beats"])]
        old_pma, new_pma = beats(old, False), beats(new, False)
        if ((Counter(old_pma) != Counter(new_pma)) if bank_stream else (old_pma != new_pma)):
            raise ValueError("tile changes PMA beat order or identity")
        count = new["vertices"]
        if not count:
            expected = []
        else:
            occupied = [src for src in range(count) if new["placement"] == 0 or
                        new["placement"] == 1 and src + 1 == count or
                        new["placement"] == 2 and src == 0 or
                        new["placement"] == 3 and src % 7 == 0]
            end = min(count, (occupied[-1] // tile_rows + 1) * tile_rows)
            expected = [((count - 1) // 8)] + list(range((end + 7) // 8))
        actual = beats(new, True)
        if actual != [(ROW_BASE + line * 64, 64) for line in expected]:
            raise ValueError("all prefetched directory beats must be accounted")
        results.append({key: new[key] for key in keys} | {
            "reference_cycles": old["cycles"], "candidate_cycles": new["cycles"],
            "candidate_over_reference": new["cycles"] / old["cycles"],
            "reference_row_bytes": old["row_transfer_bytes"],
            "candidate_row_bytes": new["row_transfer_bytes"],
            "candidate_row_requests": new["row_requests"]})
    return results


def schedules(build, packet_pipeline=False, bank_stream=False):
    result = {}
    labels = ("load_directory_tile_loop", "read_tiled_sources_loop")
    if packet_pipeline:
        labels += ("publish_packet_loop",)
    if bank_stream:
        labels += ("load_join_directory_loop", "read_cached_bank_loop", "read_external_bank_loop")
    for label in labels:
        found = []
        for path in build.rglob("*csynth.xml"):
            root = ET.parse(path).getroot()
            loop = root.find(f"PerformanceEstimates/SummaryOfLoopLatency/{label}")
            if loop is None:
                continue
            found.append({"path": str(path), "ii": int(loop.findtext("PipelineII")),
                          "depth": int(loop.findtext("PipelineDepth")),
                          "target_ns": float(root.findtext("UserAssignments/TargetClockPeriod")),
                          "estimated_ns": float(root.findtext(
                              "PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod"))})
        expected = 2 if bank_stream and "bank_loop" in label else 1
        if (len(found) != expected or any(row["ii"] <= 0 or row["depth"] <= 0 for row in found)
                or any({k:v for k,v in row.items() if k != "path"} !=
                       {k:v for k,v in found[0].items() if k != "path"} for row in found)):
            raise ValueError("one actual loop schedule required: " + label)
        result[label] = found[0]
    return result
