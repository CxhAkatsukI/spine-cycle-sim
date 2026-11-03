"""Gate the weighted SSSP and CC adapters without reserving a full route budget."""

import argparse
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from . import component
from .concurrent import Lease
from .containment import GIB, current, other_builds, verify


MODES = {"weighted_sssp": ("weighted", "-DGRASU_REGRAPH_WEIGHTED_PMA=1"),
         "connected_components": ("destination", "-DGRASU_REGRAPH_DESTINATION_ONLY=1")}
POLICY = {"tree_memory_gib": 8, "reserve_gib": 40,
          "background_memory_gib": 0, "allow_bounded_builds": True}
RTL_TESTS = ("pma_prefetch_compact_cosim.tcl", "pma_prefetch_compact_cosim_tb.cpp",
             "repair_cosim_axi_ids.tcl")


def mode_for(packet, argv):
    manifest = dict(line.split("=", 1) for line in
                    (packet / "manifest.env").read_text().splitlines() if line)
    mode, flag = MODES[manifest["ALGORITHM"]]
    mode_flags = set(argv).intersection(pair[1] for pair in MODES.values())
    if (mode_flags != {flag} or manifest["ADAPTER_MODE_DEFINE"] != flag
            or manifest["PIPELINE_MODE"] != "sharded-k4"
            or manifest["PHYSICAL_PORT_POLICY"] != "shared-ingress"
            or not {"-DGRI_HMSS_SHARED_INGRESS=1", "-DGRASU_REGRAPH_SHARDED_PMA=1",
                    "-DGRASU_REGRAPH_SHARE_ALL_MEMORY_PORTS=1"}.issubset(argv)):
        raise ValueError("component and RTL must use the same sharded shared-ingress mode")
    integration = Path(manifest["GRI_ROOT"])
    if Path(argv[-1]) != integration / "kernels/pma_prefetch_compact/top.cpp":
        raise ValueError("unexpected adapter compile source")
    return mode, integration, manifest["HLS_INCLUDE"]


def stage(output, argv, env, pins, *, binary=None):
    output.mkdir(parents=True, exist_ok=False)
    temporary = output / "tmp"
    temporary.mkdir()
    env = {**env, **{key: str(temporary) for key in ("TMPDIR", "TMP", "TEMP")}}
    atomic_write_json(output / "manifest.json", {"command": argv, "pins": pins})
    record = output / "execution.json"
    report = {"status": "RUNNING_" + ("COMPONENT" if binary else "RANDOM_STALL_RTL"),
              "board_tested": False, "policy": POLICY}
    atomic_write_json(record, report)
    try:
        result = run_link(argv, output, output / "job", environment=env, timeout=1800,
                          tree_memory_gib=POLICY["tree_memory_gib"], reserve_gib=POLICY["reserve_gib"])
        report["resources"] = result
        component.unchanged(pins)
        if result["exit_code"] or result["stop_reason"] != "process_exit" or result["cleanup_snapshot_error"]:
            raise RuntimeError("component job failed; raw logs retained")
        if binary:
            report.update(status="COMPONENT_XO_PASS_NOT_ROUTED", xo=identity(binary))
        else:
            marker = "PMA_RANDOM_STALL_RTL_OUTPUT_CHECK_PASS"
            if marker not in (output / "job.stdout.txt").read_text().splitlines():
                raise RuntimeError("finite RTL did not complete all output comparisons")
            report["status"] = "FINITE_RANDOM_STALL_RTL_PASS_NOT_BOARD"
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        atomic_write_json(record, report)


def run(packet):
    evidence = packet / "evidence"
    evidence.mkdir(exist_ok=False)
    group = current()
    lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    report = {"status": "PREPARING", "policy": POLICY, "board_tested": False}
    try:
        limits = verify(group, POLICY["tree_memory_gib"])["limits"]
        if int(limits["memory.high"]) > 7 * GIB:
            raise ValueError("component memory.high must leave room below the hard limit")
        pins = component.pins(packet) + component.runner_pins()
        argv, binary, env = component.command(packet, "pma_to_regraph_adapter")
        mode, integration, include = mode_for(packet, argv)
        report["mode"] = mode
        report["admission"] = lease.sample(available_memory_bytes(), other_builds(), POLICY, commit=True)
        if not report["admission"]["admitted"]:
            raise RuntimeError("complete compiler budget plus reserve does not fit")
        report["status"] = "RUNNING_COMPONENT_GATES"
        atomic_write_json(evidence / "execution.json", report)
        stage(evidence / "adapter", argv, env, pins, binary=binary)
        rtl = evidence / ("rtl-" + mode)
        rtl_env = dict(env, PMA_COSIM_OUT=str(rtl), PMA_COSIM_MODE=mode,
                       PMA_COSIM_SHARED="1", HLS_INCLUDE=include)
        tests = [integration / "tests" / name for name in RTL_TESTS]
        stage(rtl, ["vitis_hls", "-f", str(tests[0])], rtl_env, pins + list(map(identity, tests)))
        report["status"] = "COMPONENT_GATES_PASS_NOT_ROUTED"
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        lease.release()
        report["memory_events_after"] = (group / "memory.events").read_text()
        atomic_write_json(evidence / "execution.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    print(run(parser.parse_args().packet.resolve()))
