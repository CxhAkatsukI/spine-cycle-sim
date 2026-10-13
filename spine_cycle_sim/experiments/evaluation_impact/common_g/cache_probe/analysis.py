"""Read structured HLS schedules; keep isolated and integrated claims separate."""

from pathlib import Path
import math
import re
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


def transactions(contents: str, *, full=False, full_extended=False):
    pattern = re.compile(r"^transaction\s+(\d+):\s+(\d+)\s+(\d+|x)\s*$")
    rows = []
    lines = contents.splitlines()
    if not lines or lines[0].split() != ["latency", "interval"]:
        raise ValueError("unexpected RTL transaction report header")
    for line in lines[1:]:
        found = pattern.fullmatch(line)
        if not found:
            raise ValueError("unexpected RTL transaction report grammar")
        index, latency, interval = found.groups()
        rows.append({"index": int(index), "latency": int(latency),
                     "interval": None if interval == "x" else int(interval)})
    stimuli = ((16, "all_16_banks"), (64, "finite_FIFO_pressure")) if full else (
        (0, "empty"), (40, "positions_and_full_word_keys"), (64, "same_row"),
        (256, "same_row"), (1024, "same_row"), (1024, "dispersed"))
    if full_extended:
        if not full:
            raise ValueError("extended full-cache stimuli require the full kernel")
        stimuli = ((0, "empty"), (16, "all_16_banks"), (64, "finite_FIFO_pressure"),
                   (4096, "balanced"), (65536, "balanced"), (4096, "single_bank_same_row"))
    if [row["index"] for row in rows] != list(range(len(stimuli))):
        raise ValueError("incomplete RTL transaction scope")
    for row, (updates, pattern) in zip(rows, stimuli):
        row.update(updates=updates, pattern=pattern)
    return rows


def analyze(folder: Path, *, full=False, full_extended=False):
    reports = []
    for path in sorted(folder.glob("project/solution/syn/report/*csynth.xml")):
        tree = ET.parse(path).getroot()
        reports.append({"path": str(path), "sha256": sha256_file(path),
            "clock_ns": tree.findtext("PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod"),
            "resources": {child.tag: child.text for child in tree.findall("AreaEstimates/Resources/*")},
            "loops": [{"name": loop.tag, **{child.tag: child.text for child in loop}}
                      for loop in tree.findall(".//SummaryOfLoopLatency/*")]})
    if not reports:
        raise ValueError("missing structured synthesis report")
    top_name = "cache_full_probe" if full else "cache_bank_probe"
    top = next(r for r in reports if Path(r["path"]).name == top_name + "_csynth.xml")
    cosim = folder / ("project/solution/sim/report/" + top_name + "_cosim.rpt")
    contents = cosim.read_text()
    if not re.search(r"Verilog\s*\|\s*Pass\s*\|", contents):
        raise ValueError("RTL cosimulation did not pass")
    csim = (folder / ("project/solution/csim/report/" + top_name + "_csim.log")).read_text()
    calls = 6 if not full or full_extended else 2
    if csim.count("CACHE_FULL_PASS" if full else "CACHE_BANK_PASS") != calls:
        raise ValueError("incomplete C simulation scope")
    transaction_path = folder / "project/solution/sim/report/verilog/result.transaction.rpt"
    rows = transactions(transaction_path.read_text(), full=full, full_extended=full_extended)
    slope = None if full else (rows[4]["latency"] - rows[2]["latency"]) / (1024 - 64)
    clock = float(top["clock_ns"])
    if not math.isfinite(clock) or clock <= 0:
        raise ValueError("invalid clock estimate")
    return {"reports": reports, "top_clock_ns": clock,
        "target_5ns_met": clock <= 5,
        "top_resources": top["resources"],
        "cosim": {"path": str(cosim), "sha256": sha256_file(cosim), "report": contents},
        "transactions": rows, "same_row_incremental_cycles_per_update": slope,
        "transaction_report": {"path": str(transaction_path), "sha256": sha256_file(transaction_path)},
        "state_control_calls": calls, "complete_bank_segments": 131072 if full else 8192,
        "hardware_timing_admitted": False, "integrated_g_admitted": False,
        "claim": ("sixteen_bank_cache_kernel_with_interface_depth_wrapper_HLS_and_RTL_control"
                  if full else "single_full_depth_URAM_bank_preload_update_writeback_HLS_and_RTL_control")}
