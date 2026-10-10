"""Post-hoc arithmetic clues, deliberately not a workload admission decision."""

from .analysis import publication_numerator


def residual_event_hypothesis(stats: dict, orders: list[dict], dataset: dict):
    unique_counts = {row["final_unique_edges"] for row in orders}
    if len(unique_counts) != 1:
        raise ValueError("complete edge set must not depend on temporal ordering")
    unique = unique_counts.pop()
    candidate = stats["events"] - stats["self_loop_events"] - unique
    implied = publication_numerator(dataset["paper_seconds"], dataset["paper_rate_million"])
    return {"status": "POST_HOC_ARITHMETIC_CLUE_NOT_ADMITTED_WORKLOAD",
        "formula": "all_raw_events - all_self_loop_events - full_trace_unique_edges_including_loops",
        "candidate_count": candidate, "full_trace_unique_edges_including_loops": unique,
        "implied_paper_numerator": implied,
        "within_printed_rounding_interval": implied["integer_min"] <= candidate <= implied["integer_max"],
        "actual_original_update_sequence_recovered": False,
        "candidate_is_proven_successful_update_count": False,
        "publication_timing_match": None,
        "warning": "This subtracts full unique edges including loops from nonself events; it is not a simple-graph insertion oracle. Recover the original converter and operation types before using it."}
