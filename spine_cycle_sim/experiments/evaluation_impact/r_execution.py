"""Memory-bounded, process-isolated execution of the fixed R matrix."""

from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..upstream_controls.execution import available_memory_bytes, run_bounded
from .analysis import MATRIX, parse_demo


def run_case(root, output, binary, cpu, maximum, timeout, identity):
    latency, reverse, arm = identity
    label = f"r_lat{latency}_reverse{reverse}_{arm}"
    state = output / "states" / label
    state.mkdir(parents=True)
    print("RUN " + label, flush=True)
    command = ["taskset", "-c", str(cpu), str(binary), str(output / "inputs/warm_update"),
               str(state), str(latency), str(reverse), str(maximum), arm]
    step = run_bounded(command, root, output / "raw" / label,
                       timeout=timeout, memory_gib=4, reserve_gib=24)
    case = {"identity": identity, "step": step}
    try:
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("nonzero exit or wall-time bound")
        observations = parse_demo(Path(step["stdout"]).read_text())
        if observations["result"]["arm"] != arm:
            raise ValueError("executed arm differs from contract")
        case["row"] = {"latency": latency, "reverse": reverse, "arm": arm,
            "observations": observations, "outputs": [{"name": p.name, "sha256": sha256_file(p),
                "bytes": p.stat().st_size} for p in sorted(state.iterdir())]}
    except ValueError as error:
        case["error"] = repr(error)
    print("DONE " + label + (" PASS" if "row" in case else " FAILED_RETAINED"), flush=True)
    return case


def run_matrix(root, output, binary, cpus, maximum, timeout, record):
    if available_memory_bytes() < (24 + 4 * len(cpus)) * 1024**3:
        raise RuntimeError("insufficient memory for concurrent process limits plus reserve")
    # Spawn avoids running the resource-limited Popen preexec_fn in a threaded parent.
    with ProcessPoolExecutor(max_workers=len(cpus), mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(run_case, root, output, binary, cpus[i % len(cpus)], maximum, timeout, identity)
                   for i, identity in enumerate(MATRIX)]
        for future in as_completed(futures):
            record(future.result())
