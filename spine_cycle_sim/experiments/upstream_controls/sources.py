"""Verify immutable author snapshots and generate isolated ReGraph topologies."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


GENERATED_FILES = (
    "acc_template/kernel_little_gs_merger/kernel_little_gs_merger.cpp",
    "acc_template/kernel_big_gs_merger/kernel_big_gs_merger.cpp",
    "acc_template/kernel_hbm_wrapper/hbm_wrapper.h",
    "acc_template/kernel_hbm_wrapper/kernel_hbm_wrapper.cpp",
    "acc_template/connectivity.cfg",
    "host/host_config/hbm_mapping.h",
)


def verify_snapshot(source: Path, pin: dict) -> dict:
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True,
    ).strip()
    changes = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=source, text=True,
    ).strip()
    if revision != pin["revision"] or changes:
        raise ValueError(f"{pin['id']}: source revision or worktree differs from clean pin")
    for item in pin["files"]:
        if sha256_file(source / item["path"]) != item["sha256"]:
            raise ValueError(f"{pin['id']}: pinned source changed: {item['path']}")
    return {"id": pin["id"], "revision": revision, "files": pin["files"]}


def merger_invocation(little: int) -> str:
    if isinstance(little, bool) or not isinstance(little, int) or not 1 <= little <= 14:
        raise ValueError("Little count must be an integer in [1, 14]")
    arguments = ", ".join(f"inputs[{index}]" for index in range(little))
    return (
        "inline void call_little_merger(\n"
        "    hls::stream<l_tmp_prop_pkt> (&inputs)[LITTLE_KERNEL_NUM],\n"
        "    hls::stream<write_burst_pkt> &output) {\n"
        f"  kernelLittleGSMerger({arguments}, output);\n"
        "}\n"
    )


def big_merger_invocation(big: int) -> str:
    arguments = ", ".join(f"inputs[{index}]" for index in range(big))
    return (
        "inline void call_big_merger(\n"
        "    hls::stream<b_tmp_prop_pkt> (&inputs)[BIG_KERNEL_NUM],\n"
        "    hls::stream<write_burst_pkt> &output) {\n"
        f"  kernelBigGSMerger({arguments}, output);\n"
        "}\n"
    )


def prepare_regraph(source: Path, destination: Path, little: int, big: int,
                    generator_python: str) -> dict:
    if (isinstance(big, bool) or not isinstance(big, int) or big < 0
            or little + big > 14):
        raise ValueError("ReGraph topology exceeds the original U280 port budget")
    invocation = merger_invocation(little)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git", "dataset"))
    command = [generator_python, "autogen/autogen.py", str(little), str(big), "true", "false"]
    generated = subprocess.run(command, cwd=destination, capture_output=True, text=True,
                               timeout=30)
    (destination / "autogen.stdout.txt").write_text(generated.stdout, encoding="utf-8")
    (destination / "autogen.stderr.txt").write_text(generated.stderr, encoding="utf-8")
    if generated.returncode:
        raise ValueError(f"upstream generator failed; inspect {destination / 'autogen.stderr.txt'}")
    (destination / "little_merger_call.hpp").write_text(invocation, encoding="ascii")
    invocation_files = ["little_merger_call.hpp"]
    if big:
        (destination / "big_merger_call.hpp").write_text(big_merger_invocation(big), encoding="ascii")
        invocation_files.append("big_merger_call.hpp")
    files = [
        {"path": name, "sha256": sha256_file(destination / name)}
        for name in (*GENERATED_FILES, *invocation_files)
    ]
    connectivity = (destination / "acc_template/connectivity.cfg").read_text()
    active_lines = [line for line in connectivity.splitlines() if line.strip()
                    and not line.lstrip().startswith("#")]
    if big == 0 and any("bigKernel" in line or "kernelBig" in line for line in active_lines):
        raise ValueError("zero-Big generation retained an active Big connection")
    return {"little": little, "big": big, "command": command, "generated_files": files}


def read_pins(path: Path) -> dict[str, dict]:
    document = json.loads(path.read_text(encoding="ascii"))
    if document.get("schema_version") != 1:
        raise ValueError("unsupported source pin schema")
    pins = {item["id"]: item for item in document["sources"]}
    if set(pins) != {"grasu", "regraph"} or len(document["sources"]) != 2:
        raise ValueError("source pins must uniquely identify GraSU and ReGraph")
    return pins
