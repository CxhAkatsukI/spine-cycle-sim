"""Compose explicit failed-case retries without modifying frozen campaigns."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from .run import admit


def read_campaign(directory):
    matrix_path = directory / "matrix.json"
    identity = json.loads((directory / "identity.json").read_text())
    if sha256_file(matrix_path) != identity["matrix_sha256"]:
        raise ValueError("frozen matrix changed")
    matrix = json.loads(matrix_path.read_text())
    cases = {case["execution_id"]: case for case in matrix["cases"]}
    if len(cases) != len(matrix["cases"]):
        raise ValueError("duplicate execution identity")
    return matrix, identity, cases, json.loads((directory / "status.json").read_text())


def equivalent(original, retry):
    def normalized(case):
        case = dict(case)
        command = list(case.pop("command"))
        case.pop("out_dir")
        for flag in ("--out-dir", "--profile"):
            position = command.index(flag) + 1
            if flag == "--profile":
                command[position] = sha256_file(Path(command[position]))
            else:
                command[position] = "<output>"
        return case, command

    if normalized(original) != normalized(retry):
        raise ValueError("retry changed workload, profile, split or execution command")


def select(campaign, replacements=()):
    matrix, identity, cases, status = read_campaign(campaign)
    origins = {key: campaign for key in cases}
    selected = dict(cases)
    for directory in replacements:
        _, retry_identity, retries, retry_status = read_campaign(directory)
        for key in ("plugin_sha256", "git_revision", "compiler", "source_hashes"):
            if identity[key] != retry_identity[key]:
                raise ValueError("retry implementation identity differs: " + key)
        for execution_id, state in retry_status.items():
            if (execution_id not in cases or not state.startswith("PASS")
                    or status.get(execution_id, "").startswith("PASS")
                    or origins[execution_id] != campaign):
                raise ValueError("replacement must retry one previously failed case exactly once")
            equivalent(cases[execution_id], retries[execution_id])
            selected[execution_id], origins[execution_id] = retries[execution_id], directory
    results, receipts = [], []
    for execution_id, case in selected.items():
        for pin in case["inputs"].values():
            if sha256_file(Path(pin["path"])) != pin["sha256"]:
                raise ValueError("input changed")
        path = Path(case["out_dir"]) / "case_result.json"
        wrapper = json.loads(path.read_text())
        if wrapper != admit(case, identity["plugin_sha256"]):
            raise ValueError("admission changed: " + execution_id)
        results.append(wrapper)
        directory = origins[execution_id]
        receipts.append(dict(execution_id=execution_id, campaign=str(directory),
            out_dir=case["out_dir"], retried=directory != campaign,
            receipt_sha256=sha256_file(path),
            identity_sha256=sha256_file(directory / "identity.json"),
            matrix_sha256=sha256_file(directory / "matrix.json"),
            status_sha256=sha256_file(directory / "status.json")))
    return matrix, identity, results, receipts
