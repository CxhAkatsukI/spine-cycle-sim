from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.evidence.candidate10 import (
    Candidate10EvidenceError,
    load_correctness_cases,
    load_focused_cases,
    load_focused_trials,
    parse_metric_line,
    verify_sha256_manifest,
)


class Candidate10EvidenceTests(unittest.TestCase):
    def test_metric_line_preserves_strings_and_parses_numbers(self) -> None:
        parsed = parse_metric_line(
            "PARTITIONED_CSR_E2E_BATCH case=one input_edges=7 maint_ms=1.25",
            "PARTITIONED_CSR_E2E_BATCH",
        )
        self.assertEqual(
            parsed, {"case": "one", "input_edges": 7, "maint_ms": 1.25}
        )

    def test_sha_manifest_fails_closed_on_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact.txt"
            artifact.write_text("original\n", encoding="ascii")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            manifest = root / "SHA256SUMS"
            manifest.write_text(f"{digest}  {artifact}\n", encoding="ascii")
            self.assertEqual(verify_sha256_manifest(manifest), 1)
            artifact.write_text("tampered\n", encoding="ascii")
            with self.assertRaisesRegex(Candidate10EvidenceError, "mismatch"):
                verify_sha256_manifest(manifest)

    def test_correctness_and_focused_rows_require_clean_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = root / "correctness" / "one_edge"
            case.mkdir(parents=True)
            (case / "exit.status").write_text("0\n", encoding="ascii")
            (case / "console.log").write_text(
                "PARTITIONED_CSR_E2E_BATCH case=one_edge batch=1 "
                "dispatch_reads=1 dispatch_writes=1\n"
                "PARTITIONED_CSR_E2E_SMOKE PASS case=one_edge input_edges=1 "
                "persisted=1 errors=0\n",
                encoding="ascii",
            )
            trial_dir = root / "focused" / "fresh"
            trial_dir.mkdir(parents=True)
            (trial_dir / "trials.csv").write_text(
                "graph,trial,errors\ng,1,0\n", encoding="ascii"
            )
            cases = load_correctness_cases(root)
            trials = load_focused_trials(root)
            self.assertEqual(cases[0]["input_edges"], 1)
            self.assertEqual(cases[0]["batch_count"], 1)
            self.assertEqual(trials[0]["evidence_group"], "fresh")

            (trial_dir / "exit.status").write_text("0\n", encoding="ascii")
            (trial_dir / "console.log").write_text(
                "RMAT_HW PASS\n", encoding="ascii"
            )
            focused = load_focused_cases(root)
            self.assertEqual(focused[0]["primary_pass_marker"], "RMAT_HW PASS")

            (case / "exit.status").write_text("1\n", encoding="ascii")
            with self.assertRaisesRegex(Candidate10EvidenceError, "clean PASS"):
                load_correctness_cases(root)


if __name__ == "__main__":
    unittest.main()
