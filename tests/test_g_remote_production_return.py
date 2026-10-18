import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import (
    admission, capsule, delivery, timing,
)
from test_g_remote_production_link import fixture
from test_grasu_continuous_supervisor import INVOCATION, state


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def returned_fixture(root, *, timing_profile=None):
    parent, exports = fixture(root)
    relocated = root / "relocated"
    with patch.object(capsule.production, "EXPORTS", exports):
        packet = capsule.prepare(parent, relocated)
    route = root / "remote-route"
    route.mkdir()
    platform = root / "platform.xpfm"
    platform.write_text("synthetic platform")
    environment = {"tools": {"v++": {"invocation": "/remote/v++"}}, "pins": [identity(platform)]}
    write(route / "environment.json", environment)
    (route / "link.cfg").write_text(timing.configure(capsule.configuration(
        (relocated / "parent/link.cfg").read_text(), route, platform), timing_profile))
    (route / "candidate.hw.xclbin").write_text("synthetic binary, never programmed")
    for name in ("route.stdout.txt", "route.stderr.txt"):
        (route / name).write_text("")
    report = route / "reports/link/imp/impl_1_hw_bb_locked_timing_summary_routed.rpt"
    report.parent.mkdir(parents=True)
    report.write_text("WNS(ns) TNS(ns) TNS_FAILING TNS_TOTAL WHS(ns) THS(ns) THS_FAILING THS_TOTAL WPWS(ns) TPWS(ns) TPWS_FAILING TPWS_TOTAL\n"
                      "-------\n0.003 0 0 100 0.009 0 0 100 0.000 0 0 100\n"
                      "All user specified timing constraints are met.\n")
    resources = {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None}
    write(route / "route.resources.json", resources)
    for label in delivery.LABELS:
        write(route / f"preflight/{label}.resources.json", resources)
        for suffix in ("stdout.txt", "stderr.txt"):
            (route / f"preflight/{label}.{suffix}").write_text("")
    write(route / "preflight/results.json", {"status": "PREFLIGHT_PASS_NOT_ROUTED",
        "commands": [{"label": label, **resources} for label in delivery.LABELS]})
    pins = [identity(relocated / "capsule.json"),
            *[identity(relocated / row["member"]) for row in packet["files"]],
            identity(route / "environment.json"), identity(route / "link.cfg"), identity(platform)]
    parent_manifest = json.loads((parent / "manifest.json").read_text())
    resources.update(command=capsule.command(packet, parent_manifest, relocated, route, Path("/remote/v++")), cwd=str(route))
    write(route / "route.resources.json", resources)
    manifest = {"command": capsule.command(packet, parent_manifest, relocated, route, Path("/remote/v++")),
        "pins": pins, "relocation": identity(relocated / "capsule.json"), "parent": packet["parent"],
        "clock_mhz": 150, "policy": capsule.POLICY, **dict.fromkeys(capsule.FLAGS, False)}
    if timing_profile is not None:
        manifest["timing_profile"] = timing_profile
    write(route / "manifest.json", manifest)
    execution = {"status": delivery.PASS, "errors": [], "route": resources,
        "host": socket.gethostname(), "capsule": identity(relocated / "capsule.json"),
        "manifest": identity(route / "manifest.json"), "xclbin": identity(route / "candidate.hw.xclbin"),
        "parent": packet["parent"], "memory_events_after": "oom 0\noom_kill 0\noom_group_kill 0\n",
        **dict.fromkeys(capsule.FLAGS, False)}
    write(route / "execution.json", execution)
    return parent, relocated, route, exports


class RemoteReturnTests(unittest.TestCase):
    def fixture(self, root, *, timing_profile=None):
        parent, relocated, route, exports = returned_fixture(root, timing_profile=timing_profile)
        output = root / "returned"
        with patch.object(delivery, "service_state", return_value=state()):
            receipt = delivery.seal(relocated, route, output, unit="remote.service", invocation=INVOCATION)
        return parent, relocated, route, exports, output, receipt["sha256"]

    def test_return_survives_transport_without_rewriting_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, route, _, returned, digest = self.fixture(root)
            old_manifest = (route / "manifest.json").read_bytes()
            moved = root / "moved"
            returned.rename(moved)
            receipt, _, _ = delivery.verify(moved, digest)
            self.assertEqual(receipt["invocation"], INVOCATION)
            self.assertEqual((moved / "route/manifest.json").read_bytes(), old_manifest)
            self.assertTrue(all(receipt[flag] is False for flag in capsule.FLAGS))

    def test_running_restarted_and_failed_service_cannot_seal(self):
        for service in (state("active"), state("failed"), state(InvocationID="b" * 32)):
            with self.subTest(service=service), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, relocated, route, _ = returned_fixture(root)
                with patch.object(delivery, "service_state", return_value=service), self.assertRaises(ValueError):
                    delivery.seal(relocated, route, root / "returned", unit="remote.service", invocation=INVOCATION)
                self.assertFalse((root / "returned").exists())

    def test_incomplete_preflight_bad_exit_missing_oom_and_promoted_claims_rejected(self):
        changes = [lambda e, m, p: e.update(status="ROUTING_NOT_BOARD_ADMISSION"),
                   lambda e, m, p: e["route"].update(exit_code=True),
                   lambda e, m, p: e["route"].update(cleanup_snapshot_error="unreadable"),
                   lambda e, m, p: e.update(memory_events_after="oom 0\noom_kill 1\n"),
                   lambda e, m, p: e.update(FPGA_timing_admitted=True),
                   lambda e, m, p: m.update(publication_match_admitted=True),
                   lambda e, m, p: p["commands"].pop(),
                   lambda e, m, p: p["commands"][0].update(exit_code=1)]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                _, _, route, _ = returned_fixture(Path(directory))
                paths = [route / member for member in ("execution.json", "manifest.json", "preflight/results.json")]
                rows = [json.loads(path.read_text()) for path in paths]
                change(*rows)
                with self.assertRaises(ValueError):
                    delivery.completed(*rows)

    def test_changed_files_receipt_and_unsafe_members_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, _, output, digest = self.fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, "digest"):
                delivery.verify(output, "0" * 64)
            (output / "route/candidate.hw.xclbin").write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                delivery.verify(output, digest)
        for member in ("../escape", "/absolute"):
            with self.subTest(member=member), tempfile.TemporaryDirectory() as directory:
                _, _, _, _, output, _ = self.fixture(Path(directory))
                receipt = json.loads((output / "receipt.json").read_text())
                receipt["files"][0]["member"] = member
                write(output / "receipt.json", receipt)
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    delivery.verify(output, identity(output / "receipt.json")["sha256"])

    def test_local_admission_checks_strict_timing_cus_and_unchanged_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, _, _, exports, returned, digest = self.fixture(root)
            original = root / "original.xclbin"
            original.write_text("original")
            topology = {"clock": [("DATA", "DATA_CLK", 150)], "kernels": [
                (f"{name}:{name}_{index + 1}", "AP_CTRL_CHAIN")
                for name, count in admission.COUNTS.items() for index in range(count)], "connections": []}
            with patch.object(admission.production, "EXPORTS", exports), \
                    patch.object(admission.bitstream, "_dump", return_value={}), \
                    patch.object(admission.bitstream, "normalized_topology", return_value=topology):
                result = admission.review(returned, original, root / "admission", parent_directory=parent, receipt_sha256=digest)
                self.assertEqual(result["status"], "ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD")
                self.assertEqual(result["timing"]["wns_ns"], 0.003)
                with patch.object(admission.bitstream, "parse_routed_timing", side_effect=ValueError("timing failed")), \
                        self.assertRaisesRegex(ValueError, "timing failed"):
                    admission.review(returned, original, root / "bad-timing", parent_directory=parent, receipt_sha256=digest)
                topology["kernels"].pop()
                with self.assertRaisesRegex(ValueError, "CU budget"):
                    admission.review(returned, original, root / "bad-cus", parent_directory=parent, receipt_sha256=digest)
                parent_manifest = json.loads((parent / "manifest.json").read_text())
                Path(parent_manifest["kernel_inputs"]["bin_search"]["frozen"]["path"]).write_text("changed")
                with self.assertRaises(ValueError):
                    admission.review(returned, original, root / "bad-parent", parent_directory=parent, receipt_sha256=digest)

    def test_sealed_but_changed_configuration_or_actual_command_is_rejected(self):
        for change_config in (True, False):
            with self.subTest(change_config=change_config), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, relocated, route, exports = returned_fixture(root)
                manifest = json.loads((route / "manifest.json").read_text())
                execution = json.loads((route / "execution.json").read_text())
                if change_config:
                    config = route / "link.cfg"
                    config.write_text(config.read_text() + "\n[connectivity]\nnk=wrong:99\n")
                    for pin in manifest["pins"]:
                        if pin["path"] == str(config):
                            pin.update(identity(config))
                    write(route / "manifest.json", manifest)
                    execution["manifest"] = identity(route / "manifest.json")
                else:
                    execution["route"]["command"] = ["wrong-compiler"]
                    write(route / "route.resources.json", execution["route"])
                write(route / "execution.json", execution)
                returned = root / "returned"
                with patch.object(delivery, "service_state", return_value=state()):
                    digest = delivery.seal(relocated, route, returned, unit="remote.service", invocation=INVOCATION)["sha256"]
                original = root / "original.xclbin"
                original.write_text("original")
                with patch.object(admission.production, "EXPORTS", exports), \
                        self.assertRaisesRegex(ValueError, "configuration"):
                    admission.review(returned, original, root / "rejected", parent_directory=parent, receipt_sha256=digest)

    def test_physical_retry_retains_topology_and_strict_timing_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, _, _, exports, returned, digest = self.fixture(root, timing_profile=timing.PROFILE)
            original = root / "original.xclbin"
            original.write_text("original")
            topology = {"clock": [("DATA", "DATA_CLK", 150)], "kernels": [
                (f"{name}:{name}_{index + 1}", "AP_CTRL_CHAIN")
                for name, count in admission.COUNTS.items() for index in range(count)], "connections": []}
            with patch.object(admission.production, "EXPORTS", exports), \
                    patch.object(admission.bitstream, "_dump", return_value={}), \
                    patch.object(admission.bitstream, "normalized_topology", return_value=topology):
                result = admission.review(returned, original, root / "admission", parent_directory=parent, receipt_sha256=digest)
                self.assertEqual(result["timing_profile"], timing.PROFILE)
                with patch.object(admission.bitstream, "parse_routed_timing", side_effect=ValueError("negative HBM WNS")), \
                        self.assertRaisesRegex(ValueError, "negative HBM"):
                    admission.review(returned, original, root / "negative-hbm", parent_directory=parent, receipt_sha256=digest)
                different = {**topology, "clock": [("DATA", "DATA_CLK", 149)]}
                with patch.object(admission.bitstream, "normalized_topology", side_effect=[topology, different]), \
                        self.assertRaisesRegex(ValueError, "clock"):
                    admission.review(returned, original, root / "changed-clock", parent_directory=parent, receipt_sha256=digest)

    def test_unrecorded_physical_retry_is_rejected_even_when_resealed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, relocated, route, exports = returned_fixture(root, timing_profile=timing.PROFILE)
            manifest = json.loads((route / "manifest.json").read_text())
            manifest.pop("timing_profile")
            write(route / "manifest.json", manifest)
            execution = json.loads((route / "execution.json").read_text())
            execution["manifest"] = identity(route / "manifest.json")
            write(route / "execution.json", execution)
            returned = root / "returned"
            with patch.object(delivery, "service_state", return_value=state()):
                digest = delivery.seal(relocated, route, returned, unit="remote.service", invocation=INVOCATION)["sha256"]
            original = root / "original.xclbin"
            original.write_text("original")
            with patch.object(admission.production, "EXPORTS", exports), \
                    self.assertRaisesRegex(ValueError, "configuration"):
                admission.review(returned, original, root / "rejected", parent_directory=parent, receipt_sha256=digest)


if __name__ == "__main__":
    unittest.main()
