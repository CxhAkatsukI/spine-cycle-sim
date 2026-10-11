"""Read XRT VTF host traces and align transfers with saved kernel events."""

import csv
import io
import math


SECTIONS = {"HEADER", "STRUCTURE", "MAPPING", "EVENTS", "DEPENDENCIES"}


def parse_vtf(text: str) -> dict:
    section = None
    seen_sections = set()
    header, mapping, rows, dependencies = {}, {}, {}, []
    for row in csv.reader(io.StringIO(text)):
        if not row or not any(row):
            continue
        if len(row) == 1 and row[0] in SECTIONS:
            section = row[0]
            if section in seen_sections:
                raise ValueError("duplicate VTF section")
            seen_sections.add(section)
            continue
        if section == "HEADER":
            if len(row) != 2 or row[0] in header:
                raise ValueError("invalid or duplicate VTF header")
            header[row[0]] = row[1]
        elif section == "MAPPING":
            key = int(row[0])
            if len(row) != 2 or key in mapping:
                raise ValueError("invalid or duplicate VTF mapping")
            mapping[key] = row[1]
        elif section == "EVENTS":
            if len(row) < 5:
                raise ValueError("truncated VTF event")
            key, start_id, stamp, lane = int(row[0]), int(row[1]), float(row[2]), int(row[3])
            if key <= 0 or key in rows or not math.isfinite(stamp) or stamp < 0:
                raise ValueError("invalid or duplicate VTF event identity/time")
            rows[key] = dict(id=key, start_id=start_id, ms=stamp, lane=lane,
                             type=row[4], args=row[5:])
        elif section == "DEPENDENCIES":
            if len(row) != 2:
                raise ValueError("invalid VTF dependency")
            dependencies.append(tuple(map(int, row)))
        elif section != "STRUCTURE":
            raise ValueError("unknown VTF section")
    if seen_sections != SECTIONS or header.get("Resolution") != "ms":
        raise ValueError("complete millisecond VTF host trace required")
    pairs, completed = [], set()
    for end in rows.values():
        if not end["start_id"]:
            continue
        start = rows.get(end["start_id"])
        if (not start or start["start_id"] or start["id"] in completed
                or (start["lane"], start["type"]) != (end["lane"], end["type"])
                or end["ms"] < start["ms"]):
            raise ValueError("orphan, duplicate or unordered VTF event pair")
        completed.add(start["id"])
        pairs.append(dict(start_id=start["id"], end_id=end["id"], start_ms=start["ms"],
                          end_ms=end["ms"], type=start["type"], args=start["args"]))
    if completed != {r["id"] for r in rows.values() if not r["start_id"]}:
        raise ValueError("incomplete VTF event pair")
    if len(set(dependencies)) != len(dependencies) or any(
            a not in rows or b not in rows for a, b in dependencies):
        raise ValueError("unknown or duplicate VTF dependency")
    return dict(header=header, mapping=mapping, pairs=pairs, dependencies=dependencies)


def trace_transfers(trace: dict, board: dict) -> dict:
    compute = [e for e in board["events"] if e["stage"] != "source_prepare"]
    begin = min(e["start_ns"] for e in compute) / 1e6
    end = max(e["end_ns"] for e in compute) / 1e6
    kernels = [p for p in trace["pairs"] if p["type"] == "KERNEL_ENQUEUE"]
    matched = {}
    for event in board["events"]:
        kernel = {"adapter": "pma_to_regraph_adapter", "gather": "lksg_stream",
                  "mux": "regraph_frontend_mux", "hbm": "kernelHBMWrapper",
                  "apply": "kernelApply"}.get(event["stage"])
        if kernel is None:
            raise ValueError("unsupported kernel stage in runtime alignment")
        candidates = [p for p in kernels if trace["mapping"].get(int(p["args"][0])) == kernel
                      and abs(p["start_ms"] - event["start_ns"] / 1e6) <= .01
                      and abs(p["end_ms"] - event["end_ns"] / 1e6) <= .01]
        if len(candidates) != 1 or candidates[0]["start_id"] in matched:
            raise ValueError("runtime/kernel profiling timestamps do not align uniquely")
        matched[candidates[0]["start_id"]] = event
    writes = [p for p in trace["pairs"] if p["type"] == "WRITE_BUFFER"]
    transfers = []
    for write in writes:
        if write["end_ms"] <= begin or write["start_ms"] >= end:
            continue
        if len(write["args"]) != 4:
            raise ValueError("unexpected XRT write fields")
        size, address, bank, _thread = write["args"]
        destinations = [matched[b] for a, b in trace["dependencies"]
                        if a == write["end_id"] and b in matched]
        earlier = [p for p in writes if p["end_ms"] <= begin
                   and p["args"][:3] == write["args"][:3]]
        transfers.append({"start_id": write["start_id"], "end_id": write["end_id"],
                          "start_ms": write["start_ms"], "end_ms": write["end_ms"],
                          "bytes": int(size), "physical_bo_address": address,
                          "bank": trace["mapping"][int(bank)],
                          "earlier_same_bo_write_ids": [p["start_id"] for p in earlier],
                          "dependent_kernels": [{k: e[k] for k in ("stage", "round", "shard", "worker")}
                                                for e in destinations]})
    row_bytes = (int(board["result"]["vertices"]) + 1) * 8
    api = [p for p in trace["pairs"] if p["type"] == "OPENCL_API_CALL"
           and trace["mapping"].get(int(p["args"][0])) == "clEnqueueTask"
           and p["start_ms"] >= begin and p["end_ms"] <= end]
    return {"compute_window_ms": [begin, end], "aligned_kernels": len(matched),
            "compute_write_count": len(transfers), "compute_write_bytes": sum(p["bytes"] for p in transfers),
            "all_compute_writes_row_sized": all(p["bytes"] == row_bytes for p in transfers),
            "all_compute_writes_precede_dependent_adapter": all(
                len(p["dependent_kernels"]) == 1 and p["dependent_kernels"][0]["stage"] == "adapter"
                for p in transfers),
            "last_compute_enqueue_api_end_ms": max((p["end_ms"] for p in api), default=None),
            "writes": transfers,
            "limits": ["XRT host trace, not AXI or exclusive stage counters",
                       "an earlier same-BO host write does not prove earlier PCIe DMA",
                       "transfer durations overlap and are not an additive total-time penalty"]}
