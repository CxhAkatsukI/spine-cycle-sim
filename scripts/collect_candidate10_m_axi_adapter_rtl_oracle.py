#!/usr/bin/env python3
"""Collect the frozen Candidate10 child-to-m_axi adapter RTL oracle."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_candidate10_m_axi_adapter_rtl_oracle.sh"
TESTBENCH = ROOT / "scripts/rtl/candidate10_m_axi_adapter_tb.sv"
XO = Path(
    "/data/feiyang/spine-dynamic-graph-builds/"
    "pipeline_dirty_frontier_publication_1e61fc0_20260725/production/"
    "hls_v5_candidate_10/spine_partconv_rdmaint_kernel.hw.xo"
)
XO_SHA256 = "629e185724467cc14eec4ae14018ff0a89a94aa518ef77499ca6cc2363b28be5"
RTL_MEMBER = (
    "ip_repo/xilinx_com_hls_spine_partconv_rdmaint_kernel_1_0/hdl/verilog/"
    "spine_partconv_rdmaint_kernel_gmem_p0_m_axi.v"
)
SUMMARY_RE = re.compile(r"\bAXI_ADAPTER_RTL\s+(?P<fields>.+)$")
BURST_RE = re.compile(r"\bAXI_ADAPTER_BURST\s+(?P<fields>.+)$")
EVENT_RE = re.compile(r"\bAXI_ADAPTER_EVENT\s+(?P<fields>.+)$")


@dataclass(frozen=True)
class AdapterCase:
    case_id: str
    op: int
    requests: int
    start_word: int
    beats: int
    stride_words: int
    response_delay: int = 1
    ar_stall_period: int = 0
    ar_stall_width: int = 0
    aw_stall_period: int = 0
    aw_stall_width: int = 0
    w_stall_period: int = 0
    w_stall_width: int = 0
    r_stall_period: int = 0
    r_stall_width: int = 0
    child_r_stall_period: int = 0
    child_r_stall_width: int = 0
    child_b_stall_period: int = 0
    child_b_stall_width: int = 0
    expect_outstanding_limit: bool = False
    expect_backpressure: bool = False
    expect_issue_throttle: bool = False
    trace_events: bool = False


CASES = [
    *(AdapterCase(
        f"{name}_aligned_{beats}", op, 1, 0, beats, 64
    ) for op, name in ((0, "read"), (1, "write"))
      for beats in (1, 15, 16, 17, 31, 32, 33)),
    *(AdapterCase(
        f"{name}_4k_w510_b4", op, 1, 510, 4, 64
    ) for op, name in ((0, "read"), (1, "write"))),
    *(AdapterCase(
        f"{name}_4k_w511_b17", op, 1, 511, 17, 64
    ) for op, name in ((0, "read"), (1, "write"))),
    *(AdapterCase(
        f"{name}_4k_w510_b33", op, 1, 510, 33, 64
    ) for op, name in ((0, "read"), (1, "write"))),
    *(AdapterCase(
        f"{name}_adjacent_requests", op, 2, 0, 8, 8
    ) for op, name in ((0, "read"), (1, "write"))),
    *(AdapterCase(
        f"{name}_adjacent_single_beats", op, 4, 0, 1, 1
    ) for op, name in ((0, "read"), (1, "write"))),
    *(AdapterCase(
        f"{name}_outstanding_17", op, 17, 0, 1, 64,
        response_delay=100, expect_outstanding_limit=True,
    ) for op, name in ((0, "read"), (1, "write"))),
    AdapterCase(
        "read_channel_backpressure", 0, 2, 510, 33, 64,
        response_delay=8,
        ar_stall_period=4, ar_stall_width=2,
        r_stall_period=5, r_stall_width=2,
        child_r_stall_period=7, child_r_stall_width=3,
        expect_backpressure=True,
        trace_events=True,
    ),
    AdapterCase(
        "read_fifo_saturation", 0, 3, 0, 256, 256,
        response_delay=1,
        child_r_stall_period=16, child_r_stall_width=15,
        expect_outstanding_limit=True,
        expect_backpressure=True,
        expect_issue_throttle=True,
    ),
    AdapterCase(
        "write_channel_backpressure", 1, 2, 510, 33, 64,
        response_delay=8,
        aw_stall_period=4, aw_stall_width=2,
        w_stall_period=5, w_stall_width=2,
        child_b_stall_period=7, child_b_stall_width=3,
        expect_backpressure=True,
        trace_events=True,
    ),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_fields(text: str) -> dict[str, int]:
    fields: dict[str, int] = {}
    for item in text.split():
        key, value = item.split("=", 1)
        fields[key] = int(value)
    return fields


def parse_event_fields(text: str) -> dict[str, int | str]:
    fields: dict[str, int | str] = {}
    for item in text.split():
        key, value = item.split("=", 1)
        try:
            fields[key] = int(value)
        except ValueError:
            fields[key] = value
    return fields


def parse_events(output: str) -> list[dict[str, int | str]]:
    return [
        parse_event_fields(match.group("fields"))
        for line in output.splitlines()
        if (match := EVENT_RE.search(line))
    ]


def normalize_raw_log(output: str) -> str:
    nondeterministic = (
        "  **** Start of session at:",
        "INFO: [Common 17-206] Exiting xsim at ",
        "$finish called at time :",
        "RTL oracle build directory:",
    )
    return "\n".join(
        line for line in output.splitlines()
        if not line.startswith(nondeterministic)
    ) + "\n"


def parse_oracle(output: str) -> tuple[dict[str, int], list[dict[str, int]]]:
    if "AXI_ADAPTER_TIMEOUT" in output:
        raise RuntimeError("adapter RTL oracle timed out")
    summary_matches = [
        match for line in output.splitlines()
        if (match := SUMMARY_RE.search(line))
    ]
    if len(summary_matches) != 1:
        raise RuntimeError(
            f"expected one AXI_ADAPTER_RTL line, found {len(summary_matches)}"
        )
    bursts = [
        parse_fields(match.group("fields"))
        for line in output.splitlines()
        if (match := BURST_RE.search(line))
    ]
    return parse_fields(summary_matches[0].group("fields")), bursts


def expected_bursts(case: AdapterCase) -> list[dict[str, int]]:
    bursts: list[dict[str, int]] = []
    for request in range(case.requests):
        address = (case.start_word + request * case.stride_words) * 8
        remaining = case.beats
        while remaining:
            page_remaining = 4096 - (address % 4096)
            page_beats = page_remaining // 8
            beats = min(remaining, 16, page_beats)
            bursts.append({"addr": address, "beats": beats})
            address += beats * 8
            remaining -= beats
    return bursts


def validate_oracle(
    case: AdapterCase,
    summary: dict[str, int],
    bursts: list[dict[str, int]],
) -> list[str]:
    failures: list[str] = []
    expected_summary = {
        "op": case.op,
        "requests": case.requests,
        "start_word": case.start_word,
        "beats": case.beats,
        "stride_words": case.stride_words,
        "response_delay": case.response_delay,
        "child_requests": case.requests,
        "child_write_beats": case.requests * case.beats if case.op == 1 else 0,
        "child_read_beats": case.requests * case.beats if case.op == 0 else 0,
        "child_responses": case.requests if case.op == 1 else 0,
        "external_beats": case.requests * case.beats,
        "errors": 0,
    }
    for key, value in expected_summary.items():
        if summary.get(key) != value:
            failures.append(f"{key}: expected {value}, got {summary.get(key)}")

    expected = expected_bursts(case)
    observed = [{"addr": row["addr"], "beats": row["beats"]}
                for row in bursts]
    if observed != expected:
        failures.append(f"burst trace: expected {expected}, got {observed}")
    if summary.get("external_bursts") != len(expected):
        failures.append(
            f"external_bursts: expected {len(expected)}, "
            f"got {summary.get('external_bursts')}"
        )
    if any(row["op"] != case.op or row["index"] != index
           for index, row in enumerate(bursts)):
        failures.append("burst operation/index sequence mismatch")
    if summary.get("max_outstanding", 0) > 16:
        failures.append("adapter exceeded the configured outstanding limit")
    if case.expect_outstanding_limit and summary.get("max_outstanding") != 16:
        failures.append(
            f"outstanding limit not reached: {summary.get('max_outstanding')}"
        )
    if case.expect_backpressure:
        if case.op == 0:
            if summary.get("child_response_stalls", 0) == 0:
                failures.append("read child backpressure was not exercised")
            if (case.ar_stall_period and
                    summary.get("external_address_stalls", 0) == 0):
                failures.append("read address-channel backpressure was not exercised")
        if case.op == 1 and (
            summary.get("external_address_stalls", 0) == 0
            or summary.get("external_data_stalls", 0) == 0
            or summary.get("child_response_stalls", 0) == 0
        ):
            failures.append("write backpressure did not exercise all channels")
    if case.expect_issue_throttle:
        issue_cycles = [row["issue_cycle"] for row in bursts]
        max_gap = max(
            (right - left for left, right in zip(issue_cycles, issue_cycles[1:])),
            default=0,
        )
        if max_gap < 128:
            failures.append(f"read issue throttle gap too small: {max_gap}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path)
    args = parser.parse_args()

    out_dir = args.out_dir.resolve()
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for stale in raw_dir.glob("*.log"):
        stale.unlink()
    build_dir = (
        args.build_dir.resolve() if args.build_dir
        else Path(tempfile.mkdtemp(
            prefix="candidate10_m_axi_adapter_oracle.",
            dir="/data/tmp/chuxiao",
        ))
    )
    if sha256(XO) != XO_SHA256:
        raise SystemExit("frozen Candidate10 XO hash mismatch")
    with zipfile.ZipFile(XO) as archive:
        adapter_sha256 = hashlib.sha256(archive.read(RTL_MEMBER)).hexdigest()

    rows: list[dict[str, object]] = []
    for stale_attempt in raw_dir.glob("*.attempt*.log"):
        stale_attempt.unlink()
    for index, case in enumerate(CASES):
        snapshot = build_dir / "xsim/xsim.dir/candidate10_m_axi_adapter_oracle"
        environment = os.environ.copy()
        environment.update({
            "BUILD_DIR": str(build_dir),
            "CANDIDATE10_XO": str(XO),
            "CANDIDATE10_XO_SHA256": XO_SHA256,
            "CANDIDATE10_ORACLE_REUSE": (
                "1" if index or snapshot.is_dir() else "0"
            ),
        })
        values = asdict(case)
        command = [str(RUNNER)]
        for key in (
            "op", "requests", "start_word", "beats", "stride_words",
            "response_delay", "ar_stall_period", "ar_stall_width",
            "aw_stall_period", "aw_stall_width", "w_stall_period",
            "w_stall_width", "r_stall_period", "r_stall_width",
            "child_r_stall_period", "child_r_stall_width",
            "child_b_stall_period", "child_b_stall_width",
        ):
            command.append(f"{key.upper()}={values[key]}")
        command.append("MAX_CYCLES=100000")
        if case.trace_events:
            command.append("TRACE=1")
        completed: subprocess.CompletedProcess[str] | None = None
        for attempt in range(2):
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=180,
            )
            if completed.returncode == 0:
                break
        assert completed is not None
        raw_path = raw_dir / f"{case.case_id}.log"
        raw_path.write_text(normalize_raw_log(completed.stdout), encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(f"adapter RTL failed for {case.case_id}: {raw_path}")
        summary, bursts = parse_oracle(completed.stdout)
        events = parse_events(completed.stdout)
        failures = validate_oracle(case, summary, bursts)
        if case.trace_events and not events:
            failures.append("trace case did not emit an event transcript")
        if not case.trace_events and events:
            failures.append("non-trace case emitted an event transcript")
        row: dict[str, object] = {
            **values,
            **summary,
            "expected_bursts": len(expected_bursts(case)),
            "max_burst_issue_gap": max(
                (right["issue_cycle"] - left["issue_cycle"]
                 for left, right in zip(bursts, bursts[1:])),
                default=0,
            ),
            "burst_trace": json.dumps(bursts, separators=(",", ":")),
            "event_trace": json.dumps(events, separators=(",", ":")),
            "status": "PASS" if not failures else "FAIL",
            "failures": "; ".join(failures),
            "raw_log": str(raw_path.relative_to(out_dir)),
        }
        rows.append(row)
        print(
            f"{row['status']} {case.case_id}: cycles={summary['cycles']} "
            f"bursts={summary['external_bursts']} "
            f"outstanding={summary['max_outstanding']}"
            + (f" ({row['failures']})" if failures else ""),
            flush=True,
        )

    csv_path = out_dir / "m_axi_adapter_oracle.csv"
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "schema_version": 2,
        "claim": "frozen_candidate10_child_to_m_axi_adapter_transaction_oracle",
        "xo": str(XO),
        "xo_sha256": XO_SHA256,
        "rtl_member": RTL_MEMBER,
        "rtl_member_sha256": adapter_sha256,
        "runner_sha256": sha256(RUNNER),
        "testbench_sha256": sha256(TESTBENCH),
        "collector_sha256": sha256(Path(__file__).resolve()),
        "build_dir": str(build_dir),
        "cases": len(rows),
        "all_pass": all(row["status"] == "PASS" for row in rows),
        "adapter_profile": {
            "child_data_width_bits": 64,
            "external_data_width_bits": 64,
            "address_width_bits": 64,
            "max_read_burst_beats": 16,
            "max_write_burst_beats": 16,
            "read_outstanding": 16,
            "write_outstanding": 16,
            "user_max_requests": 70,
            "conservative": True,
        },
        "validated": [
            "child word addresses convert to external byte addresses",
            "child beat counts convert to external AXI AxLEN plus one",
            "each child request splits at 16 beats and 4 KiB boundaries",
            "adjacent child requests are not coalesced",
            "read and write external outstanding counts are capped at 16",
            "channel stalls propagate through RTL and read-FIFO saturation throttles future address issue",
            "backpressure cases retain child/external data and response cycle transcripts",
            "write backpressure retains store-to-bridge and bridge-to-throttle cycle transcripts",
        ],
        "limitations": [
            "The external AXI responder is deterministic, not an HBM model.",
            "This oracle validates one generated gmem_p0 adapter; other Candidate10 adapters require profile/hash equivalence before inheriting the claim.",
            "Inter-port arbitration and U55C HBM contention are outside this single-adapter oracle.",
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if manifest["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
