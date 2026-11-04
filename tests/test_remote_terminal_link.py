"""Keep the remote route return strict when systemd unloads a transient unit."""

import pytest

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import terminal_link

UNIT = "route.service"
INVOCATION = "1" * 32
ATTEMPT = "/tmp/route-attempt"


def state():
    common = dict(USER_UNIT=UNIT, USER_INVOCATION_ID=INVOCATION,
                  _SYSTEMD_USER_UNIT="init.scope", _EXE="/usr/lib/systemd/systemd", _BOOT_ID="boot")
    start = {**common, "MESSAGE_ID": "39f53479d3a045ac8e11786248231fbf",
             "__MONOTONIC_TIMESTAMP": "11", "MESSAGE": f"Started {UNIT} - runner --output {ATTEMPT}."}
    end = {**common, "MESSAGE_ID": "ae8f7b866b0347b9af31fe1c80b127c0", "__MONOTONIC_TIMESTAMP": "22"}
    return dict(LoadState="not-found", ActiveState="inactive", SubState="dead", InvocationID="",
                terminal_journal=[start, end])


def test_unloaded_recovery_requires_the_exact_attempt():
    assert terminal_link.terminal(state(), UNIT, INVOCATION, ATTEMPT)
    with pytest.raises(ValueError, match="different link attempt"):
        terminal_link.terminal(state(), UNIT, INVOCATION, "/tmp/other")


@pytest.mark.parametrize("change", [
    {"USER_INVOCATION_ID": "2" * 32},
    {"_SYSTEMD_USER_UNIT": UNIT},
    {"_BOOT_ID": "old"},
    {"__MONOTONIC_TIMESTAMP": "10"},
    {"EXIT_STATUS": "1"},
    {"UNIT_RESULT": "oom-kill"},
])
def test_unloaded_recovery_refuses_mismatched_or_failed_exit(change):
    receipt = state()
    receipt["terminal_journal"][1].update(change)
    with pytest.raises(ValueError):
        terminal_link.terminal(receipt, UNIT, INVOCATION, ATTEMPT)


def test_unloaded_unit_without_manager_teardown_is_not_a_completed_link():
    receipt = state()
    receipt["terminal_journal"].pop()
    with pytest.raises(ValueError, match="start and teardown"):
        terminal_link.terminal(receipt, UNIT, INVOCATION, ATTEMPT)
