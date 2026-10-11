"""Validate paired C/RTL outputs and retain per-call helper timing."""

from pathlib import Path
import re
import xml.etree.ElementTree as ET

from ..execution import identity
from ..rtl import parse_cosim_report

CASES = [(v, p, 7, 14) for v in (1, 8, 9, 65, 1025) for p in (0, 1)]
CASES += [(65, 2, 3, 60), (9, 0, 0, 0), (0, 0, 0, 0)]


def transactions(text: str) -> list[int]:
    # Vitis calls this file .xml, but writes a plain-text transaction table.
    rows = re.findall(r"^transaction\s+(\d+):\s+(\d+)\s+(\d+|x)\s*$", text, re.M)
    if (len(rows) != len(CASES) or [int(row[0]) for row in rows] != list(range(len(CASES)))
            or len(re.findall(r"^transaction", text, re.M)) != len(CASES)
            or any(int(row[1]) <= 0 for row in rows)):
        raise ValueError("all thirteen ordered RTL transaction latencies required")
    return [int(row[1]) for row in rows]


def check_trace(text: str) -> None:
    rows = re.findall(r"^PMA_COSIM_CASE vertices=(\d+) placement=(\d+) length=(\d+) "
                      r"packets=(\d+) status=PASS$", text, re.M)
    observed = [tuple(map(int, row)) for row in rows]
    groups, remainder = divmod(len(observed), len(CASES))
    if (groups < 2 or remainder or observed != CASES * groups
            or len(re.findall(r"^PMA_COSIM_CASE ", text, re.M)) != len(observed)
            or text.count("PMA_COSIM_RESULT status=PASS cases=13 packets=200") != groups
            or re.search(r"\b(?:ERROR|FATAL|FAIL)\b", text)):
        raise ValueError("complete matching C/RTL packet checks required")


def analyze(directory: Path) -> dict:
    solution = directory / "project/solution"
    check_trace((directory / "cosim.stdout.txt").read_text())
    summary = parse_cosim_report(solution / "sim/report/pma_to_regraph_adapter_cosim.rpt")
    table = solution / "sim/verilog/pma_to_regraph_adapter.performance.result.transaction.xml"
    latencies = transactions(table.read_text())
    if (min(latencies) != summary["latency_min_cycles"]
            or max(latencies) != summary["latency_max_cycles"]):
        raise ValueError("summary and per-call latencies differ")
    report = solution / "syn/report/pma_to_regraph_adapter_csynth.xml"
    tree = ET.parse(report).getroot()
    resources = tree.find("AreaEstimates/Resources")
    if resources is None:
        raise ValueError("HLS resource report missing")
    return {"cosim": summary, "transaction_table": identity(table),
            "hls_report": identity(report),
            "resources": {item.tag: int(item.text) for item in resources},
            "estimated_clock_ns": float(tree.findtext(
                "PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod")),
            "cases": [{"vertices": v, "placement": p, "length": n,
                       "packets": packets, "rtl_cycles": latency}
                      for (v, p, n, packets), latency in zip(CASES, latencies, strict=True)]}
