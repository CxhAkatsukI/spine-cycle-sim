import json
import zipfile

import pytest

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import (
    replacement_capsule as relocation, replacement_return,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    banked_clear_link,
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
           for name in ["pma_to_regraph_adapter", "lksg_stream", *[f"kernel{i}" for i in range(9)]]]
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


@pytest.mark.parametrize(("profile", "mode"), [
    (banked_clear_link.CC, "destination"),
    (banked_clear_link.SSSP, "weighted"),
])
def test_banked_clear_changes_only_the_fixed_frame_gather(tmp_path, profile, mode):
    manifest, platform = source(tmp_path)
    original = json.loads(manifest.read_text())
    old_xo = tmp_path / "xos/lksg_stream.hw.xo"
    new_xo = tmp_path / "banked/lksg_stream.hw.xo"
    new_xo.parent.mkdir()

    def write_xo(path, rtl, *, offset="0x28", flags=""):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("lksg_stream/kernel.xml",
                             '<root><kernel name="lksg_stream" vlnv="v" hwControlProtocol="ap_ctrl_chain"'
                             f' compileOptions="{flags}">'
                             '<ports><port name="control"/></ports>'
                             f'<args><arg name="reset_tmp_prop" offset="{offset}"/></args>'
                             '</kernel></root>')
            archive.writestr("rtl", rtl)

    common = "-DGRASU_REGRAPH_PREFETCH_COMPACT=1"
    banked = f"{common} -D{banked_clear_link.BANKED_CLEAR}=1"
    write_xo(old_xo, "original", flags=common)
    write_xo(new_xo, "banked", flags=banked)
    original["mode"] = mode
    original["pins"] = [identity(old_xo) if row["path"] == str(old_xo) else row
                        for row in original["pins"]]
    manifest.write_text(json.dumps(original))
    old_manifest = identity(manifest)

    def derive(output):
        return banked_clear_link.derive(manifest, new_xo, output, profile=profile,
                                        parent_sha256=old_manifest["sha256"],
                                        gather_sha256=identity(new_xo)["sha256"])

    output = tmp_path / "derived"
    derived = derive(output)
    assert derived["gather_replacement"] == {"parent": old_manifest, "before": identity(old_xo),
                                             "after": identity(new_xo)}
    expected = [str(new_xo) if arg == str(old_xo) else arg for arg in original["command"]]
    expected[expected.index("-o") + 1] = str(output / "candidate.hw.xclbin")
    assert derived["command"] == expected
    assert identity(manifest) == old_manifest
    capsule = tmp_path / "capsule"
    relocation.prepare(output, capsule)
    relocation.verify(capsule, platform)
    write_xo(new_xo, "incompatible", offset="0x2c")
    with pytest.raises(ValueError, match="ABI-compatible"):
        derive(tmp_path / "rejected")
    if profile == banked_clear_link.SSSP:
        write_xo(new_xo, "unrelated change", flags=f"{banked} -DGRASU_EXTRA=1")
        with pytest.raises(ValueError, match="only the SSSP banked clear compile flag"):
            derive(tmp_path / "rejected-flag")


def test_lazy_respr_preserves_tail_abi_and_pinned_cache(tmp_path):
    manifest, platform = source(tmp_path)
    original = json.loads(manifest.read_text())
    old_xo = tmp_path / "xos/lksg_stream.hw.xo"
    new_xo = tmp_path / "lazy/lksg_stream.hw.xo"
    new_xo.parent.mkdir()
    tail = "-DGRASU_REGRAPH_TAIL_PUBLICATION=1"
    lazy = "-DGRASU_REGRAPH_LAZY_GATHER_CLEAR=1"

    def write_xo(path, flags):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("lksg_stream/kernel.xml",
                             '<root><kernel name="lksg_stream" vlnv="v" hwControlProtocol="ap_ctrl_chain"'
                             f' compileOptions="{flags}"><ports><port name="control"/></ports>'
                             '<args><arg name="publication_rows" id="5" offset="0x30"/></args>'
                             '</kernel></root>')

    write_xo(old_xo, tail)
    write_xo(new_xo, f"{tail} {lazy}")
    extra = old_xo.with_name("prefetch.hw.xo")
    extra.write_text("prefetch")
    cache = manifest.parent / "ip_cache"
    cache.mkdir()
    checkpoint = cache / "reuse.dcp"
    checkpoint.write_text("checkpoint")
    seed = manifest.with_name("ip-cache-seed.json")
    seed.write_text(json.dumps({"files": [
        {"relative": checkpoint.name, "sha256": identity(checkpoint)["sha256"]}]}))
    original.pop("mode")
    original["ip_cache_seed"] = identity(seed)
    original["command"].append(str(extra))
    original["pins"] = [identity(old_xo) if pin["path"] == str(old_xo) else pin
                        for pin in original["pins"]] + [identity(extra), identity(seed)]
    manifest.write_text(json.dumps(original))

    def derive(output):
        return banked_clear_link.derive(manifest, new_xo, output, profile=banked_clear_link.RESPR,
                                        parent_sha256=identity(manifest)["sha256"],
                                        gather_sha256=identity(new_xo)["sha256"])

    output = tmp_path / "derived"
    result = derive(output)
    assert result["gather_replacement"]["after"] == identity(new_xo)
    assert str(extra) in result["command"]
    assert not (output / "ip_cache" / checkpoint.name).samefile(checkpoint)
    packet = relocation.prepare(output, tmp_path / "capsule")
    assert packet["cache_files"] == {checkpoint.name: identity(checkpoint)["sha256"]}
    write_xo(new_xo, f"{tail} {lazy} -DGRASU_EXTRA=1")
    with pytest.raises(ValueError, match="only the ResPR packed validity compile flag"):
        derive(tmp_path / "rejected")


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
