"""Read routed timing and normalized XRT topology before board admission."""

import json
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .execution import identity


SECTIONS = {"CLOCK_FREQ_TOPOLOGY": "clock", "MEM_TOPOLOGY": "memory",
            "CONNECTIVITY": "connectivity", "IP_LAYOUT": "ip"}


def normalized_topology(sections: dict) -> dict:
    clocks = sections["clock"]["clock_freq_topology"]
    memory = sections["memory"]["mem_topology"]
    ip = sections["ip"]["ip_layout"]
    connectivity = sections["connectivity"]["connectivity"]
    for table, field in ((clocks, "m_clock_freq"), (memory, "m_mem_data"),
                         (ip, "m_ip_data"), (connectivity, "m_connection")):
        if int(table["m_count"]) != len(table[field]):
            raise ValueError("XRT section count differs from entries")
    mem = memory["m_mem_data"]
    ips = ip["m_ip_data"]
    kernels = [(row["m_name"], row["m_ip_control"])
               for row in ips if row["m_type"] == "IP_KERNEL"]
    if len({name for name, _ in kernels}) != len(kernels):
        raise ValueError("duplicate kernel instance")
    connections = []
    for row in connectivity["m_connection"]:
        instance = ips[int(row["m_ip_layout_index"])]["m_name"]
        region = mem[int(row["mem_data_index"])]["m_tag"]
        connections.append((instance, int(row["arg_index"]), region))
    return {"clock": sorted((row["m_type"], row["m_name"], int(row["m_freq_Mhz"]))
                            for row in clocks["m_clock_freq"]),
            "kernels": sorted(kernels),
            "memory": sorted((row["m_tag"], row["m_type"], row["m_used"], row.get("m_sizeKB", "0"))
                             for row in mem),
            "connections": sorted(connections)}


def parse_routed_timing(path: Path) -> dict:
    lines = path.read_text().splitlines()
    headings = [index for index, line in enumerate(lines) if line.strip().startswith("WNS(ns)")]
    if len(headings) != 1:
        raise ValueError("one design timing summary required")
    values = lines[headings[0] + 2].split()
    if len(values) != 12:
        raise ValueError("unexpected Vivado design timing columns")
    for index in (0, 4, 8):
        if float(values[index]) < 0 or float(values[index + 1]) != 0 or int(values[index + 2]) != 0:
            raise ValueError("setup, hold or pulse-width timing failed")
    if "All user specified timing constraints are met." not in lines:
        raise ValueError("Vivado has not admitted routed timing")
    return {"wns_ns": float(values[0]), "whs_ns": float(values[4]),
            "wpws_ns": float(values[8]), "report": identity(path)}


def _dump(binary: Path, output: Path) -> dict:
    output.mkdir()
    command = ["/opt/xilinx/xrt/bin/xclbinutil", "--input", str(binary)]
    for section, name in SECTIONS.items():
        command += ["--dump-section", f"{section}:JSON:{output / (name + '.json')}"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (output / "xclbinutil.stdout.txt").write_text(result.stdout)
    (output / "xclbinutil.stderr.txt").write_text(result.stderr)
    if result.returncode:
        raise RuntimeError("xclbin topology extraction failed; raw logs retained")
    return {name: json.loads((output / (name + ".json")).read_text()) for name in SECTIONS.values()}


def admit_bitstream(route: Path, original: Path, output: Path) -> dict:
    summary = json.loads((route / "summary.json").read_text())
    if summary["status"] != "LINK_PASS_AWAITING_TIMING_AND_BOARD":
        raise ValueError("link must pass before routed admission")
    candidate = Path(summary["xclbin"]["path"])
    if identity(candidate) != summary["xclbin"]:
        raise ValueError("candidate changed after link")
    manifest = json.loads((route / "manifest.json").read_text())
    pins = manifest["pins"] + [identity(original)]
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("link inputs changed")
    output.mkdir(parents=True, exist_ok=False)
    old = normalized_topology(_dump(original, output / "original"))
    new = normalized_topology(_dump(candidate, output / "candidate"))
    if old != new or ("DATA", "DATA_CLK", 150) not in new["clock"]:
        raise ValueError("candidate clock, kernel budget or connectivity differs")
    reports = list((route / "reports").glob("**/impl_1_hw_bb_locked_timing_summary_routed.rpt"))
    if len(reports) != 1:
        raise ValueError("one final routed timing report required")
    timing = parse_routed_timing(reports[0])
    unchanged = all(identity(Path(pin["path"])) == pin for pin in pins)
    if not unchanged:
        raise ValueError("admission inputs changed during extraction")
    result = {"status": "ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD",
              "original": identity(original), "candidate": identity(candidate),
              "clock_topology_connectivity_equal": True, "timing": timing,
              "topology": new, "pins": pins,
              "claim": "routed_metadata_and_timing_not_board_correctness_or_speedup"}
    atomic_write_json(output / "summary.json", result)
    return result
