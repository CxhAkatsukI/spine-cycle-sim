from pathlib import Path

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.link_retention import validate


IMAGE = Path("/build/xclbin/engine.hw.xclbin")
TEMP = Path("/build/temp/link")
CACHE = Path("/build/source/.ipcache")
COMMAND = (f"/tools/bin/v++ -l --save-temps --temp_dir {TEMP} "
           f"--remote_ip_cache {CACHE} -o {IMAGE} a.xo b.xo")


def check(plan):
    return validate(plan, image=IMAGE, temp=TEMP, cache=CACHE)


def test_link_retention_checks_actual_link_not_a_global_make_variable():
    result = check("echo 'VPP_FLAGS=--save-temps'\n" + COMMAND)
    assert result["status"] == "LINK_RETENTION_PLAN_PASS_NOT_BUILD_COMPLETION"
    assert result["command"][1] == "-l"
    assert len(result["plan_sha256"]) == 64
    with pytest.raises(ValueError, match="link itself"):
        check("echo 'VPP_FLAGS=--save-temps'\n" + COMMAND.replace("--save-temps", ""))


def test_link_retention_accepts_quoted_paths_and_continuations():
    assert check(COMMAND.replace(str(TEMP), f"'{TEMP}'").replace(" -o", " \\\n -o"))


@pytest.mark.parametrize("plan", [
    "", COMMAND + "\n" + COMMAND,
    "/tools/bin/v++ -c --save-temps a.cpp\n" + COMMAND,
    "echo '" + COMMAND + "'",
    COMMAND.replace("-l", "-c", 1),
])
def test_requires_only_one_link_with_frozen_xos(plan):
    with pytest.raises(ValueError, match="exactly one Vitis link"):
        check(plan)


@pytest.mark.parametrize("flag,value", [
    ("-o", IMAGE), ("--temp_dir", TEMP), ("--remote_ip_cache", CACHE),
])
def test_rejects_missing_different_or_duplicate_paths(flag, value):
    for plan in (COMMAND.replace(f"{flag} {value}", ""),
                 COMMAND.replace(str(value), "/different"),
                 COMMAND + f" {flag} {value}"):
        with pytest.raises(ValueError, match="link"):
            check(plan)
