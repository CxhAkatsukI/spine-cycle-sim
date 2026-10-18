import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.evaluation_impact.common_g.production_board import route
import test_grasu_continuous_execution as diagnostic_tests


def fixture(root):
    manifest, result, checked = diagnostic_tests.ContinuousRouteTests().fixture(root)
    rows = []
    for index, member in enumerate(sorted(route.MEMBERS)):
        source = root / (str(index) + ".hpp")
        source.write_text(member)
        rows.append({"member": member, **identity(source)})
        manifest["pins"].append(identity(source))
    core = {"rtl_components_rechecked": True, "connected_host_rechecked": True, "production_source_members": rows,
            **dict.fromkeys(("integrated_rtl_admitted", "device_metadata_refresh_admitted",
                            "production_baseline_admitted", "publication_match_admitted"), False)}
    manifest.update(candidate_owner="production-source-grasu-complete", core_identity=core,
                    production_source_evidence=copy.deepcopy(core),
                    **dict.fromkeys(("integrated_rtl_admitted", "FPGA_timing_admitted",
                                    "production_baseline_admitted", "publication_match_admitted"), False))
    exports = {name: manifest["kernel_inputs"][name]["source"]["sha256"] for name in route.EXPORTS}
    save(root, manifest)
    return manifest, checked, exports


def save(root, manifest):
    (root / "manifest.json").write_text(json.dumps(manifest))


def append_preflight(root, manifest):
    path = root / "preflight/results.json"
    path.parent.mkdir()
    path.write_text('{"synthetic_test_only":true}')
    manifest["pins"].append(identity(path))
    save(root, manifest)


class ProductionRouteTests(unittest.TestCase):
    def test_registered_comparison_pair_is_atomic_and_keeps_other_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _, old_exports = fixture(root)
            registered = {name: "b" * 64 if name == "bin_search" else "c" * 64
                          for name in route.EXPORTS}
            with patch.object(route, "EXPORTS", old_exports), \
                    patch.object(route, "REGISTERED_COMPARISON_EXPORTS", registered):
                route.candidate(manifest)
                manifest["kernel_inputs"] = copy.deepcopy(manifest["kernel_inputs"])
                for name, digest in registered.items():
                    for key in ("source", "frozen"):
                        manifest["kernel_inputs"][name][key]["sha256"] = digest
                    if name == "bin_search":
                        with self.assertRaisesRegex(ValueError, "export identity"):
                            route.candidate(manifest)
                route.candidate(manifest)
                for name in ("bin_search", "process_cache"):
                    changed = copy.deepcopy(manifest)
                    changed["kernel_inputs"][name]["source"]["sha256"] = "d" * 64
                    with self.assertRaisesRegex(ValueError, "export identity"):
                        route.candidate(changed)
                manifest["FPGA_timing_admitted"] = True
                with self.assertRaisesRegex(ValueError, "production-source"):
                    route.candidate(manifest)

    def test_production_source_admission_does_not_forge_diagnostic_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, checked, exports = fixture(root)
            append_preflight(root, manifest)
            with patch.object(route, "EXPORTS", exports), patch.object(route.shared, "admit_bitstream", return_value=checked):
                result = route.review(root, root / "original", root / "admission")
            self.assertEqual(result["candidate_owner"], "production-source-grasu-complete")
            self.assertNotIn("synthesizable_core_identical", json.loads((root / "manifest.json").read_text())["core_identity"])
            self.assertEqual(len(result["pins"]), 3)

    def test_diagnostic_exports_changed_members_and_claim_promotions_rejected(self):
        changes = [lambda m: m.update(candidate_owner="old-diagnostic"),
                   lambda m: m["core_identity"].update(connected_host_rechecked=False),
                   lambda m: m["core_identity"]["production_source_members"].pop(),
                   lambda m: m["production_source_evidence"].update(rtl_components_rechecked=False),
                   lambda m: m["kernel_inputs"]["bin_search"]["frozen"].update(sha256="a" * 64),
                   lambda m: m["kernel_inputs"]["process_cache"].update(replaced=False),
                   lambda m: m.update(FPGA_timing_admitted=True), lambda m: m.update(clock_mhz=True)]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest, _, exports = fixture(root)
                change(manifest)
                with patch.object(route, "EXPORTS", exports), self.assertRaises(ValueError):
                    route.candidate(manifest)

    def test_snapshot_allows_only_the_documented_late_preflight_append(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _, exports = fixture(root)
            with patch.object(route, "EXPORTS", exports):
                frozen = route.snapshot(root)
                route.unchanged_packet(root, frozen)
                with self.assertRaisesRegex(ValueError, "final route preflight"):
                    route.unchanged_packet(root, frozen, complete=True)
                append_preflight(root, manifest)
                route.unchanged_packet(root, frozen, complete=True)
                self.assertEqual(route.snapshot(root), frozen)
                changes = [lambda m: m.update(clock_mhz=149), lambda m: m["pins"].pop(0),
                           lambda m: m["pins"].append(m["pins"][0]), lambda m: m["pins"].reverse()]
                for change in changes:
                    modified = copy.deepcopy(manifest)
                    change(modified)
                    save(root, modified)
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        route.unchanged_packet(root, frozen)

    def test_timing_failure_missing_preflight_and_changed_source_cannot_admit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _, exports = fixture(root)
            with patch.object(route, "EXPORTS", exports), patch.object(route.shared, "admit_bitstream") as admit:
                with self.assertRaisesRegex(ValueError, "preflight"):
                    route.review(root, root / "original", root / "admission")
                admit.assert_not_called()
                append_preflight(root, manifest)
                admit.side_effect = ValueError("strict routed timing rejected")
                with self.assertRaisesRegex(ValueError, "timing rejected"):
                    route.review(root, root / "original", root / "admission")
                Path(manifest["core_identity"]["production_source_members"][0]["path"]).write_text("changed")
                with self.assertRaisesRegex(ValueError, "source changed"):
                    route.candidate(manifest)


if __name__ == "__main__":
    unittest.main()
