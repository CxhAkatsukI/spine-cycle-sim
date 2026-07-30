from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.plugin_equivalence import (
    HOST_RUNTIME_EQUIVALENCE_CLASS,
    compare_host_runtime_summaries,
    sha256_file,
    verify_spine_plugin_admission,
)


def summary(plugin_sha256: str) -> dict:
    return {
        "status": "PASS",
        "success": True,
        "cycles": 123,
        "backend_requests": 45,
        "final_values_sha256": "f" * 64,
        "architecture_correctness_mismatches": 0,
        "mathematical_correctness_mismatches": 0,
        "sst_host_wall_seconds": 1.0,
        "sst_library_binding": {"plugin_path": "/old"},
        "sst_plugin_sha256": plugin_sha256,
    }


class PluginEquivalenceTests(unittest.TestCase):
    def test_summary_comparison_ignores_only_host_runtime_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            old_hash = "a" * 64
            new_hash = "b" * 64
            baseline.write_text(json.dumps(summary(old_hash)), encoding="ascii")
            updated = summary(new_hash)
            updated["sst_host_wall_seconds"] = 2.0
            updated["sst_library_binding"] = {"plugin_path": "/new"}
            candidate.write_text(json.dumps(updated), encoding="ascii")
            report = compare_host_runtime_summaries(
                baseline, candidate, label="tiny"
            )
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["baseline"]["plugin_sha256"], old_hash)
            self.assertEqual(report["candidate"]["plugin_sha256"], new_hash)

    def test_summary_comparison_rejects_a_cycle_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            baseline.write_text(json.dumps(summary("a" * 64)), encoding="ascii")
            changed = summary("b" * 64)
            changed["cycles"] += 1
            candidate.write_text(json.dumps(changed), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "cycles"):
                compare_host_runtime_summaries(
                    baseline, candidate, label="changed"
                )

    def test_spine_admission_verifies_every_frozen_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_plugin = root / "baseline.so"
            candidate_plugin = root / "candidate.so"
            baseline_plugin.write_bytes(b"baseline")
            candidate_plugin.write_bytes(b"candidate")
            old_hash = sha256_file(baseline_plugin)
            new_hash = sha256_file(candidate_plugin)
            reports = []
            for label in ("tiny", "real"):
                report = {
                    "schema_version": 1,
                    "status": "pass",
                    "label": label,
                    "classification": HOST_RUNTIME_EQUIVALENCE_CLASS,
                    "ignored_top_level_fields": [
                        "sst_host_wall_seconds",
                        "sst_library_binding",
                        "sst_plugin_sha256",
                    ],
                    "canonical_summary_sha256": hashlib.sha256(
                        label.encode("ascii")
                    ).hexdigest(),
                    "baseline": {"plugin_sha256": old_hash},
                    "candidate": {"plugin_sha256": new_hash},
                }
                path = root / f"{label}.json"
                path.write_text(json.dumps(report), encoding="ascii")
                reports.append([path.name, sha256_file(path)])
            contract = {
                "architecture_baselines": {
                    "simulator_baseline": {
                        "plugin_sha256": old_hash,
                        "spine_host_runtime_equivalent_plugins": [
                            {
                                "plugin_sha256": new_hash,
                                "baseline_plugin_sha256": old_hash,
                                "classification": HOST_RUNTIME_EQUIVALENCE_CLASS,
                                "source_commit": "1" * 40,
                                "required_report_labels": ["tiny", "real"],
                                "evidence_reports": reports,
                            }
                        ],
                    }
                }
            }
            admission = verify_spine_plugin_admission(
                contract,
                candidate_plugin,
                system="spine",
                repository_root=root,
            )
            self.assertEqual(admission["observed_plugin_sha256"], new_hash)
            with self.assertRaisesRegex(ValueError, "only for Spine"):
                verify_spine_plugin_admission(
                    contract,
                    candidate_plugin,
                    system="grasu_regraph_k1",
                    repository_root=root,
                )
            tampered = deepcopy(report)
            tampered["status"] = "fail"
            (root / "real.json").write_text(json.dumps(tampered), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "missing or changed"):
                verify_spine_plugin_admission(
                    contract,
                    candidate_plugin,
                    system="spine",
                    repository_root=root,
                )


if __name__ == "__main__":
    unittest.main()
