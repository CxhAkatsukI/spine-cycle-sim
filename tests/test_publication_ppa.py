from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.evidence.publication_ppa import (
    PublicationPpaError,
    analyze_publication_ppa_manifest,
)


def _write_tsv(path: Path, rows: list[dict[str, object]]) -> str:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PublicationPpaTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        builds = []
        specs = (
            ("spine", "weighted_sssp", "spine_core_sssp_baseline", 1.0),
            (
                "grasu_regraph",
                "weighted_sssp",
                "algorithm_specific_conversion_free_whole_system",
                -0.01,
            ),
            (
                "grasu_regraph",
                "full_pagerank",
                "algorithm_specific_conversion_free_whole_system",
                -0.02,
            ),
            (
                "grasu_regraph",
                "thresholded_residual_pagerank",
                "algorithm_specific_conversion_free_whole_system",
                -0.03,
            ),
        )
        for index, (system, algorithm, scope, wns) in enumerate(specs):
            build_id = f"build_{index}"
            directory = root / build_id
            directory.mkdir()
            resources = {
                "lut": 100 + index,
                "reg": 200,
                "bram": 3,
                "uram": 4,
                "dsp": 5,
            }
            util = directory / "accelerator_util.tsv"
            timing = directory / "timing.tsv"
            artifacts = directory / "artifacts.tsv"
            evidence = {
                "accelerator_util": {
                    "path": str(util.relative_to(root)),
                    "sha256": _write_tsv(
                        util,
                        [{"name": "Used Resources", "stage": "routed", **resources}],
                    ),
                },
                "timing": {
                    "path": str(timing.relative_to(root)),
                    "sha256": _write_tsv(
                        timing,
                        [
                            {
                                "wns_ns": wns,
                                "tns_ns": 0 if wns >= 0 else -1,
                                "tns_failing_endpoints": 0 if wns >= 0 else 1,
                            }
                        ],
                    ),
                },
                "artifacts": {
                    "path": str(artifacts.relative_to(root)),
                    "sha256": _write_tsv(
                        artifacts,
                        [
                            {
                                "path_from_build_root": f"build/{build_id}.xclbin",
                                "size_bytes": 1234,
                                "sha256": str(index) * 64,
                            }
                        ],
                    ),
                },
            }
            builds.append(
                {
                    "build_id": build_id,
                    "system": system,
                    "algorithm": algorithm,
                    "claim_scope": scope,
                    "source": {"revision": f"revision-{index}"},
                    "target_mhz": 150,
                    "artifact_sha256": str(index) * 64,
                    "evidence": evidence,
                    "expected": {
                        "resources": resources,
                        "wns_ns": wns,
                        "timing_disposition": (
                            "target_closed" if wns >= 0 else "routed_target_missed"
                        ),
                    },
                }
            )
        manifest = {
            "schema_version": 1,
            "claim_class": "candidate10_routed_hls_feasibility_non_iso_functional",
            "repository_root": ".",
            "builds": builds,
            "limitations": ["not iso-functional"],
        }
        path = root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_accepts_three_grasu_algorithms_and_one_spine_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = analyze_publication_ppa_manifest(self._fixture(Path(temporary)))
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["coverage"]["grasu_regraph_three_algorithm_routed"])
        self.assertFalse(result["coverage"]["spine_three_algorithm_iso_functional"])
        self.assertFalse(result["resource_ratio_eligible"])
        self.assertEqual(
            result["builds"][0]["timing"]["disposition"], "target_closed"
        )

    def test_rejects_missing_algorithm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._fixture(Path(temporary))
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["builds"].pop()
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(PublicationPpaError, "all three"):
                analyze_publication_ppa_manifest(path)

    def test_rejects_tampered_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._fixture(Path(temporary))
            manifest = json.loads(path.read_text(encoding="utf-8"))
            util = Path(temporary) / manifest["builds"][0]["evidence"][
                "accelerator_util"
            ]["path"]
            util.write_text(
                util.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(PublicationPpaError, "SHA256 mismatch"):
                analyze_publication_ppa_manifest(path)

    def test_rejects_changed_frozen_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._fixture(Path(temporary))
            manifest = json.loads(path.read_text(encoding="utf-8"))
            broken = copy.deepcopy(manifest)
            broken["builds"][0]["expected"]["resources"]["lut"] += 1
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaisesRegex(PublicationPpaError, "frozen expectation"):
                analyze_publication_ppa_manifest(path)


if __name__ == "__main__":
    unittest.main()
