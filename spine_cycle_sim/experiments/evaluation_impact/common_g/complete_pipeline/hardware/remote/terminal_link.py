"""Recover a finished transient link after systemd unloads its unit."""

import json
import shlex
import subprocess

from ....continuous_board.execution.supervisor import route_finished, service_state


def unloaded(state):
    return (state["LoadState"], state["ActiveState"], state["SubState"], state["InvocationID"]) == (
        "not-found", "inactive", "dead", "")


def terminal(state, unit, invocation, attempt):
    if not unloaded(state):
        return route_finished(state, invocation)
    records = state.get("terminal_journal", [])
    if not records or any(
            row.get("USER_UNIT") != unit or row.get("USER_INVOCATION_ID") != invocation
            or row.get("_SYSTEMD_USER_UNIT") != "init.scope"
            or row.get("_EXE") not in ("/usr/lib/systemd/systemd", "/lib/systemd/systemd")
            or row.get("UNIT_RESULT", "success") != "success" or row.get("EXIT_STATUS", "0") != "0"
            or row.get("JOB_RESULT", "done") != "done" for row in records):
        raise ValueError("unloaded link lacks a clean exact-invocation manager journal")
    starts = [row for row in records if row.get("MESSAGE_ID") == "39f53479d3a045ac8e11786248231fbf"]
    finishes = [row for row in records if row.get("MESSAGE_ID") == "ae8f7b866b0347b9af31fe1c80b127c0"]
    if len(starts) != 1 or len(finishes) != 1 or starts[0]["_BOOT_ID"] != finishes[0]["_BOOT_ID"]:
        raise ValueError("unloaded link lacks an unambiguous start and teardown")
    if int(starts[0]["__MONOTONIC_TIMESTAMP"]) >= int(finishes[0]["__MONOTONIC_TIMESTAMP"]):
        raise ValueError("manager teardown predates the requested link")
    command = shlex.split(starts[0]["MESSAGE"].partition(" - ")[2].removesuffix("."))
    if command.count("--output") != 1 or command[-1] == "--output":
        raise ValueError("link manager journal does not identify its output")
    if command[command.index("--output") + 1] != str(attempt):
        raise ValueError("manager journal names a different link attempt")
    # Resource accounting establishes teardown, not success. The sealer also
    # requires the matching build's successful execution record and pinned files.
    return True


def capture(unit, invocation, attempt):
    state = service_state(unit)
    if unloaded(state):
        journal = subprocess.run(
            ["journalctl", "--user", "--boot", "--no-pager", "-o", "json",
             f"USER_UNIT={unit}", f"USER_INVOCATION_ID={invocation}"],
            check=True, capture_output=True, text=True, timeout=20)
        state["terminal_journal"] = [json.loads(line) for line in journal.stdout.splitlines()]
    if not terminal(state, unit, invocation, attempt):
        raise ValueError("route service is still running; no return package")
    return state
