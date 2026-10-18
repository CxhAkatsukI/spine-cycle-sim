"""Sequential kernel synthesis per bounded service; algorithms may run concurrently."""

from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment import probe
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment.contract import require_unchanged
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import high_memory
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from ....search_pipeline.synthesis import unchanged
from ..remote import environment
from . import commands, inputs, memory


def run(root, output, algorithm, xilinx, platform, compatibility, shim, *, memory_profile=None):
    root, output, xilinx, platform, compatibility, shim = (
        path.resolve() for path in (root, output, xilinx, platform, compatibility, shim))
    policy = memory.select(memory_profile, compile=True)
    sources = inputs.verify(root)
    output.mkdir(parents=True, exist_ok=False)
    group = current()
    report = {"status": "PREPARING", "algorithm": algorithm, "errors": [], "host": socket.gethostname(),
              "source_manifest": identity(root / "sources.json"), "policy": policy,
              "memory_profile": memory_profile,
              "compiles": [], **inputs.CLAIMS}
    save = lambda: atomic_write_json(output / "execution.json", report)
    lease = high_memory.lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group, policy)
    save()
    try:
        report["containment"] = verify(group, memory_gib=policy["tree_memory_gib"])
        report["disk_free_before_bytes"] = shutil.disk_usage(output).free
        if report["disk_free_before_bytes"] < 80 * 1024**3:
            raise ValueError("at least 80 GiB free compile disk required")
        for member in ("tmp", "user-data"):
            (output / member).mkdir()
        effective, contract = environment.capture(shim, output, xilinx, platform, compatibility)
        atomic_write_json(output / "environment.json", contract)
        argv, variables = inputs.generation(root, output, algorithm, xilinx, platform)
        with (output / "generation.stdout.txt").open("w") as stdout, \
                (output / "generation.stderr.txt").open("w") as stderr:
            subprocess.run(argv, env={**effective, **variables}, cwd=output, check=True,
                           stdout=stdout, stderr=stderr, timeout=60)
        packet = output / "packet"
        compiles = commands.compile_list(packet, algorithm, contract["tools"]["v++"]["invocation"], root / "source")
        pins = [report["source_manifest"], *[identity(root / row["member"]) for row in sources["files"]],
                *contract["pins"], identity(output / "environment.json"),
                *[identity(path) for path in sorted(packet.rglob("*")) if path.is_file()],
                identity(Path(sys.executable))]
        runners = sorted({Path(module.__file__) for name, module in sys.modules.copy().items()
            if name.startswith("spine_cycle_sim.experiments") and getattr(module, "__file__", None)})
        pins.extend(map(identity, runners))
        atomic_write_json(output / "manifest.json", {"source_manifest": report["source_manifest"],
            "integration_revision": sources["integration_revision"], "generation": argv,
            "generation_environment": variables, "algorithm": algorithm, "compiles": compiles,
            "pins": pins, "policy": policy, "memory_profile": memory_profile,
            "clock_mhz": 150, **inputs.CLAIMS})
        report["manifest"] = identity(output / "manifest.json")
        pins.append(report["manifest"])
        deadline = time.monotonic() + 86400
        while True:
            unchanged(pins)
            report["admission"] = lease.sample(available_memory_bytes(), other_builds(), policy, commit=True)
            report["status"] = "WAITING_FOR_MEMORY_NOT_OTHER_TOOLS"
            save()
            if report["admission"]["admitted"]:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("full finite compiler budgets do not fit")
            time.sleep(10)
        report["status"] = "ENVIRONMENT_PREFLIGHT"
        save()
        report["preflight"] = probe.run(output, effective, contract)
        pins.append(identity(output / "preflight/results.json"))
        for row in compiles:
            unchanged(pins)
            require_unchanged(contract, effective)
            report.update(status="COMPILING_NOT_ROUTED", current_kernel=row["kernel"])
            save()
            result = run_link(row["argv"], output, output / "compile" / row["kernel"],
                              environment=effective, timeout=3600, tree_memory_gib=policy["tree_memory_gib"],
                              reserve_gib=policy["reserve_gib"])
            record = {"kernel": row["kernel"], "resources": result}
            report["compiles"].append(record)
            save()
            if result["exit_code"] or result["stop_reason"] != "process_exit" or \
                    result["cleanup_snapshot_error"] or not Path(row["xo"]).is_file():
                raise RuntimeError("kernel compile failed; logs retained: " + row["kernel"])
            record["xo"] = identity(Path(row["xo"]))
            pins.append(record["xo"])
            unchanged(pins)
        report["status"] = "COMPILATION_PASS_AWAITING_RESOURCE_RTL_AND_ROUTE"
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        lease.release()
        report["memory_events_after"] = (group / "memory.events").read_text()
        save()
    return report
