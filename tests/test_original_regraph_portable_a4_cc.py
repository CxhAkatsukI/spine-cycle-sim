"""Protect the author CC control against source or command drift in transit."""

import json
from pathlib import Path

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_build import (
    configuration, portable_inputs as portable, portable_return as returned,
)
from test_grasu_continuous_supervisor import INVOCATION, state


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


def test_retry_only_adds_reviewed_implementation_properties(tmp_path):
    args = (tmp_path / "source", tmp_path / "build", configuration.COMPILER, configuration.PLATFORM)
    original = portable.commands(*args)
    retry = portable.commands(*args, timing_profile=portable.timing.PROFILE)
    assert retry["compilations"] == original["compilations"]
    link = retry["link"]
    start = link.index("--vivado.prop")
    stop = link.index("--vivado.synth.jobs")
    assert link[start:stop:2] == ["--vivado.prop"] * len(portable.timing.PROPERTIES)
    assert tuple(link[start + 1:stop:2]) == portable.timing.PROPERTIES
    assert link[:start] + link[stop:] == original["link"]
    with pytest.raises(ValueError, match="unknown physical timing profile"):
        portable.commands(*args, timing_profile="unreviewed")


@pytest.mark.parametrize("profile", [None, portable.timing.PROFILE])
def test_terminal_public_cc_return_replays_and_detects_tampering(frozen, tmp_path, monkeypatch, profile):
    prior, platform, _, shim = frozen
    root, attempt, output = [tmp_path / name for name in ("portable", "build", "returned")]
    portable.prepare(prior, root, shim)
    capsule = artifact.identity(root / "capsule.json")
    policy = returned.memory_profiles.select(returned.capsule.POLICY, returned.memory_profiles.SEELE)
    resources = dict(exit_code=0, stop_reason="process_exit", cleanup_snapshot_error=None,
                     tree_memory_gib=40, reserve_gib=128, minimum_available_bytes=129 * 2**30)
    plan = dict(configuration="a4", algorithm="cc", clock_mhz=150,
                commands=portable.commands(root / "source", attempt, configuration.COMPILER, platform,
                                           timing_profile=profile))
    if profile is not None:
        plan["timing_profile"] = profile
    manifest = write(attempt, "manifest.json", json.dumps(plan))
    image = write(attempt, returned.BINARY, "unprogrammed test fixture")
    write(attempt, "environment.json", json.dumps({"tools": {"v++": {"invocation": str(configuration.COMPILER)}}}))
    write(attempt, "preflight/results.json", json.dumps(dict(status="PREFLIGHT_PASS_NOT_ROUTED",
        commands=[dict(label=label, **resources) for label in returned.delivery.LABELS])))
    xos = [{"abi": {"kernel": name, "xo": artifact.identity(write(attempt, f"xo/{name}.hw.xo", name))},
            "hls": {"report": artifact.identity(write(attempt, f"compile/{name}/syn/{name}_csynth.xml", name))}}
           for name in returned.NAMES]
    result = dict(status=returned.portable_execution.STATUS, errors=[], host="seele", board_programmed=False,
                  policy=policy, memory_profile=returned.memory_profiles.SEELE, xos=xos,
                  admission={"admitted": True, "policy": returned.memory_profiles.SEELE,
                             "observed_peer_host": {"host": "seele", "total_memory_bytes": 502 * 2**30}},
                  steps=[dict(id=name, **resources) for name in
                         [*("compile_" + name for name in returned.NAMES), "route"]],
                  capsule=capsule, manifest=artifact.identity(manifest), xclbin=artifact.identity(image),
                  pins=[capsule], memory_events_after="oom 0\noom_kill 0\noom_group_kill 0\n")
    write(attempt, "results.json", json.dumps(result))
    for name in returned.members(result, attempt):
        if not (attempt / name).exists():
            write(attempt, name, "log")
    write(attempt, "link/reports/imp/impl_1_hw_bb_locked_timing_summary_routed.rpt", "timing")
    if profile:
        write(attempt, "link/reports/imp/" + portable.timing.PHYSOPT_REPORT, "postroute timing")
    monkeypatch.setattr(returned.socket, "gethostname", lambda: "seele")
    monkeypatch.setattr(returned.terminal_link, "service_state", lambda _: state("active"))
    with pytest.raises(ValueError, match="still running"):
        returned.seal(root, attempt, output, "cc.service", INVOCATION, capsule["sha256"])
    monkeypatch.setattr(returned.terminal_link, "service_state", lambda _: state())
    digest = returned.seal(root, attempt, output, "cc.service", INVOCATION, capsule["sha256"])
    assert returned.verify(output, digest, root)[1] == result
    assert (output / returned.TIMING_MEMBER).read_text() == ("postroute timing" if profile else "timing")
    write(output, returned.BINARY, "changed")
    with pytest.raises(ValueError, match="receipt or payload"):
        returned.verify(output, digest, root)
