#!/usr/bin/env python3
"""Collect sharded Full PageRank route evidence for the refresh packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTE_DIR = Path(
    "/data/tmp/chuxiao/grasu_regraph_sharded_k4_fullpr_hw_646c8a8_20260810_route"
)
DEFAULT_OUT_DIR = ROOT / "docs" / "evaluation_refresh_20260810"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (FileNotFoundError, ValueError):
        return None


def log_tail(path: Path, lines: int = 24) -> list[str]:
    if not path.is_file():
        return []
    content = [
        line.rstrip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
    ]
    return content[-lines:]


def timing_summary(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"present": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    row = re.search(
        r"\n\s*(?P<wns>-?\d+\.\d+)\s+"
        r"(?P<tns>-?\d+\.\d+)\s+"
        r"(?P<tns_failing>\d+)\s+"
        r"(?P<tns_total>\d+)\s+"
        r"(?P<whs>-?\d+\.\d+)\s+"
        r"(?P<ths>-?\d+\.\d+)\s+"
        r"(?P<ths_failing>\d+)\s+"
        r"(?P<ths_total>\d+)\s+"
        r"(?P<wpws>-?\d+\.\d+)\s+"
        r"(?P<tpws>-?\d+\.\d+)\s+"
        r"(?P<tpws_failing>\d+)\s+"
        r"(?P<tpws_total>\d+)\s*\n",
        text,
    )
    if row is None:
        return {"present": True, "parsed": False}
    return {
        "present": True,
        "parsed": True,
        "wns_ns": float(row.group("wns")),
        "tns_ns": float(row.group("tns")),
        "tns_failing_endpoints": int(row.group("tns_failing")),
        "tns_total_endpoints": int(row.group("tns_total")),
        "whs_ns": float(row.group("whs")),
        "ths_ns": float(row.group("ths")),
        "ths_failing_endpoints": int(row.group("ths_failing")),
        "ths_total_endpoints": int(row.group("ths_total")),
        "wpws_ns": float(row.group("wpws")),
        "tpws_ns": float(row.group("tpws")),
        "tpws_failing_endpoints": int(row.group("tpws_failing")),
        "tpws_total_endpoints": int(row.group("tpws_total")),
        "constraints_met": "Timing constraints are met." in text,
    }


def classify_status(
    log_text: str, xclbin: Path, running: bool, timing: dict[str, object]
) -> str:
    lowered = log_text.lower()
    if xclbin.is_file() and (
        "build completed successfully" in lowered
        or "v++ completed successfully" in lowered
        or "run completed" in lowered
        or re.search(r"finished .*step impl", lowered)
    ):
        if timing.get("parsed") and not timing.get("constraints_met"):
            return "PASS_TIMING_MISS"
        return "PASS"
    if "error:" in lowered or "failed" in lowered or "command failed" in lowered:
        return "FAIL"
    if running:
        return "RUNNING"
    return "UNKNOWN"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-dir", type=Path, default=DEFAULT_ROUTE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--tail-lines", type=int, default=24)
    args = parser.parse_args()

    route_dir = args.route_dir.resolve()
    log_path = route_dir / "logs" / "fullpr_route_bg_20260810_182948.log"
    xclbin = route_dir / "build" / "grasu_regraph_full_pagerank.hw.xclbin"
    link_summary = route_dir / "build" / "grasu_regraph_full_pagerank.hw.xclbin.link_summary"
    timing_report = (
        route_dir
        / "reports"
        / "link"
        / "link"
        / "imp"
        / "impl_1_hw_bb_locked_timing_summary_routed.rpt"
    )
    util_report = (
        route_dir
        / "reports"
        / "link"
        / "link"
        / "imp"
        / "impl_1_kernel_util_routed.rpt"
    )
    manifest = route_dir / "manifest.json"
    pid = read_pid(route_dir / "route.pid")
    running = bool(pid is not None and process_alive(pid))
    tail = log_tail(log_path, args.tail_lines)
    log_text = "\n".join(tail)
    timing = timing_summary(timing_report)
    status = classify_status(log_text, xclbin, running, timing)
    artifacts = []
    for path in (xclbin, link_summary, timing_report, util_report, manifest, log_path):
        if path.is_file():
            artifacts.append(
                {
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    payload = {
        "status": status,
        "route_dir": str(route_dir),
        "pid": pid,
        "pid_running": running,
        "xclbin_present": xclbin.is_file(),
        "link_summary_present": link_summary.is_file(),
        "timing_report_present": timing_report.is_file(),
        "util_report_present": util_report.is_file(),
        "timing": timing,
        "artifacts": artifacts,
        "log_tail": tail,
    }
    provenance_dir = args.out_dir / "provenance"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    json_path = provenance_dir / "fullpr_route.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if timing.get("parsed"):
        timing_note = (
            f"WNS={timing['wns_ns']} ns, TNS={timing['tns_ns']} ns, "
            f"setup failing endpoints={timing['tns_failing_endpoints']}; "
            f"constraints_met={timing['constraints_met']}"
        )
    else:
        timing_note = "not parsed"

    md_path = args.out_dir / "fullpr_status.md"
    md_path.write_text(
        "# Full PageRank Evidence Status\n\n"
        "The current compact Full PageRank panel uses three correctness-admitted routed\n"
        "K4-shared FPGA workloads: Amazon-2008, Web-Google, and Flickr. The plotted\n"
        "metric is setup-inclusive G+R/Delta.hls latency speedup over three repetitions,\n"
        "not the older kernel-window ratio.\n\n"
        f"Sharded K4 Full PageRank route status: `{status}`.\n\n"
        f"- Route directory: `{route_dir}`\n"
        f"- PID: `{pid}`; running: `{running}`\n"
        f"- XCLBIN present: `{xclbin.is_file()}`\n"
        f"- Link summary present: `{link_summary.is_file()}`\n\n"
        f"- Timing report present: `{timing_report.is_file()}`\n"
        f"- Timing summary: `{timing_note}`\n\n"
        "This evidence is intentionally labeled `compact_one_partition` until the\n"
        "destination-sharded K4 Full PageRank xclbin routes successfully and its\n"
        "correctness/performance matrix passes. If that happens, panel (d) can be\n"
        "replaced without changing the other panels' layout.\n\n"
        "## Latest Route Log Tail\n\n"
        "```text\n"
        + "\n".join(tail)
        + "\n```\n",
        encoding="utf-8",
    )
    print(f"FULLPR_ROUTE_EVIDENCE_{status} out={json_path}")
    return 0 if status != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
