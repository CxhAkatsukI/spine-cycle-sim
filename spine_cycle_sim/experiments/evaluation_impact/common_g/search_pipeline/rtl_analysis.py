"""Interpret synthesis and all eighteen RTL transactions without timing promotion."""

import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from .analysis import PACKET

COUNTS = (0, 1, 63, 64, 65, 127, 128, 129, 257)


def parse_bench(contents):
    packets = [tuple(map(int, row)) for row in PACKET.findall(contents)]
    if [row[0] for row in packets] != [count for count in COUNTS for _ in range(2)] or \
            any(row[2] or row[3] for row in packets):
        raise ValueError("incomplete normal RTL testbench C-simulation scope")
    return {"calls": len(packets), "counts": [row[0] for row in packets],
            "ordered_packets_pass": True, "claim": "testbench_source_not_RTL_execution"}


def transactions(contents):
    lines = contents.splitlines()
    if not lines or lines[0].split() != ["latency", "interval"]:
        raise ValueError("unexpected RTL transaction header")
    rows = []
    for line in lines[1:]:
        match = re.fullmatch(r"transaction\s+(\d+):\s+(\d+)\s+(\d+|x)\s*", line)
        if not match:
            raise ValueError("unexpected RTL transaction grammar")
        index, latency, interval = match.groups()
        rows.append({"index": int(index), "latency": int(latency),
                     "interval": None if interval == "x" else int(interval)})
    if [row["index"] for row in rows] != list(range(len(COUNTS) * 2)):
        raise ValueError("incomplete or duplicate RTL transaction scope")
    for row in rows:
        row.update(updates=COUNTS[row["index"] // 2], same_key=bool(row["index"] % 2))
    return rows


def analyze_rtl(folder):
    reports = []
    for path in sorted(folder.glob("project/solution/syn/report/*csynth.xml")):
        tree = ET.parse(path).getroot()
        reports.append({"path": str(path), "sha256": sha256_file(path),
            "clock_ns": tree.findtext("PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod"),
            "resources": {child.tag: child.text for child in tree.findall("AreaEstimates/Resources/*")},
            "loops": [{"name": loop.tag, **{child.tag: child.text for child in loop}}
                      for loop in tree.findall(".//SummaryOfLoopLatency/*")]})
    tops = [row for row in reports if Path(row["path"]).name == "bin_search_pipeline_csynth.xml"]
    if len(tops) != 1:
        raise ValueError("missing or duplicate top synthesis report")
    csim = folder / "project/solution/csim/report/bin_search_pipeline_csim.log"
    parse_bench(csim.read_text())
    cosim = folder / "project/solution/sim/report/bin_search_pipeline_cosim.rpt"
    if not re.search(r"Verilog\s*\|\s*Pass\s*\|", cosim.read_text()):
        raise ValueError("RTL co-simulation did not pass")
    transaction = folder / "project/solution/sim/report/verilog/result.transaction.rpt"
    rows = transactions(transaction.read_text())
    clock = float(tops[0]["clock_ns"])
    if not math.isfinite(clock) or clock <= 0:
        raise ValueError("invalid clock estimate")
    return {"reports": reports, "top_clock_ns": clock, "target_5ns_met": clock <= 5,
            "top_resources": tops[0]["resources"], "transactions": rows,
            "csim": {"path": str(csim), "sha256": sha256_file(csim)},
            "cosim": {"path": str(cosim), "sha256": sha256_file(cosim), "report": cosim.read_text()},
            "transaction_report": {"path": str(transaction), "sha256": sha256_file(transaction)},
            "external_RTL_backpressure_tested": False, "integrated_g_admitted": False,
            "hardware_timing_admitted": False}
