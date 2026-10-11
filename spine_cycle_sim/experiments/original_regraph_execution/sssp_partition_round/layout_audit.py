"""Static PMA work derived from frozen CSR, not measured stall attribution."""

from ..sssp_real_round.preparation import read_words


def audit(capture, vertices, partitions=4, partition_vertices=65536):
    offsets = read_words(capture / "csr_offsets.u32le")
    destinations = read_words(capture / "csr_destinations.u32le")
    if (len(offsets) != vertices + 1 or offsets[0] != 0 or offsets[-1] != len(destinations)
            or any(a > b for a, b in zip(offsets, offsets[1:]))):
        raise ValueError("invalid captured CSR offsets")
    rows = [{"partition": p, "live_edges": 0, "nonempty_sources": 0, "source_zero_live_edges": 0,
             "last_nonempty_source": -1, "segments": 0} for p in range(partitions)]
    for source in range(vertices):
        degrees = [0] * partitions
        for position in range(offsets[source], offsets[source + 1]):
            destination = destinations[position]
            if not 0 <= destination < vertices:
                raise ValueError("invalid captured CSR destination")
            degrees[destination // partition_vertices] += 1
        for row, degree in zip(rows, degrees):
            if source == 0:
                row["source_zero_live_edges"] = degree
            if degree:
                row["live_edges"] += degree
                row["nonempty_sources"] += 1
                row["last_nonempty_source"] = source
                row["segments"] += (degree + 15) // 16
    for row in rows:
        # Routed admission reserves a source-0 dummy segment for empty row 0.
        forced = int(row["source_zero_live_edges"] == 0)
        row["forced_dummy_source_zero_segments"] = forced
        row["segments"] += forced
        visited = row["last_nonempty_source"] + 1
        row.update({"rows_visited": visited, "empty_rows_visited": visited - row["nonempty_sources"] - forced,
                    "row_read_requests": min(vertices, ((visited + 7) // 8) * 8),
                    "physical_slots": row["segments"] * 16})
        row["dummy_slots"] = row["physical_slots"] - row["live_edges"]
        row["serial_row_control_cycles"] = visited * 6
        row["serial_empty_exit_cycles"] = row["empty_rows_visited"] * 73
    return {"scope": "static_CSR_layout_work_not_runtime_stall_or_FPGA_attribution",
            "assumptions": {"unique_pairs_no_reserved_updates": True, "segment_slots": 16,
                            "prefetch_rows": 8, "stop_after_last": True,
                            "row_control_cycles": 6, "empty_segment_exit_cycles": 73},
            "partitions": rows,
            "longest_worker_serial_row_and_empty_cycle_lower_bound": max(
                row["serial_row_control_cycles"] + row["serial_empty_exit_cycles"] for row in rows)}


def bind_traffic(result, cases):
    rows = result["partitions"]
    for case in cases:
        k4 = case["paths"][1]
        if (k4["row_reads"] != sum(row["row_read_requests"] for row in rows)
                or k4["segment_reads"] != sum(row["segments"] for row in rows)
                or k4["live_edges"] != sum(row["live_edges"] for row in rows)
                or k4["dummy_edges"] != sum(row["dummy_slots"] for row in rows)
                or k4["cycles"] < result["longest_worker_serial_row_and_empty_cycle_lower_bound"]):
            raise ValueError("static PMA work differs from runtime traffic or cycle lower bound")
