"""Compile the frozen search candidate, not a routed/integrated G bitstream."""

import argparse
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from ..study import ROOT


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"; source.mkdir()
    for name in ("parallel_search.cpp", "parallel_search.hpp"):
        shutil.copy2(ROOT / "cpp/tests/evaluation_impact/common_g/hls" / name, source / name)
    pins = [{"path": str(p), "sha256": sha256_file(p)} for p in sorted(source.iterdir())]
    command = ["/data/yxx/tools/xilinx/Vitis/2024.1/bin/v++", "--target", "hw", "--compile",
        "--kernel_frequency", "200", "--kernel", "bin_search_parallel", "--platform",
        "/opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm",
        "--save-temps", "-D_GTHREAD_USE_COND_INIT_FUNC",
        "-I/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include/etc",
        "--temp_dir", str(output / "build"), "--report_dir", str(output / "reports"),
        "--log_dir", str(output / "logs"), "-o", str(output / "search.hw.xo"),
        str(source / "parallel_search.cpp")]
    result = {"status": "RUNNING", "source": pins, "command": command,
        "claim": "isolated_search_HLS_schedule_not_routed_G_performance",
        "hardware_timing_admitted": False, "production_baseline_admitted": False}
    atomic_write_json(output / "results.json", result)
    try:
        result["execution"] = run_bounded(command, output, output / "compile", timeout=900,
            memory_gib=8, reserve_gib=24)
        if result["execution"]["exit_code"] or result["execution"]["timed_out"]:
            raise ValueError("isolated search synthesis failed; raw attempt retained")
        reports = sorted(output.glob("build/**/syn/report/*csynth.xml"))
        if not reports:
            raise ValueError("missing structured synthesis reports")
        result["reports"] = []
        for path in reports:
            tree = ET.parse(path).getroot()
            result["reports"].append({"path": str(path), "sha256": sha256_file(path),
                "resources": {child.tag: child.text for child in tree.findall("AreaEstimates/Resources/*")},
                "clock_ns": tree.findtext("PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod"),
                "loops": [{"name": loop.tag, **{child.tag: child.text for child in loop}}
                          for loop in tree.findall(".//SummaryOfLoopLatency/*")]})
        if any(sha256_file(Path(pin["path"])) != pin["sha256"] for pin in pins):
            raise ValueError("frozen HLS source changed")
        result["xo_sha256"] = sha256_file(output / "search.hw.xo")
        result["status"] = "SYNTHESIZED_REQUIRES_SCHEDULE_REVIEW_AND_RTL_VALIDATION"
    except BaseException as error:
        result["status"] = "FAILED_RETAINED"; result["error"] = repr(error)
        atomic_write_json(output / "results.json", result); raise
    atomic_write_json(output / "results.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
