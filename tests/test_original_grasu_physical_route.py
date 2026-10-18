"""Fail-closed continuation contracts, not physical-route or FPGA acceptance."""

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from original_grasu_physical_port_fixture import INVOCATION, STATE, UNIT, build, change, proof, write
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware import configuration as config
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.physical_port import probe, route, route_inputs


class OriginalGPhysicalRouteTests(unittest.TestCase):
    def admit(self, values, *, states=None):
        packet, attempt, bd, _, compiled = values
        with patch.object(route_inputs, "service_state", side_effect=states, return_value=STATE), \
                patch.object(probe, "inputs", return_value=([], compiled)):
            return route_inputs.admit(packet, attempt, bd, unit=UNIT, invocation=INVOCATION)

    def test_complete_bd_admits_only_an_unchanged_external_port_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            values = build(Path(directory))
            result = self.admit(values)
            self.assertEqual(result["profile"], route_inputs.PROFILE)
            self.assertFalse(result["source_modified"])
            self.assertTrue(result["physical_interconnect_changed"])
            self.assertFalse(result["publication_performance_match"])
            self.assertEqual(result["service"], STATE)

    def test_result_claims_raw_policy_proof_and_containment_are_checked(self):
        cases = (("results.json", lambda r: r.update(status="ROUTED")),
                 ("results.json", lambda r: r.update(hardware_timing_measured=True)),
                 ("results.json", lambda r: r["step"].update(exit_code=False)),
                 ("results.json", lambda r: r["admission"].update(admitted=False)),
                 ("results.json", lambda r: r.update(memory_events_after="oom 0\noom_kill 1\noom_group_kill 1\n")),
                 ("results.json", lambda r: r["containment"]["limits"].update({"memory.max": "max"})),
                 ("results.json", lambda r: r["containment"]["limits"].update({"memory.oom.group": "0"})),
                 ("results.json", lambda r: r["physical_port"].update(groups=7)),
                 ("link.resources.json", lambda r: r.update(reserve_gib=0)),
                 ("manifest.json", lambda r: r.update(timeout_seconds=43200)),
                 ("manifest.json", lambda r: r.update(command=["--platform"])))
        for name, mutate in cases:
            with self.subTest(name=name, mutate=mutate), tempfile.TemporaryDirectory() as directory:
                values = build(Path(directory))
                change(values[2], name, mutate)
                with self.assertRaises(ValueError): self.admit(values)

    def test_changed_hooks_platform_or_proof_cannot_be_reused(self):
        for name in (*["hooks/" + hook for hook in probe.HOOK_NAMES], "platform", "hooks/physical_port.xml"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                values = build(Path(directory))
                path = values[3] if name == "platform" else values[2] / name
                path.write_text(path.read_text() + "\nchanged")
                with self.assertRaises((ValueError, probe.ET.ParseError)):
                    self.admit(values)

    def test_wrong_live_failed_or_changed_service_cannot_admit(self):
        for states in ([dict(STATE, SubState="running", MainPID="1")],
                       [dict(STATE, Result="exit-code")],
                       [dict(STATE, InvocationID="2" * 32)],
                       [STATE, dict(STATE, InvocationID="2" * 32)]):
            with self.subTest(states=states), tempfile.TemporaryDirectory() as directory:
                values = build(Path(directory))
                with self.assertRaises(ValueError): self.admit(values, states=states)

    def test_full_link_retains_all_xos_frequency_and_hooks_without_bd_stop(self):
        root = Path("/synthetic")
        for bd_only in (True, False):
            command = probe.link_command("/vendor/v++", root / "p.xpfm", root / "packet",
                                          root / "attempt", root / "output", bd_only=bd_only)
            self.assertEqual(command[command.index("--kernel_frequency") + 1], "150")
            self.assertEqual("--to_step" in command, bd_only)
            self.assertEqual([item for item in command if item.endswith(".xo")],
                [str(root / "attempt/xo" / (name + ".hw.xo")) for name in config.KERNELS])
            self.assertEqual(command[-4:], ["--xp", "param:compiler.userPreSysLinkTcl=/synthetic/output/hooks/pre_link.tcl",
                "--xp", "param:compiler.userPostSysLinkTcl=/synthetic/output/hooks/post_link.tcl"])

    def test_wait_bounds_and_identity_fail_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kwargs in (dict(unit="bad;unit", invocation=INVOCATION),
                           dict(unit=UNIT, invocation="bad"),
                           dict(unit=UNIT, invocation=INVOCATION, maximum_wait=float("nan")),
                           dict(unit=UNIT, invocation=INVOCATION, poll_seconds=0)):
                with self.assertRaises(ValueError): route.run(*([root] * 8), **kwargs)
            self.assertEqual(list(root.iterdir()), [])

    def test_waiter_stops_before_tools_on_changed_or_failed_parent(self):
        for state in (dict(STATE, InvocationID="2" * 32), dict(STATE, Result="exit-code")):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.object(probe, "current"), patch.object(probe, "verify", return_value={}), \
                        patch.object(probe, "inputs", return_value=([], [])), \
                        patch.object(route, "runner_pins", return_value=[]), \
                        patch.object(route_inputs, "service_state", return_value=state), \
                        patch.object(probe, "run") as tool, self.assertRaises(ValueError):
                    route.run(root, root, root, root / "output", root, root, root, root,
                              unit=UNIT, invocation=INVOCATION)
                tool.assert_not_called()
                result = json.loads((root / "output/results.json").read_text())
                self.assertEqual(result["status"], "FAILED_RETAINED")
                self.assertFalse(result["board_programmed"])

    def test_waiter_timeout_never_starts_full_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(probe, "current"), patch.object(probe, "verify", return_value={}), \
                    patch.object(probe, "inputs", return_value=([], [])), \
                    patch.object(route, "runner_pins", return_value=[]), \
                    patch.object(route_inputs, "service_state", return_value=dict(STATE, SubState="running", MainPID="1")), \
                    patch.object(route.time, "monotonic", side_effect=[0, 2]), \
                    patch.object(probe, "run") as tool, self.assertRaises(TimeoutError):
                route.run(root, root, root, root / "output", root, root, root, root,
                          unit=UNIT, invocation=INVOCATION, maximum_wait=1)
            tool.assert_not_called()

    def test_waiter_records_child_success_or_failure_without_board_claims(self):
        for success in (False, True):
            with self.subTest(success=success), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                output = root / "output"
                expected = "EXTERNAL_PORT_LINK_PASS_AWAITING_CLOCK_TIMING_AND_BOARD"
                parent = {"bd": str(root), "unit": UNIT, "invocation": INVOCATION, "pins": []}
                stack.enter_context(patch.object(probe, "current"))
                stack.enter_context(patch.object(probe, "verify", return_value={}))
                stack.enter_context(patch.object(probe, "inputs", return_value=([], [])))
                stack.enter_context(patch.object(route, "runner_pins", return_value=[]))
                stack.enter_context(patch.object(route_inputs, "service_state", return_value=STATE))
                stack.enter_context(patch.object(route_inputs, "admit", return_value=parent))
                def child(*args, **kwargs):
                    result = {"status": expected if success else "FAILED_RETAINED"}
                    write(output, "link_attempt/results.json", result)
                    return result
                tool = stack.enter_context(patch.object(probe, "run", side_effect=child))
                if success:
                    route.run(root, root, root, output, root, root, root, root,
                              unit=UNIT, invocation=INVOCATION)
                else:
                    with self.assertRaises(ValueError):
                        route.run(root, root, root, output, root, root, root, root,
                                  unit=UNIT, invocation=INVOCATION)
                self.assertEqual(tool.call_args.kwargs["bd_parent"], parent)
                result = json.loads((output / "results.json").read_text())
                self.assertEqual(result["status"], expected if success else "FAILED_RETAINED")
                self.assertTrue(all(result[flag] is False for flag in config.FLAGS))

    def test_bd_and_full_execution_keep_separate_claims_and_resource_limits(self):
        for full in (False, True):
            with self.subTest(full=full), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                packet, attempt, bd, platform, compiled = build(root)
                output, group = root / "output", root / "cgroup"
                group.mkdir()
                (group / "memory.events").write_text("oom 0\noom_kill 0\noom_group_kill 0\n")
                parent = {"bd": str(bd), "unit": UNIT, "invocation": INVOCATION, "pins": []}
                stack.enter_context(patch.object(probe, "inputs", side_effect=lambda *a: ([], compiled)))
                stack.enter_context(patch.object(route_inputs, "admit", return_value=parent))
                stack.enter_context(patch.object(probe, "current", return_value=group))
                stack.enter_context(patch.object(probe, "verify", return_value={}))
                stack.enter_context(patch.object(probe.shutil, "disk_usage", return_value=SimpleNamespace(free=500*1024**3)))
                lease = stack.enter_context(patch.object(probe, "Lease")).return_value
                lease.sample.return_value = {"admitted": True}
                stack.enter_context(patch.object(probe, "available_memory_bytes", return_value=500*1024**3))
                stack.enter_context(patch.object(probe, "other_builds", return_value=[]))
                contract = {"tools": {"v++": {"invocation": "/vendor/v++"}}, "pins": []}
                stack.enter_context(patch.object(probe.environment, "capture", return_value=({}, contract)))
                def preflight(*args):
                    write(output, "preflight/results.json", {"synthetic": True})
                    return {"synthetic": True}
                preflight_mock = stack.enter_context(patch.object(probe.environment_probe, "run", side_effect=preflight))
                stack.enter_context(patch.object(probe, "require_unchanged"))
                def link(command, cwd, prefix, **kwargs):
                    proof(output / "hooks/physical_port.xml")
                    if full:
                        (output / "original_grasu.hw.xclbin").write_text("synthetic not FPGA")
                    return dict(exit_code=0, stop_reason="process_exit", cleanup_snapshot_error=None)
                tool = stack.enter_context(patch.object(probe, "run_link", side_effect=link))
                result = probe.run(packet, attempt, output, root, root, platform, root,
                                   bd_parent=parent if full else None)
                expected = "EXTERNAL_PORT_LINK_PASS_AWAITING_CLOCK_TIMING_AND_BOARD" if full else route_inputs.PASS
                self.assertEqual(result["status"], expected)
                self.assertTrue(all(result[flag] is False for flag in config.FLAGS))
                self.assertEqual(tool.call_args.kwargs["timeout"], 43200 if full else 3600)
                self.assertEqual(tool.call_args.kwargs["tree_memory_gib"], 40)
                self.assertEqual(tool.call_args.kwargs["reserve_gib"], 32)
                self.assertEqual(preflight_mock.call_count, int(full))
                self.assertEqual("--to_step" in tool.call_args.args[0], not full)
                lease.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
