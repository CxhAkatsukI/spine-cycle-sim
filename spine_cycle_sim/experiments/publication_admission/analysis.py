"""Conserved event/success counts and rounded publication-denominator intervals."""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .temporal import materialize_order, ordered_events


def rounded_interval(text: str):
    value = Decimal(text)
    half = Decimal(1).scaleb(value.as_tuple().exponent) / 2
    if value <= half:
        raise ValueError("rounded publication value must be positive")
    return value - half, value + half


def publication_numerator(seconds: str, rate_million: str):
    times = rounded_interval(seconds)
    rates = rounded_interval(rate_million)
    lower, upper = times[0] * rates[0] * 1000000, times[1] * rates[1] * 1000000
    return {"central": str(Decimal(seconds) * Decimal(rate_million) * 1000000),
            "integer_min": int(lower.to_integral_value(rounding=ROUND_CEILING)),
            "integer_max": int(upper.to_integral_value(rounding=ROUND_FLOOR)),
            "interpretation": "only_if_table_time_and_rate_share_one_aggregate_window"}


def equal_count_batch(position: int, base: int, total: int, batches: int):
    if not (0 <= base < total and base <= position < total and batches > 0):
        raise ValueError("invalid temporal batch position")
    return (position - base) * batches // (total - base)


def _success(connection, base: int, exclude_loops: bool):
    loop_filter = "AND (edge >> 32) != (edge & 4294967295)" if exclude_loops else ""
    return connection.execute(f"SELECT COUNT(*) FROM firsts WHERE first >= ? {loop_filter}", (base,)).fetchone()[0]


def analyze_order(connection, ordering: str, total: int, base: int, batches: int,
                  rounding_half_width: int):
    if not (batches > 0 and 0 < base < total and rounding_half_width >= 0
            and base - rounding_half_width >= 0 and base + rounding_half_width < total):
        raise ValueError("invalid base/count admission control")
    materialize_order(connection, ordering)
    unique = connection.execute("SELECT COUNT(*) FROM firsts").fetchone()[0]
    unique_loops = connection.execute("SELECT COUNT(*) FROM firsts WHERE (edge >> 32) = (edge & 4294967295)").fetchone()[0]
    counts = [0] * batches
    success = [0] * batches
    nonself = [0] * batches
    for edge, first in connection.execute("SELECT edge,first FROM firsts WHERE first >= ? ORDER BY first", (base,)):
        index = equal_count_batch(first, base, total, batches)
        success[index] += 1
        nonself[index] += (edge >> 32) != (edge & 4294967295)
    # Explicitly retain timestamps at the actual raw-event base cut, including ties.
    base_last = remaining_min = remaining_max = None
    time_counts = [0] * batches
    for position, (_, timestamp) in enumerate(ordered_events(connection, ordering)):
        if position == base - 1:
            base_last = timestamp
        if position >= base:
            counts[equal_count_batch(position, base, total, batches)] += 1
            remaining_min = timestamp if remaining_min is None else min(remaining_min, timestamp)
            remaining_max = timestamp if remaining_max is None else max(remaining_max, timestamp)
    if sum(counts) != total - base or sum(success) != _success(connection, base, False):
        raise ValueError("temporal aggregate conservation failed")
    result = {"ordering": ordering, "events": total, "base_raw_events": base,
        "base_unique_edges": unique - sum(success), "final_unique_edges": unique,
        "final_unique_nonself_edges": unique - unique_loops, "update_raw_events": total - base,
        "successful_new_edges": sum(success), "successful_new_nonself_edges": sum(nonself),
        "repeated_update_events": total - base - sum(success),
        "base_last_timestamp": base_last, "update_min_timestamp": remaining_min,
        "update_max_timestamp": remaining_max,
        "equal_event_count": [{"id": i, "raw_events": counts[i], "new_edges": success[i],
            "new_nonself_edges": nonself[i]} for i in range(batches)],
        "base_rounding_sensitivity": {"raw_base_min": base - rounding_half_width,
            "raw_base_max_inclusive": base + rounding_half_width - int(rounding_half_width > 0),
            "successful_new_edges_min": _success(connection, base + rounding_half_width - int(rounding_half_width > 0), False),
            "successful_new_edges_max": _success(connection, base - rounding_half_width, False)}}
    if ordering == "timestamp_then_file_order":
        span = remaining_max - remaining_min + 1
        for position, (_, timestamp) in enumerate(ordered_events(connection, ordering)):
            if position >= base:
                time_counts[(timestamp - remaining_min) * batches // span] += 1
        time_success, time_nonself = [0] * batches, [0] * batches
        for edge, timestamp in connection.execute("SELECT edge,earliest_timestamp FROM firsts WHERE first >= ?", (base,)):
            index = (timestamp - remaining_min) * batches // span
            time_success[index] += 1
            time_nonself[index] += (edge >> 32) != (edge & 4294967295)
        if sum(time_counts) != sum(counts) or sum(time_success) != sum(success) or sum(time_nonself) != sum(nonself):
            raise ValueError("timestamp batch conservation failed")
        result["equal_timestamp_span"] = [{"id": i, "raw_events": time_counts[i],
            "new_edges": time_success[i], "new_nonself_edges": time_nonself[i]} for i in range(batches)]
    return result


def compare_denominator(row: dict, seconds: str, rate_million: str):
    implied = publication_numerator(seconds, rate_million)
    low, high = implied["integer_min"], implied["integer_max"]
    sensitivity = row["base_rounding_sensitivity"]
    return {"implied_paper_numerator": implied,
        "raw_update_count_consistent": low <= row["update_raw_events"] <= high,
        "new_edge_count_consistent": low <= row["successful_new_edges"] <= high,
        "new_nonself_count_consistent": low <= row["successful_new_nonself_edges"] <= high,
        "base_rounding_success_intervals_overlap": sensitivity["successful_new_edges_min"] <= high
            and sensitivity["successful_new_edges_max"] >= low,
        "publication_timing_match": None,
        "status": "DENOMINATOR_CONTROL_ONLY_NOT_TIMING_ADMISSION"}
