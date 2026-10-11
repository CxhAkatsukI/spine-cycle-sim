"""Admit completed vendor artifacts after losing the link supervisor.

Recovery records artifact evidence, never an invented process exit code or
continuous resource-monitoring claim. Normal routed and board gates still apply.
"""

import json
from pathlib import Path
import re
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .execution import identity
from .link_runtime import tree_rss_kib


RECOVERED = "LINK_ARTIFACT_RECOVERED_AWAITING_TIMING_AND_BOARD"


def vendor_completion(stdout: str, stderr: str, steps: str, binary: Path) -> int:
    if any(re.search(r"^ERROR(?:\s|:)", value, re.MULTILINE)
           for value in (stdout, stderr, steps)):
        raise ValueError("vendor logs contain an error")
    markers = ("vpl status: success", "rtdgen status: success",
               "xclbinutil status: success", "xclbinutilinfo status: success",
               "hw completed", "system estimate report task completed")
    if any(marker not in steps.splitlines() for marker in markers):
        raise ValueError("vendor link steps are incomplete")
    if f"Created {binary}" not in stdout or "INFO: [v++ 60-1307] Run completed." not in stdout:
        raise ValueError("vendor did not report this xclbin completed")
    durations = re.findall(r"Total elapsed time: (\d+)h (\d+)m (\d+)s", stdout)
    if len(durations) != 1:
        raise ValueError("one vendor elapsed duration required")
    hours, minutes, seconds = map(int, durations[0])
    return hours * 3600 + minutes * 60 + seconds


def recover_route(output: Path) -> dict:
    output = output.resolve()
    if (output / "summary.json").exists() or (output / "route.resources.json").exists():
        raise FileExistsError("existing route outcome must not be replaced")
    manifest_path = output / "manifest.json"
    progress_path = output / "route.progress.json"
    manifest = json.loads(manifest_path.read_text())
    progress = json.loads(progress_path.read_text())
    if progress["stop_reason"] != "process_exit":
        raise ValueError("cannot recover an attempt stopped by a watchdog failure")
    processes = subprocess.check_output(["ps", "-eo", "pid=,ppid=,pgid=,rss="], text=True, timeout=10)
    if tree_rss_kib(processes, progress["pid"])[1]:
        raise RuntimeError("route process group or descendants still exist")
    stdout, stderr = output / "route.stdout.txt", output / "route.stderr.txt"
    steps = output / "logs/link/link.steps.log"
    binary = output / "candidate.hw.xclbin"
    pins = manifest["pins"] + [identity(path) for path in
            (manifest_path, progress_path, stdout, stderr, steps, binary)]
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("frozen route inputs changed")
    duration = vendor_completion(stdout.read_text(), stderr.read_text(), steps.read_text(), binary)
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("recovery evidence changed while reading")
    result = {"status": RECOVERED, "inputs_unchanged": True, "xclbin": identity(binary),
              "resources": None, "pins": pins,
              "recovery": {"process_exit_code": None, "vendor_elapsed_seconds": duration,
                           "last_supervisor_sample": progress,
                           "continuous_resource_monitoring_verified": False,
                           "configured_timeout_seconds": manifest["timeout_seconds"],
                           "vendor_duration_exceeded_configured_timeout": duration > manifest["timeout_seconds"]},
              "claim": "vendor_completed_artifact_recovered_after_supervisor_loss_not_a_monitored_run_pass"}
    atomic_write_json(output / "summary.json", result)
    return result
