"""Bounded independent-case concurrency; canonical evidence order is separate."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from ..upstream_controls.execution import available_memory_bytes


def parallel(jobs, worker, contract):
    jobs = list(jobs)
    if not jobs:
        return
    if len({name for name, _ in jobs}) != len(jobs):
        raise ValueError("finite PMA duplicate parallel case")
    workers = min(contract["parallel_processes"], len(jobs))
    required = workers * contract["memory_limit_gib"] + contract["reserve_gib"]
    if workers < 1 or available_memory_bytes() < required * 1024**3:
        raise RuntimeError("insufficient available memory for all bounded PMA workers plus reserve")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(worker, payload): name for name, payload in jobs}
        for future in as_completed(pending):
            yield pending[future], future.result()


def step_order(contract, instrumented):
    names = ["configure", "build", "ctest", "routing_normal_compile", "routing_ubsan_compile",
             "source_first", "source_repeat", "source_ubsan", "finite_routing"]
    names += [prefix + case["id"] for case in contract["cases"] for prefix in ("legacy_", "matched_")]
    names += ["pma_" + case["id"] for case in contract["cases"]]
    names += ["pma_r_ubsan_compile"]
    names += ["ubsan_" + row["id"] for row in instrumented if row["status"] != "NOT_RUN_NORMAL_NOT_ADMITTED"]
    return names + ["focused_tests"]
