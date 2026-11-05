from hashlib import sha256
from pathlib import Path

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import cc_au_collect


ROOT = Path("/data/chuxiao/cc-build")
UNIT = "cc-build.service"
INVOCATION = "a" * 32
ABI = "b" * 64


@pytest.fixture
def journal():
    common = dict(USER_UNIT=UNIT, USER_INVOCATION_ID=INVOCATION, _BOOT_ID="boot",
                  _SYSTEMD_USER_UNIT="init.scope", _EXE="/usr/lib/systemd/systemd")
    return [
        dict(common, MESSAGE_ID=cc_au_collect.START, __MONOTONIC_TIMESTAMP="10",
             MESSAGE=f'Started {UNIT} - /bin/bash -c "\\n    root={ROOT}\\n    exec make\\n".'),
        dict(common, MESSAGE_ID=cc_au_collect.TEARDOWN, __MONOTONIC_TIMESTAMP="20"),
    ]


def test_retired_checks_exact_journal(journal):
    cc_au_collect.retired(journal, UNIT, INVOCATION, ROOT)
    with pytest.raises(ValueError, match="different launch"):
        cc_au_collect.retired(journal, UNIT, INVOCATION, ROOT / "different")


@pytest.mark.parametrize("mutation", [
    {"USER_INVOCATION_ID": "different"}, {"JOB_TYPE": "stop"}, {"JOB_RESULT": "timeout"},
    {"EXIT_STATUS": "1"}, {"_EXE": "/usr/bin/bash"},
])
def test_retired_rejects_dirty_teardown(journal, mutation):
    journal[1].update(mutation)
    with pytest.raises(ValueError, match="clean exact-invocation"):
        cc_au_collect.retired(journal, UNIT, INVOCATION, ROOT)


@pytest.fixture
def route():
    hook = ROOT / "temp/vivado/bus_skew_routed.rpt"
    files = {
        cc_au_collect.IMAGE + ".weighted-manifest": f"build_sha256 {ABI}\n",
        "build.log": f"g++ -DSPINE_WEIGHTED_BUILD_SHA256='\"{ABI}\"'\ncheck.py --expected {ABI}\n",
    }

    def content(path):
        return files.get(path.name, f"sample {path.name}\n")

    def command(argv, *, timeout=40):
        if argv[0] == "find":
            return str(hook) + "\n"
        assert argv[:2] == ["sha256sum", "--"]
        return "".join(f"{sha256(content(path).encode()).hexdigest()}  {path}\n" for path in argv[2:])

    def transfer(paths, output):
        for path in paths:
            (output / path.name).write_text(content(path))

    return command, transfer


def test_collect_pins_all_files_and_expected_abi(route, tmp_path):
    candidate = cc_au_collect.collect(*route, ROOT, tmp_path / "valid", ABI)
    assert candidate["abi"] == ABI
    assert candidate["linked_image"] == str(ROOT / "xclbin" / cc_au_collect.IMAGE)
    assert len(candidate["build"]["sha256"]) == 64
    with pytest.raises(ValueError, match="frozen source"):
        cc_au_collect.collect(*route, ROOT, tmp_path / "wrong-abi", "c" * 64)


def test_collect_rejects_files_modified_in_transit(route, tmp_path):
    command, transfer = route

    def modified(paths, output):
        transfer(paths, output)
        (output / "build.log").write_text("different build log\n")

    with pytest.raises(ValueError, match="changed during transfer"):
        cc_au_collect.collect(command, modified, ROOT, tmp_path / "tampered", ABI)
