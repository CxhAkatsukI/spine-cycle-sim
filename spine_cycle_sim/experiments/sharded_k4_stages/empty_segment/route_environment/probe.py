"""Bounded launcher and host-thread compatibility checks, not a Vivado route."""

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...execution import identity
from ...link_runtime import run_link
from .contract import require_unchanged

SOURCE = """#include <condition_variable>
#include <mutex>
#include <thread>
int main() {
    std::mutex mutex;
    std::condition_variable ready;
    bool done = false;
    std::thread worker([&] {
        std::lock_guard<std::mutex> lock(mutex);
        done = true;
        ready.notify_one();
    });
    { std::unique_lock<std::mutex> lock(mutex);
      ready.wait(lock, [&] { return done; }); }
    worker.join();
    return done ? 0 : 1;
}
"""


def run(output: Path, environment: dict, contract: dict) -> dict:
    directory = output / "preflight"
    directory.mkdir()
    source, binary = directory / "thread.cpp", directory / "thread"
    source.write_text(SOURCE)
    tools = contract["tools"]
    commands = [
        ("vitis_version", [tools["v++"]["invocation"], "--version"]),
        ("vivado_version", [tools["vivado"]["invocation"], "-version"]),
        ("gcc_version", [tools["gcc"]["invocation"], "--version"]),
        ("gxx_version", [tools["g++"]["invocation"], "--version"]),
        ("thread_compile", [tools["g++"]["invocation"], "-std=c++17", "-pthread", "-H",
                            "-D_GTHREAD_USE_COND_INIT_FUNC", str(source), "-o", str(binary)]),
        ("thread_execute", [str(binary)]),
    ]
    result = {"status": "running", "source": identity(source), "commands": [],
              "claim": "launcher_and_host_thread_smoke_not_vendor_internal_compiler_or_route_admission"}
    try:
        for label, command in commands:
            require_unchanged(contract, environment)
            record = run_link(command, output, directory / label, environment=environment,
                              timeout=90, tree_memory_gib=4, reserve_gib=16, poll_seconds=0.5)
            result["commands"].append({"label": label, **record})
            atomic_write_json(directory / "results.json", result)
            if record["exit_code"] or record["stop_reason"] != "process_exit" or record["cleanup_snapshot_error"]:
                raise RuntimeError("environment preflight failed: " + label)
            print("route environment " + label + " PASS", flush=True)
        for label in ("vitis_version", "vivado_version"):
            if "2024.1" not in (directory / (label + ".stdout.txt")).read_text():
                raise ValueError("vendor version differs: " + label)
        includes = (directory / "thread_compile.stderr.txt").read_text()
        shim = Path(environment["CPLUS_INCLUDE_PATH"]) / "bits/gthr-default.h"
        if str(shim) not in includes:
            raise ValueError("compatibility shim was not included by host compiler")
        require_unchanged(contract, environment)
        result.update(status="PREFLIGHT_PASS_NOT_ROUTED", executable=identity(binary))
    except Exception as error:
        result.update(status="PREFLIGHT_FAILED_NOT_ROUTED", error=str(error))
        raise
    finally:
        atomic_write_json(directory / "results.json", result)
    return result
