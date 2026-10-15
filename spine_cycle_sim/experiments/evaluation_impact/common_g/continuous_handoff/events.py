"""Validate resident G/R event conservation, convergence and host-inclusive boundaries."""

from collections import Counter
import json

from ..continuous_board.execution.events import ROLES as G_ROLES, STAMP_KEYS, close, window
from .analysis import TIMES, nonnegative

BOARD_MARKER = "CONTINUOUS_GR_BOARD_CORRECTNESS_PASS_NOT_BASELINE_ADMISSION"
R_ROLES = {"hbm", "apply", "adapter", "little", "mux"}
TRANSFER_ROLES = {"update_dma", "seed_dma", "fallback_dma", "active_readback", "result_readback"}


def state(case, row, index):
    expected = case["batches"][index]
    if any(type(row.get(key)) is not type(value) or row[key] != value for key, value in expected.items()) or \
            row.get("board") is not True or row.get("converged") is not True or \
            row.get("state_pass") is not True or row.get("restored_pma") is not False or \
            type(row.get("checked_words")) is not int or row["checked_words"] != 2 * 131072 * 16 + 32 or \
            type(row.get("checked_vertices")) is not int or row["checked_vertices"] != case["vertices"] or \
            any(not nonnegative(row.get(key)) for key in TIMES):
        raise ValueError("board handoff state/policy/timing disagreement")
    counts = row.get("active_counts")
    if type(counts) is not list or not counts or len(counts) > 2048 or counts[-1] != 0 or \
            any(type(count) is not int or not 0 <= count <= case["vertices"] for count in counts) or \
            any(count == 0 for count in counts[:-1]) or type(row.get("rounds")) is not int or \
            row["rounds"] != len(counts) or counts != case["expected_active_counts"][index] or \
            (index == 0 and (counts != [0] or row["fallback"] or row["seed_sources"])):
        raise ValueError("board convergence differs from the admitted preflight trajectory")


def record(event, batch, previous_end):
    if set(event) != {"batch", "stage", "role", "index", *STAMP_KEYS} or any(
            type(event[key]) is not int or event[key] < 0 for key in ("batch", "index", *STAMP_KEYS)) or \
            event["batch"] != batch or event["stage"] not in ("G", "R", "transfer"):
        raise ValueError("event outside the declared batch/stage")
    roles = {"G": G_ROLES, "R": R_ROLES, "transfer": TRANSFER_ROLES}
    if event["role"] not in roles[event["stage"]]:
        raise ValueError("event role outside its stage")
    stamps = [event[key] for key in STAMP_KEYS]
    if stamps != sorted(stamps) or event["end_ns"] <= event["start_ns"] or stamps[0] <= previous_end:
        raise ValueError("invalid event timestamps or cross-batch overlap")


def before(first, second):
    if first and second and max(event["end_ns"] for event in first) > min(
            event["queued_ns"] for event in second):
        raise ValueError("DMA/G/R/convergence handoff ordering disagreement")


def ledger(row, events):
    grouped = {stage: [event for event in events if event["stage"] == stage] for stage in ("G", "R", "transfer")}
    g, r, transfers = (grouped[key] for key in ("G", "R", "transfer"))
    if Counter((event["role"], event["index"]) for event in g) != Counter((role, 0) for role in G_ROLES) or \
            Counter((event["role"], event["index"]) for event in r) != Counter(
                (role, round) for round in range(row["rounds"]) for role in R_ROLES):
        raise ValueError("missing or duplicate G/R kernel events")
    expected = Counter({("update_dma", 0): min(4, row["updates"]), ("result_readback", 0): 1})
    expected.update(("active_readback", round) for round in range(row["rounds"]))
    if row["fallback"]:
        expected["fallback_dma", 0] = 3
    else:
        expected["seed_dma", 0] = 2 * row["seed_sources"]
    if Counter((event["role"], event["index"]) for event in transfers) != +expected:
        raise ValueError("missing or duplicate update/seed/fallback/convergence/result transfers")
    select = lambda role: [event for event in transfers if event["role"] == role]
    before(select("update_dma"), g)
    seed = select("seed_dma") + select("fallback_dma")
    before(g, seed or r)
    before(seed, r)
    for round in range(row["rounds"]):
        kernels = [event for event in r if event["index"] == round]
        active = [event for event in select("active_readback") if event["index"] == round]
        before(kernels, active)
        before(active, [event for event in r if event["index"] == round + 1] or select("result_readback"))
    if any(not close(row[key], window(grouped[stage])[0]) for stage, key in (("G", "g_busy_ms"), ("R", "r_busy_ms"))):
        raise ValueError("reported kernel union differs from raw G/R events")
    if row["g_ready_wall_ms"] + 0.01 < row["host_preparation_ms"] + window(g)[1] + window(select("update_dma"))[1] or \
            row["host_inclusive_e2e_ms"] + 0.01 < row["g_ready_wall_ms"] + window(r)[1] or \
            row["host_inclusive_e2e_ms"] + 0.01 < row["host_preparation_ms"] + window(events)[1]:
        raise ValueError("raw events exceed the host-inclusive timing boundary")


def analyze(case, stdout, stderr, *, bdf):
    lines = stdout.splitlines()
    if stderr.strip() or len(lines) < 5 or not lines[0].startswith("CONTINUOUS_GR_SETUP ") or lines[-1] != BOARD_MARKER:
        raise ValueError("incomplete or diagnostic board handoff output")
    if case["shards"] != 1 or case["partition_vertices"] != 65536 or len(case["batches"]) != 3 or \
            len(case.get("expected_active_counts", [])) != 3:
        raise ValueError("single-partition three-batch preflight trajectories required")
    setup = json.loads(lines[0].removeprefix("CONTINUOUS_GR_SETUP "))
    if setup.get("board") is not True or setup.get("device_bdf") != bdf or \
            setup.get("initial_state") != "old_graph_converged" or \
            any(type(setup.get(key)) is not int or setup[key] != value
                for key, value in (("shards", 1), ("source", 0), ("round_limit", 2048))) or \
            type(setup.get("hbm_bytes")) is not int or setup["hbm_bytes"] <= 5 * 65536 * 4 + 4 or \
            not nonnegative(setup.get("one_time_setup_ms")):
        raise ValueError("board setup/device identity disagreement")
    rows, pending, all_events, previous_end = [], [], [], -1
    for line in lines[1:-1]:
        if len(rows) >= 3:
            raise ValueError("unexpected output after three batches")
        if line.startswith("CONTINUOUS_GR_EVENT "):
            event = json.loads(line.removeprefix("CONTINUOUS_GR_EVENT "))
            record(event, len(rows), previous_end)
            pending.append(event)
            continue
        if not line.startswith("CONTINUOUS_GR_ROW "):
            raise ValueError("unexpected board output")
        row = json.loads(line.removeprefix("CONTINUOUS_GR_ROW "))
        state(case, row, len(rows))
        ledger(row, pending)
        rows.append(row)
        all_events.extend(pending)
        previous_end = max(event["end_ns"] for event in pending)
        pending = []
    if len(rows) != 3 or pending:
        raise ValueError("incomplete three-batch board handoff")
    return {"setup": setup, "rows": rows, "events": all_events}
