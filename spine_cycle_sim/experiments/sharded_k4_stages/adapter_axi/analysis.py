"""Validate a complete AXI transcript without imposing fitted cycle values."""

from collections import deque
import re


TRIALS = [(0, 0, 1, 1, 0), (1, 0, 1, 1, 0), (8, 0, 1, 1, 0),
          (9, 0, 1, 1, 0), (17, 0, 1, 1, 0), (17, 0, 1, 64, 0),
          (17, 0, 1, 128, 0), (17, 0, 3, 64, 0), (17, 1, 1, 64, 0),
          (17, 2, 1, 64, 0), (17, 3, 1, 64, 0), (17, 0, 1, 64, 1000)]
CONFIG = ("vertices", "placement", "length", "latency", "stall")
CASE = ("trial", *CONFIG, "start", "cycles", "row_requests", "row_beats",
        "row_transfer_bytes", "pma_requests", "pma_beats", "pma_transfer_bytes",
        "packets", "first_packet", "last_packet", "done")
AR = ("trial", "cycle", "address", "beats", "size")
R = ("trial", "cycle", "address", "size", "last")
ROW_BASE = 0x80000


def _records(text: str, prefix: str, fields: tuple) -> list[dict]:
    pattern = "^" + prefix + " " + " ".join(f"{key}=(-?\\d+)" for key in fields) + "$"
    rows = [dict(zip(fields, map(int, values))) for values in re.findall(pattern, text, re.M)]
    if len(rows) != len(re.findall("^" + prefix + " ", text, re.M)):
        raise ValueError(f"malformed {prefix} record")
    return rows


def parse_trace(text: str) -> list[dict]:
    cases = _records(text, "AXI_CASE", CASE)
    requests, responses = _records(text, "AXI_AR", AR), _records(text, "AXI_R", R)
    if (text.count("ADAPTER_AXI_PASS cases=12") != 1
            or re.search(r"\b(?:fatal|error|fail)\b", text, re.I)
            or [tuple(case[key] for key in CONFIG) for case in cases] != TRIALS
            or [case["trial"] for case in cases] != list(range(len(TRIALS)))
            or any(row["trial"] not in range(len(TRIALS)) for row in requests + responses)):
        raise ValueError("complete twelve-case production AXI transcript required")
    for case in cases:
        trial = case["trial"]
        if (case["cycles"] != case["done"] - case["start"] or case["cycles"] <= 0
                or (trial and case["start"] <= cases[trial - 1]["done"])):
            raise ValueError("invalid invocation completion timeline")
        sources = [source for source in range(case["vertices"])
                   if (case["placement"] == 0
                       or case["placement"] == 1 and source + 1 == case["vertices"]
                       or case["placement"] == 2 and source == 0
                       or case["placement"] == 3 and source % 7 == 0)]
        if case["packets"] != len(sources) * case["length"] * 2:
            raise ValueError("incomplete packet count")
        if case["packets"]:
            if not case["start"] < case["first_packet"] <= case["last_packet"] <= case["done"]:
                raise ValueError("output outside invocation")
            if case["first_packet"] < case["start"] + case["stall"]:
                raise ValueError("packet accepted before sink became ready")
        elif (case["first_packet"], case["last_packet"]) != (-1, -1):
            raise ValueError("empty invocation emitted a packet")
        reads = [row for row in requests if row["trial"] == trial]
        returns = [row for row in responses if row["trial"] == trial]
        for events in (reads, returns):
            cycles = [row["cycle"] for row in events]
            if any(right <= left for left, right in zip(cycles, cycles[1:])):
                raise ValueError("AXI channel timeline is not strictly ordered")
        for kind, lower, upper in (("row", ROW_BASE, ROW_BASE + 576), ("pma", 0x10000, ROW_BASE)):
            selected = [row for row in reads if lower <= row["address"] < upper]
            if (case[kind + "_requests"] != len(selected)
                    or case[kind + "_beats"] != sum(row["beats"] for row in selected)
                    or case[kind + "_transfer_bytes"] != sum(row["beats"] * row["size"] for row in selected)):
                raise ValueError("AXI request, beat or transfer-byte conservation failed")
        if len(reads) != case["row_requests"] + case["pma_requests"]:
            raise ValueError("unmapped AXI request")
        expanded = []
        for row in reads:
            if (row["size"] not in (1, 2, 4, 8, 16, 32, 64) or not 1 <= row["beats"] <= 256
                    or row["address"] % row["size"]
                    or row["address"] % 4096 + row["size"] * row["beats"] > 4096):
                raise ValueError("invalid external AXI burst")
            expanded += [(row["address"] + beat * row["size"], row["size"],
                          int(beat + 1 == row["beats"]), row["cycle"])
                         for beat in range(row["beats"])]
        if len(expanded) != len(returns):
            raise ValueError("AXI responses missing")
        for expected, response in zip(expanded, returns):
            if (expected[:3] != tuple(response[key] for key in ("address", "size", "last"))
                    or response["cycle"] <= expected[3] + case["latency"]
                    or response["cycle"] > case["done"]):
                raise ValueError("AXI response identity or latency differs")
        pending = deque()
        maximum = 0
        final_beat = -1
        for row in reads:
            if not case["start"] <= row["cycle"] <= case["done"]:
                raise ValueError("AXI request outside invocation")
            while pending and pending[0] < row["cycle"]:
                pending.popleft()
            # Pair each request with its final accepted R beat, in issue order.
            final_beat += row["beats"]
            pending.append(returns[final_beat]["cycle"])
            maximum = max(maximum, len(pending))
        case["maximum_outstanding"] = maximum
        case["requests"] = reads
        case["responses"] = returns
    return cases
