"""Capture unmodified author partitioning without changing the fixed common IDs."""

from array import array
from pathlib import Path
import sys

from ...original_regraph_inputs.analysis import analyze_topology
from ...original_regraph_inputs.preparation import compiler_command, inspect_graph

CAPTURES = ("original_to_reordered.u32le", "csr_offsets.u32le", "csr_destinations.u32le",
            "initial.u32le", "degrees.u32le", "partitions.u32le", "tasks.u32le")


def layout_command(root, prepared, output, compiler, xrt_include):
    command = compiler_command(root, prepared, {"little": 4, "big": 0}, output,
                               str(compiler), xrt_include)
    old = str(root / "cpp/tests/publication_sources/regraph_layout_probe.cpp")
    command[command.index(old)] = str(root / "cpp/tests/evaluation_impact/warm_comparison/fixed_id_layout.cpp")
    return command


def describe_layout(step, directory, graph):
    analysis = analyze_topology(Path(step["stdout"]).read_text(), directory,
        {"little": 4, "big": 0}, inspect_graph(graph), {"seed": 0, "capture_files": CAPTURES})
    summary = analysis["summary"]
    words = [0x3447524F, 1, summary["vertices"], summary["logical_edges"],
             summary["aligned_vertices"], summary["partitions"] * 65536,
             len(analysis["tasks"]), summary["partitions"]]
    for task in analysis["tasks"]:
        words += [task["partition"], task["subpartition"], task["kernel"], task["dst_offset"],
                  task["dst_len"], task["offset_words"], task["words"], 0]
    payload = array("I", words)
    if sys.byteorder != "little":
        payload.byteswap()
    with (directory / "execution.u32le").open("xb") as stream:
        payload.tofile(stream)
    return analysis
