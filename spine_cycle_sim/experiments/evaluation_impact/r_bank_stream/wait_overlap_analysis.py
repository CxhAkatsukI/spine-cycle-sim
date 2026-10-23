"""Validate mutually exclusive wait masks; overlaps are not causal stage times."""

from .progress import read

NAMES = ("apply_output_stalls", "apply_read_stalls",
         "apply_pipeline_stalls", "apply_write_stalls", "writeback_pipeline_stalls",
         "writeback_write_stalls", "any_frontend_output_stall",
         "any_frontend_edge_wait")


def summarize(directory, cycles):
    rows = read(directory / "wait_overlap.csv", ("mask", "cycles"))
    if type(cycles) is not int or cycles <= 0 or not rows or any(
            row["mask"] >= 1 << len(NAMES) or row["cycles"] <= 0 for row in rows):
        raise ValueError("positive cycles and bounded wait masks required")
    if len({row["mask"] for row in rows}) != len(rows) or sum(r["cycles"] for r in rows) != cycles:
        raise ValueError("unique exclusive masks must cover every sampled cycle")
    marginal = {name: sum(r["cycles"] for r in rows if r["mask"] & (1 << bit))
                for bit, name in enumerate(NAMES)}
    with (directory / "backend_waits.csv").open() as stream:
        import csv
        backend = list(csv.DictReader(stream))
    if len(backend) != 1 or any(marginal[name] != int(backend[0][name]) for name in NAMES[:6]):
        raise ValueError("histogram disagrees with cumulative backend waits")
    both = lambda a, b: sum(r["cycles"] for r in rows if
        r["mask"] & (1 << NAMES.index(a)) and r["mask"] & (1 << NAMES.index(b)))
    pair_names = (("apply_output_stalls", "writeback_pipeline_stalls"),
                  ("apply_output_stalls", "writeback_write_stalls"),
                  ("apply_read_stalls", "apply_write_stalls"),
                  ("writeback_pipeline_stalls", "writeback_write_stalls"),
                  ("any_frontend_output_stall", "any_frontend_edge_wait"))
    return {"sampled_cycles": cycles, "marginal_cycles": marginal,
        "marginal_fraction": {key: value / cycles for key, value in marginal.items()},
        "joint_cycles": {a + " & " + b: both(a, b) for a, b in pair_names},
        "exclusive_histogram": rows,
        "interpretation": "joint observations, not additive stage time or causal attribution"}
