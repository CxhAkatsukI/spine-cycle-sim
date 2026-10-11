"""Cross-check the new cycle adapter and production HLS on shared packet fixtures."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .execution import identity


def require_case_report(text: str, *, hls: bool) -> int:
    pattern = (r"HLS shared-fixture packet check PASS cases=(\d+)" if hls else
               r"Routed shared-master PMA adapter PASS cases=(\d+) "
               r"pressure_latency_registration_and_completion_checks=PASS")
    reports = re.findall(r"^" + pattern + r"$", text, re.MULTILINE)
    expected = 27 if hls else 288
    if reports != [str(expected)]:
        raise ValueError("one complete passing adapter case report required")
    return expected


def validate_adapter(*, root: Path, integration: Path, vitis: Path,
                     core_build: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    hls = integration / "kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp"
    probe = root / "cpp/tests/routed_regraph/adapter_hls_test.cpp"
    simulator = core_build / "cpp/routed_pma_adapter_tests"
    sources = [hls, hls.with_name("row_prefetch.hpp"), probe,
               root / "cpp/tests/routed_regraph/adapter_fixture.hpp",
               root / "cpp/tests/routed_regraph/adapter_tests.cpp",
               root / "cpp/include/spine_sim/regraph_pma_adapter.hpp",
               root / "cpp/src/regraph_pma_adapter.cpp",
               root / "cpp/src/detail/grasu_regraph_payload.hpp",
               Path(__file__), root / "scripts/validate_sharded_k4_adapter_model.py"]
    pins = [identity(path) for path in sources + [simulator, core_build / "cpp/libspine_cycle_core.a"]]
    manifest = {"schema_version": 1, "sources_and_executable": pins,
                "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
                "affinity": sorted(os.sched_getaffinity(0)),
                "vitis_include": str(vitis.resolve()),
                "claim": "packet_equivalence_and_finite_resources_not_hardware_timing",
                "matrix": {"formats": ["weighted", "destination", "unit"],
                           "prefetch": [0, 1], "stop": [0, 1],
                           "vertices": [0, 1, 8, 9, 65, 1025],
                           "last_occupied": ["early", "last"], "empty": [False, True]}}
    atomic_write_json(output / "manifest.json", manifest)
    attempts = []

    def run(command: list[str], name: str, timeout: int) -> None:
        result = run_bounded(command, root, output / name, timeout=timeout,
                             memory_gib=8, reserve_gib=16)
        attempts.append({"name": name, "resources": result})
        atomic_write_json(output / "attempts.json", attempts)
        if result["exit_code"]:
            raise RuntimeError(f"{name} failed; all attempt logs retained at {output}")

    run([str(simulator)], "cycle_model", 300)
    simulator_cases = require_case_report((output / "cycle_model.stdout.txt").read_text(), hls=False)
    hls_cases = 0
    for mode, weighted, destination in (("weighted", 1, 0), ("destination", 0, 1), ("unit", 0, 0)):
        for prefetch in (0, 1):
            for stop in (0, 1):
                name = f"{mode}_prefetch{prefetch}_stop{stop}"
                binary = output / name
                command = ["g++", "-std=c++20", "-O2", "-Wno-unknown-pragmas",
                           "-I", str(root / "cpp/include"), "-isystem", str(vitis),
                           f"-DGRASU_REGRAPH_WEIGHTED_PMA={weighted}",
                           f"-DGRASU_REGRAPH_DESTINATION_ONLY={destination}",
                           "-DGRASU_REGRAPH_SHARDED_PMA=1",
                           "-DGRASU_REGRAPH_SHARE_ALL_MEMORY_PORTS=1",
                           f"-DGRASU_REGRAPH_ROW_PREFETCH={prefetch}",
                           f"-DGRASU_REGRAPH_STOP_AFTER_LAST={stop}",
                           f'-DGRASU_ADAPTER_SOURCE="{hls}"',
                           str(probe), "-lgmp", "-o", str(binary)]
                run(command, name + "_build", 300)
                run([str(binary)], name + "_run", 120)
                hls_cases += require_case_report((output / f"{name}_run.stdout.txt").read_text(), hls=True)
                print(f"{name} packet fixtures PASS", flush=True)
    if [identity(Path(pin["path"])) for pin in pins] != pins:
        raise RuntimeError("input or executable changed during adapter validation")
    result = {"schema_version": 1, "status": "PASS", "claim": manifest["claim"],
              "hls_variants": 12, "hls_fixture_calls": hls_cases,
              "simulator_primary_cases": simulator_cases, "source_unchanged": True,
              "attempts": attempts}
    atomic_write_json(output / "summary.json", result)
    return result
