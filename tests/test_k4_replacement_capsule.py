import json

import pytest

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import (
    replacement_capsule as relocation, replacement_return,
)
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity


def source(tmp_path):
    def put(name, contents):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
        return path

    platform = put("platform/u55c.xpfm", "platform")
    put("platform/hw/shell.xsa", "platform dependency")
    config = put("parent/link.cfg", f"platform={platform}\n[connectivity]\n")
    shim = put("packet/gcc_compat/bits/gthr-default.h", "shim")
    xos = [put(f"xos/{name}.hw.xo", name)
           for name in ["pma_to_regraph_adapter", *[f"kernel{i}" for i in range(10)]]]
    argv = ["v++", "--link", "--target", "hw", "--kernel_frequency", "150", "--config", str(config),
            "-o", str(tmp_path / "parent/candidate.hw.xclbin"), *map(str, xos),
            "--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]
    manifest = put("parent/manifest.json", json.dumps({"command": argv, "board_tested": False,
        "mode": "weighted", "status": "PREPARED_NOT_ROUTED", "clock_mhz": 150, "timeout_seconds": 21600,
        "packet": str(tmp_path / "packet"), "pins": list(map(identity, [config, shim, *xos]))}))
    return manifest, platform


def test_exact_relocation_and_platform_closure(tmp_path):
    manifest, platform = source(tmp_path)
    output = tmp_path / "relocated"
    packet = relocation.prepare(manifest.parent, output)
    assert packet["parent"] == identity(manifest)
    assert relocation.verify(output, platform)[0] == packet
    (platform.parent / "hw/shell.xsa").write_text("different shell")
    with pytest.raises(ValueError, match="platform"):
        relocation.verify(output, platform)


def test_modified_xo_is_rejected(tmp_path):
    manifest, platform = source(tmp_path)
    output = tmp_path / "relocated"
    relocation.prepare(manifest.parent, output)
    (output / "inputs/kernel0.hw.xo").write_text("substitution")
    with pytest.raises(ValueError, match="modified capsule member"):
        relocation.verify(output, platform)


def test_physical_strategy_is_pinned_to_a_separate_replacement_capsule(tmp_path, monkeypatch):
    manifest, platform = source(tmp_path)
    original = relocation.prepare(manifest.parent, tmp_path / "original")
    returned = tmp_path / "returned"
    local = tmp_path / "physical"
    profile = relocation.timing.PROFILE
    packet = relocation.prepare(manifest.parent, local, timing_profile=profile)
    relocation.prepare(manifest.parent, returned / "capsule", timing_profile=profile)
    assert relocation.verify(local, platform)[0] == packet
    assert packet == {**original, "timing_profile": profile}
    monkeypatch.setattr(replacement_return.delivery, "verify",
                        lambda *_args, **_kwargs: ({}, packet, {}))
    monkeypatch.setattr(replacement_return.admission, "verify_link",
                        lambda *_args: ({}, []))
    with pytest.raises(ValueError, match="pinned replacement capsule"):
        replacement_return.verify(returned, local, platform, "digest")
    monkeypatch.setattr(replacement_return.admission, "verify_link",
                        lambda *_args: ({"timing_profile": profile}, []))
    replacement_return.verify(returned, local, platform, "digest")


def test_board_result_cannot_be_exported_as_source_input(tmp_path):
    manifest, _ = source(tmp_path)
    parent = json.loads(manifest.read_text())
    parent["board_tested"] = True
    with pytest.raises(ValueError, match="not board evidence"):
        relocation.layout(parent)


def test_replacement_return_needs_same_local_capsule(tmp_path, monkeypatch):
    manifest, platform = source(tmp_path)
    local = tmp_path / "local"
    returned = tmp_path / "returned"
    packet = relocation.prepare(manifest.parent, local)
    relocation.prepare(manifest.parent, returned / "capsule")
    (local / "capsule.json").write_text("different export")
    monkeypatch.setattr(replacement_return.delivery, "verify", lambda *_args, **_kwargs: ({}, packet, {}))
    with pytest.raises(ValueError, match="locally exported capsule"):
        replacement_return.verify(returned, local, platform, "digest")


def test_failed_remote_invocation_never_seals(tmp_path):
    class Remote:
        invocation = "a" * 32

        def state(self):
            return {"InvocationID": self.invocation, "LoadState": "loaded", "ActiveState": "failed",
                    "SubState": "failed"}

        def seal(self, **_kwargs):
            pytest.fail("must not seal a failed remote invocation")

    with pytest.raises(ValueError, match="terminated unsuccessfully"):
        replacement_return.collect(Remote(), None, None, None, tmp_path / "collect", wait_seconds=1)
    report = json.loads((tmp_path / "collect/transfer.json").read_text())
    assert report["status"] == "FAILED_RETAINED"
    assert "candidate" not in report
