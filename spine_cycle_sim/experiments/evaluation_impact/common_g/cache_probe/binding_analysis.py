"""Keep cache wrapper state, RTL, ABI and estimated clock as separate gates."""

import math
import re
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..search_binding.abi import exported_members
from .analysis import transactions
from .binding_abi import compare


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
        root = ET.fromstring(record(solution / "syn/report/process_cache_csynth.xml"))
        clock = float(root.findtext("PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod"))
        if not math.isfinite(clock) or clock <= 0:
            raise ValueError("invalid clock estimate")
        result.update(top_clock_ns=clock, target_5ns_met=clock <= 5,
                      top_resources={child.tag: child.text for child in root.findall("AreaEstimates/Resources/*")})
    except (OSError, ValueError, TypeError, ET.ParseError) as error:
        result["errors"]["synthesis"] = repr(error)
    try:
        contents = record(solution / "csim/report/process_cache_csim.log")
        calls = re.findall(r"^CACHE_FULL_PASS updates=(\d+) conflict=([01])$", contents, re.M)
        if calls != [(str(count), str(conflict)) for count, conflict in
                     ((0, 0), (16, 0), (64, 0), (4096, 0), (65536, 0), (4096, 1))]:
            raise ValueError("incomplete production cache state/token test scope")
        result.update(csim_pass=True, state_control_calls=6)
    except (OSError, ValueError) as error:
        result["errors"]["csim"] = repr(error)
    try:
        cosim = record(solution / "sim/report/process_cache_cosim.rpt")
        if not re.search(r"Verilog\s*\|\s*Pass\s*\|", cosim):
            raise ValueError("cache wrapper RTL did not pass")
        rows = transactions(record(solution / "sim/report/verilog/result.transaction.rpt"),
                            full=True, full_extended=True)
        result.update(transactions=rows, rtl_pass=True)
    except (OSError, ValueError) as error:
        result["errors"]["rtl"] = repr(error)
    try:
        xo = attempt / "process_cache.hw.xo"
        result["artifacts"].append({"path": str(xo), "sha256": sha256_file(xo)})
        with ZipFile(xo) as archive:
            members = exported_members(archive, "process_cache")
            result["abi"] = compare(archive.read(members["kernel.xml"]), archive.read(members["component.xml"]),
                                    record(reference / "kernel.xml"), record(reference / "component.xml"))
            result["exported_abi_members"] = members
        result["abi_pass"] = True
    except (OSError, ValueError, KeyError, ET.ParseError, BadZipFile) as error:
        result["errors"]["abi"] = repr(error)
    return result


def status(analysis):
    if analysis["errors"] or not all(analysis[key] for key in ("csim_pass", "rtl_pass", "abi_pass")):
        return "FAILED_RETAINED"
    return ("CACHE_WRAPPER_RTL_ABI_PASS_TARGET_MET_REQUIRES_INTEGRATION" if analysis["target_5ns_met"]
            else "CACHE_WRAPPER_RTL_ABI_PASS_CLOCK_GATE_FAILED")
