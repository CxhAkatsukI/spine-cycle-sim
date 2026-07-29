#!/usr/bin/env python3
"""Repair completed jobs rejected only by the obsolete arbitration cross-ledger."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Sequence


EXPECTED_ERROR = (
    "RuntimeError: publication parent admission failed: "
    "registered_arbitration_requests"
)


@dataclass(frozen=True)
class RepairCandidate:
    campaign_dir: Path
    job_id: str
    execution_id: str
    command: tuple[str, ...]
    cwd: Path
    job_dir: Path
    result_path: Path


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _state_path(campaign_dir: Path) -> Path:
    direct = campaign_dir / "campaign_state.json"
    nested = campaign_dir / "run" / "campaign_state.json"
    if direct.is_file():
        return direct
    if nested.is_file():
        return nested
    raise FileNotFoundError(f"campaign state not found below {campaign_dir}")


def _already_repaired(result_path: Path) -> bool:
    if not result_path.is_file():
        return False
    result = _load_json(result_path)
    admission = result.get("admission")
    return (
        result.get("status") == "pass"
        and isinstance(admission, Mapping)
        and admission.get("reused_child") is True
    )


def find_repair_candidates(campaign_dir: Path) -> tuple[RepairCandidate, ...]:
    campaign_dir = campaign_dir.resolve()
    manifest = _load_json(campaign_dir / "campaign_manifest.json")
    state = _load_json(_state_path(campaign_dir))
    specs = {
        str(job["job_id"]): job
        for job in manifest.get("jobs", [])
        if isinstance(job, Mapping) and "job_id" in job
    }
    candidates = []
    for job in state.get("jobs", []):
        if not isinstance(job, Mapping) or job.get("status") != "fail":
            continue
        progress = job.get("progress")
        if not isinstance(progress, Mapping) or progress.get("status") != "pass":
            continue
        job_id = str(job.get("job_id", ""))
        spec = specs.get(job_id)
        if not isinstance(spec, Mapping):
            continue
        command_value = spec.get("command")
        if not isinstance(command_value, list) or not all(
            isinstance(argument, str) for argument in command_value
        ):
            continue
        command = tuple(command_value)
        if not any(Path(argument).name == "run_publication_case.py" for argument in command):
            continue
        if "--reuse-child" in command:
            continue
        log_path = Path(str(job.get("log_path", "")))
        if not log_path.is_file():
            continue
        error_lines = [
            line.strip()
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("RuntimeError: publication parent admission failed:")
        ]
        if error_lines != [EXPECTED_ERROR]:
            continue
        execution_id = job_id.rsplit(".", 1)[-1]
        result_path = campaign_dir / "runs" / execution_id / "case_result.json"
        if _already_repaired(result_path):
            continue
        cwd_value = spec.get("cwd", manifest.get("default_cwd", "."))
        candidates.append(
            RepairCandidate(
                campaign_dir=campaign_dir,
                job_id=job_id,
                execution_id=execution_id,
                command=command,
                cwd=Path(str(cwd_value)).resolve(),
                job_dir=log_path.parent,
                result_path=result_path,
            )
        )
    return tuple(candidates)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repair_candidate(candidate: RepairCandidate) -> dict[str, Any]:
    started = time.time()
    completed = subprocess.run(
        (*candidate.command, "--reuse-child"),
        cwd=candidate.cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    finished = time.time()
    repair_log = candidate.job_dir / "registered_arbitration_repair.log"
    repair_log.write_text(completed.stdout, encoding="utf-8")
    result_valid = _already_repaired(candidate.result_path)
    audit = {
        "schema_version": 1,
        "repair": "reuse_completed_child_after_registered_arbitration_cross_ledger_fix",
        "candidate": {
            **asdict(candidate),
            "campaign_dir": str(candidate.campaign_dir),
            "command": list(candidate.command),
            "cwd": str(candidate.cwd),
            "job_dir": str(candidate.job_dir),
            "result_path": str(candidate.result_path),
        },
        "original_error": EXPECTED_ERROR,
        "repair_command": [*candidate.command, "--reuse-child"],
        "started_at": started,
        "finished_at": finished,
        "returncode": completed.returncode,
        "result_valid": result_valid,
        "result_sha256": (
            _sha256(candidate.result_path) if result_valid else None
        ),
        "repair_log": str(repair_log),
        "status": "pass" if completed.returncode == 0 and result_valid else "fail",
    }
    audit_path = candidate.job_dir / "registered_arbitration_repair.json"
    audit_path.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, action="append", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    candidates = tuple(
        candidate
        for campaign_dir in args.campaign_dir
        for candidate in find_repair_candidates(campaign_dir)
    )
    if args.dry_run:
        for candidate in candidates:
            print(candidate.job_id)
        print(f"repair_candidates={len(candidates)}")
        return 0
    failed = 0
    for candidate in candidates:
        audit = repair_candidate(candidate)
        print(f"{audit['status'].upper()} {candidate.job_id}")
        failed += audit["status"] != "pass"
    print(f"repair_candidates={len(candidates)} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
