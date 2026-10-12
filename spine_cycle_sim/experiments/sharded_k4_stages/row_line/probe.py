"""Execute the complete production adapter RTL against the existing AXI bench."""

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ..adapter_axi.analysis import parse_trace
from ..adapter_axi.study import BENCH, extract_rtl, require_execution
from ..execution import identity
from ..link_runtime import run_link


def probe(root: Path, xo: Path, output: Path, vivado_bin: Path, *, bench=BENCH, trials=None) -> list[dict]:
    output.mkdir()
    rtl = extract_rtl(xo, output)
    shutil.copyfile(root / bench, output / Path(bench).name)
    included = []
    if bench != BENCH:
        shutil.copyfile(root / BENCH, output / Path(BENCH).name)
        included = [root / BENCH, output / Path(BENCH).name]
    (output / "run.tcl").write_text("run all\nquit\n")
    pins = [identity(path) for path in (xo, root / bench, *rtl, *included,
            output / Path(bench).name, output / "run.tcl")]
    atomic_write_json(output / "inputs.json", pins)
    commands = {
        "compile": [str(vivado_bin / "xvlog"), "--sv", Path(bench).name]
                   + [path.name for path in rtl if path.suffix == ".v"],
        "elaborate": [str(vivado_bin / "xelab"), "adapter_axi_tb", "-s", "adapter_axi"],
        "simulate": [str(vivado_bin / "xsim"), "adapter_axi", "-tclbatch", "run.tcl"],
    }
    for step, command in commands.items():
        if any(identity(Path(pin["path"])) != pin for pin in pins):
            raise ValueError("production RTL inputs changed")
        record = run_link(command, output, output / step, timeout=120,
                          tree_memory_gib=4, reserve_gib=16, poll_seconds=0.5)
        require_execution(record)
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("production RTL inputs changed during execution")
    return parse_trace((output / "simulate.stdout.txt").read_text(), trials)
