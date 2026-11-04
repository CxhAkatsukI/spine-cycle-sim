"""Protect the author CC control against source or command drift in transit."""

import json
from pathlib import Path

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_build import (
    configuration, portable_inputs as portable,
)


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    xilinx = tmp_path / "xilinx"
    for name in portable.VENDOR_FILES:
        write(xilinx, name, name)
    platform = write(tmp_path, "platform/u55c.xpfm", "platform")
    monkeypatch.setattr(configuration, "COMPILER", xilinx / portable.VENDOR_FILES[0])
    monkeypatch.setattr(configuration, "PLATFORM", platform)
    prior = tmp_path / "prior"
    files = [write(prior, portable.CONNECTIVITY, "sp=kernelApply_1.vertex_prop:HBM[30]\n"),
             write(prior, "algorithm/udf/l2.h", "min label"), write(prior, "entries/apply_interface.tcl", ""),
             *[write(prior, f"entries/{name}.cpp", name) for name in configuration.kernels("a4")]]
    report = dict(status=portable.STATUS, errors=[], algorithm="cc", configuration="a4",
                  placement="author", compiler_launched=False, board_programmed=False,
                  physical_configuration={"config": str(prior / portable.CONNECTIVITY)},
                  pins=[artifact.identity(path) for path in files],
                  commands_not_executed=portable.commands(prior / "source", prior, configuration.COMPILER, platform))
    write(prior, "results.json", json.dumps(report))
    return prior, platform, xilinx, write(tmp_path, "shim", "shim")


def test_frozen_source_and_platform_are_checked(frozen, tmp_path):
    prior, platform, xilinx, shim = frozen
    root = tmp_path / "portable"
    packet = portable.prepare(prior, root, shim)
    digest = artifact.identity(root / "capsule.json")["sha256"]
    assert portable.verify(root, platform, xilinx, digest) == packet
    write(root, "algorithm/udf/l2.h", "different semantics")
    with pytest.raises(ValueError, match="source, platform or reviewed vendor"):
        portable.verify(root, platform, xilinx, digest)


def test_reject_a_changed_author_clock(frozen, tmp_path):
    prior, _, _, shim = frozen
    path = prior / "results.json"
    report = json.loads(path.read_text())
    command = report["commands_not_executed"]["link"]
    command[command.index("--kernel_frequency") + 1] = "125"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="preflight command differs"):
        portable.prepare(prior, tmp_path / "portable", shim)


def test_remote_command_keeps_cu_configuration_and_fixed_clock(tmp_path):
    prior = tmp_path / "prior"
    compiler = tmp_path / "other/Vitis/2024.1/bin/v++"
    platform = Path("/remote/u55c.xpfm")
    plan = portable.commands(prior / "source", prior, compiler, platform)
    for command in [*plan["compilations"].values(), plan["link"]]:
        assert command[0] == str(compiler)
        assert command[command.index("--platform") + 1] == str(platform)
        assert command[command.index("--kernel_frequency") + 1] == "150"
    for command in plan["compilations"].values():
        assert "-DLITTLE_KERNEL_NUM=4" in command
        assert "-DBIG_KERNEL_NUM=0" in command
        assert "-I" + str(compiler.parents[3] / "Vitis_HLS/2024.1/include/etc") in command
