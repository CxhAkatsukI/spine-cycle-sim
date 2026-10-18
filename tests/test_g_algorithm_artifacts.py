"""Terminal remote provenance and local timing admission, without FPGA access."""

import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from test_g_algorithm_topology import fixture as topology_fixture
from test_g_algorithm_inspection import CONFIG
from test_grasu_continuous_supervisor import INVOCATION, state
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import admission, artifacts, route_study


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(root):
    compilation, route, sources = (root / name for name in ("compilation", "route", "sources"))
    source_index = {"integration_revision": "test-integration"}
    write(sources / "sources.json", source_index)
    declared = {"algorithm": "connected_components", "integration_revision": "test-integration",
                "source_manifest": identity(sources / "sources.json"),
                "compiles": [{"kernel": kernel, "xo": "/remote/" + kernel + ".xo"}
                             for kernel in ("pma_to_regraph_adapter", "consume")]}
    write(compilation / "manifest.json", declared)
    write(compilation / "execution.json", {"status": "COMPILATION_PASS_AWAITING_RESOURCE_RTL_AND_ROUTE"})
    sections, checked = topology_fixture()
    write(route / "placement-review.json", checked)
    write(route / "original-review/results.json", {"status": "STORAGE_CONFLICT_REQUIRES_PLACEMENT_REVIEW"})
    write(route / "environment.json", {"tools": {"v++": {"invocation": "/remote/v++"}}})
    (route / "link.cfg").write_text(CONFIG)
    (route / "candidate.hw.xclbin").write_text("synthetic binary; never programmed")
    (route / "route.stdout.txt").write_text("")
    (route / "route.stderr.txt").write_text("")
    command = ["/remote/v++", "--target", "hw", "--link", "--kernel_frequency", "150", "--config",
               str(route / "link.cfg"), "-o", str(route / "candidate.hw.xclbin"),
               *[row["xo"] for row in declared["compiles"]],
               "--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]
    resources = {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None,
                 "tree_memory_gib": 40, "reserve_gib": 32, "timeout_seconds": 43200,
                 "command": command, "cwd": str(route)}
    write(route / "route.resources.json", resources)
    for label in artifacts.LABELS:
        write(route / f"preflight/{label}.resources.json", resources)
        for suffix in ("stdout.txt", "stderr.txt"):
            (route / f"preflight/{label}.{suffix}").write_text("")
    write(route / "preflight/results.json", {"status": "PREFLIGHT_PASS_NOT_ROUTED",
          "commands": [{"label": label, **resources} for label in artifacts.LABELS]})
    pins = [identity(path) for path in (compilation / "manifest.json", compilation / "execution.json",
            sources / "sources.json", route / "placement-review.json", route / "link.cfg", route / "environment.json")]
    manifest = {"algorithm": "connected_components", "integration_revision": "test-integration",
                "command": command, "clock_mhz": 150, "policy": route_study.POLICY, "pins": pins,
                **dict.fromkeys(artifacts.FLAGS, False)}
    write(route / "manifest.json", manifest)
    write(route / "execution.json", {"status": artifacts.PASS, "errors": [], "route": resources,
          "algorithm": declared["algorithm"], "integration_revision": declared["integration_revision"],
          "manifest": identity(route / "manifest.json"), "xclbin": identity(route / "candidate.hw.xclbin"),
          "host": socket.gethostname(), "memory_events_after": "oom 0\noom_kill 0\noom_group_kill 0\n",
          **dict.fromkeys(artifacts.FLAGS, False)})
    report = route / "reports/impl/impl_1_hw_bb_locked_timing_summary_routed.rpt"
    report.parent.mkdir(parents=True)
    report.write_text("WNS(ns) remaining timing columns\n-------\n"
                      "0.003 0 0 100 0.009 0 0 100 0.000 0 0 100\n"
                      "All user specified timing constraints are met.\n")
    return compilation, route, sources, source_index, sections


class ArtifactTests(unittest.TestCase):
    def sealed(self, root):
        compilation, route, sources, source, sections = fixture(root)
        output = root / "returned"
        with patch.object(artifacts, "service_state", return_value=state()), \
                patch.object(artifacts.inputs, "verify", return_value=source):
            result = artifacts.seal(compilation, route, output, unit="route.service", invocation=INVOCATION)
        return output, result["sha256"], sources, source, sections

    def test_return_preserves_remote_absolute_evidence_after_relocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output, digest, _, _, _ = self.sealed(root)
            moved = root / "local-copy"
            output.rename(moved)
            receipt = artifacts.verify(moved, digest)
            self.assertEqual(receipt["remote_route"], str(root / "route"))
            self.assertEqual({row["member"] for row in receipt["files"]}, set(artifacts.MEMBERS))
            self.assertTrue(all(receipt[flag] is False for flag in artifacts.FLAGS))

    def test_running_failed_or_restarted_service_cannot_seal(self):
        for service in (state("active"), state("failed"), state(InvocationID="b" * 32)):
            with self.subTest(service=service), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                comp, route, _, _, _ = fixture(root)
                with patch.object(artifacts, "service_state", return_value=service), self.assertRaises(ValueError):
                    artifacts.seal(comp, route, root / "output", unit="route.service", invocation=INVOCATION)
                self.assertFalse((root / "output").exists())

    def test_running_missing_oom_wrong_scope_or_failed_preflight_rejected(self):
        changes = [lambda e, m, p: e.update(status="ROUTING_EXPERIMENT_NOT_RTL_OR_BOARD_ADMISSION"),
                   lambda e, m, p: e["route"].update(exit_code=True),
                   lambda e, m, p: e.update(memory_events_after="oom 0\noom_kill 0\n"),
                   lambda e, m, p: m.update(board_admitted=True),
                   lambda e, m, p: p["commands"].pop(),
                   lambda e, m, p: p["commands"][0].update(exit_code=1)]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                _, route, _, _, _ = fixture(Path(temporary))
                paths = [route / name for name in ("execution.json", "manifest.json", "preflight/results.json")]
                rows = [json.loads(path.read_text()) for path in paths]
                change(*rows)
                for path, row in zip(paths, rows):
                    write(path, row)
                with self.assertRaises(ValueError):
                    artifacts.completed(route)

    def test_untrusted_digest_modified_binary_duplicate_or_unsafe_member_rejected(self):
        for mutation in ("digest", "binary", "duplicate", "escape", "missing"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                output, digest, _, _, _ = self.sealed(Path(temporary))
                path = output / "receipt.json"
                receipt = json.loads(path.read_text())
                if mutation == "digest":
                    digest = "0" * 64
                elif mutation == "binary":
                    (output / "route/candidate.hw.xclbin").write_text("changed")
                else:
                    if mutation == "duplicate":
                        receipt["files"].append(receipt["files"][0])
                    elif mutation == "escape":
                        receipt["files"][0]["member"] = "../escape"
                    else:
                        receipt["files"].pop()
                    write(path, receipt)
                    digest = identity(path)["sha256"]
                with self.assertRaises(ValueError):
                    artifacts.verify(output, digest)

    def test_local_admission_checks_requested_source_clock_and_timing_not_original_sssp(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            returned, digest, sources, source, sections = self.sealed(root)
            with patch.object(admission.inputs, "verify", return_value=source), \
                    patch.object(admission.commands, "PURE", {"pma_to_regraph_adapter", "consume"}), \
                    patch.object(admission.bitstream, "_dump", return_value=sections):
                result = admission.review(returned, sources, root / "admitted", receipt_sha256=digest)
                self.assertEqual(result["status"], "ALGORITHM_ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD")
                self.assertEqual(result["timing"]["wns_ns"], 0.003)
                self.assertEqual(result["kernel_instances"], 2)
                self.assertFalse(result["board_admitted"])
                self.assertFalse(result["rtl_admitted"])
                with patch.object(admission.bitstream, "parse_routed_timing", side_effect=ValueError("timing fail")), \
                        self.assertRaisesRegex(ValueError, "timing fail"):
                    admission.review(returned, sources, root / "failed", receipt_sha256=digest)
                self.assertEqual(json.loads((root / "failed/summary.json").read_text())["status"], "FAILED_RETAINED")
                (sources / "sources.json").write_text("changed source identity")
                with self.assertRaisesRegex(ValueError, "source closure"):
                    admission.review(returned, sources, root / "bad-source", receipt_sha256=digest)


if __name__ == "__main__":
    unittest.main()
