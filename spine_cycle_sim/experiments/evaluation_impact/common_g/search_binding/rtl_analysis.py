"""Keep wrapper functionality, exported ABI and clock feasibility separate."""

import math
import hashlib
import re
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..search_pipeline.rtl_analysis import COUNTS, parse_bench, transactions
from .abi import compare, exported_members

ROW = re.compile(r"^SEARCH_BINDING_RTL_ROW generation=(\d+) updates=(\d+)$", re.M)


def bench(contents):
    result = parse_bench(contents)
    expected = [(generation, count) for count in COUNTS for generation in range(2)]
    if [tuple(map(int, match)) for match in ROW.findall(contents)] != expected:
        raise ValueError("incomplete metadata-refresh testbench scope")
    return {**result, "metadata_generations": 2, "pointer_storage_reused": True}


def analyze(attempt, reference):
    solution = attempt / "project/solution"
    result = {"errors": {}, "artifacts": [], "csim_pass": False, "rtl_pass": False,
              "abi_pass": False, "target_5ns_met": False,
              "external_RTL_backpressure_tested": False, "integrated_g_admitted": False,
              "hardware_timing_admitted": False, "production_baseline_admitted": False,
              "publication_match_admitted": False}

    def record(path):
        result["artifacts"].append({"path": str(path), "sha256": sha256_file(path)})
        return path.read_text()

    try:
        tree = ET.fromstring(record(solution / "syn/report/bin_search_csynth.xml"))
        clock = float(tree.findtext("PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod"))
        if not math.isfinite(clock) or clock <= 0:
            raise ValueError("invalid clock estimate")
        result.update(top_clock_ns=clock, target_5ns_met=clock <= 5,
                      top_resources={child.tag: child.text for child in tree.findall("AreaEstimates/Resources/*")})
    except (OSError, ValueError, TypeError, ET.ParseError) as error:
        result["errors"]["synthesis"] = repr(error)
    try:
        result["csim"] = bench(record(solution / "csim/report/bin_search_csim.log"))
        result["csim_pass"] = True
    except (OSError, ValueError) as error:
        result["errors"]["csim"] = repr(error)
    try:
        cosim = record(solution / "sim/report/bin_search_cosim.rpt")
        if not re.search(r"Verilog\s*\|\s*Pass\s*\|", cosim):
            raise ValueError("wrapper RTL co-simulation did not pass")
        rows = transactions(record(solution / "sim/report/verilog/result.transaction.rpt"))
        for row in rows:
            row["metadata_generation"] = row["index"] % 2
        result.update(transactions=rows, rtl_pass=True)
    except (OSError, ValueError) as error:
        result["errors"]["rtl"] = repr(error)
    try:
        xo = attempt / "search_binding.xo"
        result["artifacts"].append({"path": str(xo), "sha256": sha256_file(xo)})
        with ZipFile(xo) as archive:
            members = exported_members(archive)
            contents = {name: archive.read(path) for name, path in members.items()}
            result["exported_abi_members"] = [
                {"path": path, "sha256": hashlib.sha256(contents[name]).hexdigest()}
                for name, path in members.items()]
            member = contents.__getitem__
            result["abi"] = compare(member("kernel.xml"), member("component.xml"),
                                    record(reference / "kernel.xml"), record(reference / "component.xml"))
        result["abi_pass"] = True
    except (OSError, ValueError, KeyError, ET.ParseError, BadZipFile) as error:
        result["errors"]["abi"] = repr(error)
    return result


def status(analysis):
    if analysis["errors"] or not all(analysis[key] for key in ("csim_pass", "rtl_pass", "abi_pass")):
        return "FAILED_RETAINED"
    return ("WRAPPER_RTL_ABI_PASS_TARGET_MET_REQUIRES_INTEGRATION" if analysis["target_5ns_met"]
            else "WRAPPER_RTL_ABI_PASS_CLOCK_GATE_FAILED")
