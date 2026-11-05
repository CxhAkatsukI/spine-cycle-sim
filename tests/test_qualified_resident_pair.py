"""A qualified host changes neither kernel identity nor the fresh-pair evidence gate."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    correction_matrix, dual_clock_resident as resident, qualified_resident as qualified,
)


class QualifiedResidentTests(unittest.TestCase):
    def test_only_explicit_cpu_qualification_admits_another_host(self):
        args = argparse.Namespace(spine_host="host", spine_image="image", comparator="compare",
                                  verifier="verify", qualification=None)
        pins = {name: dict(sha256=sha) for name, sha in (
            ("host", "different-host"), ("image", resident.board.SPINE_IMAGE_SHA256),
            ("compare", resident.resident_results.COMPARATOR_SHA256), ("verify", "verifier"))}
        with patch.object(resident, "identity", side_effect=pins.__getitem__), \
                patch.object(resident.host_correction, "admit", return_value=["qualification-pin"]) as admit:
            with self.assertRaisesRegex(ValueError, "frozen Spine"):
                resident.spine_inputs(args)
            admit.assert_not_called()
            args.qualification = "cpu-qualified"
            original, qualified_pins = resident.spine_inputs(args)
            self.assertEqual(original["spine_host"], pins["host"])
            self.assertEqual(qualified_pins, ["qualification-pin"])
            admit.assert_called_once_with(args.qualification, args.spine_host)
            for name in ("image", "compare"):
                old = pins[name]
                pins[name] = dict(sha256="changed")
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "frozen Spine"):
                    resident.spine_inputs(args)
                pins[name] = old

    def test_qualification_failure_cannot_authorize_a_host(self):
        args = argparse.Namespace(spine_host="host", spine_image="image", comparator="compare",
                                  verifier="verify", qualification="unqualified")
        with patch.object(resident, "identity", return_value={}), \
                patch.object(resident.host_correction, "admit", side_effect=ValueError("not qualified")), \
                self.assertRaisesRegex(ValueError, "not qualified"):
            resident.spine_inputs(args)

    def test_fresh_pair_replays_scope_and_rejects_retime_or_changed_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            host, qualification = root / "host", root / "qualification.json"
            host.write_bytes(b"host")
            qualification.write_text("{}")
            args = argparse.Namespace(spine_host=host, qualification=qualification, comparator=root / "comparator")
            stdout, comparison = root / "spine.txt", root / "pair.json"
            stdout.write_text("RESIDENT_CORRECTION_CACHE scope=old_graph_only_single_batch bytes=1024 "
                "preparation_ms=2.5 included_in_dynamic_wall=0\n"
                "RESIDENT_CORRECTION mode=old_incoming_fp32_replay dense_dangling_fallback=0 "
                "host_update_and_state_upload_in_dynamic_wall=1\n")
            raw_pair = dict(gr_rounds=0, spine_rounds=0, speedup_gr_over_spine=0.5)
            comparison.write_text(json.dumps(raw_pair))
            case = dict(dataset="LJ08", requires_propagation=False)
            correction = dict(resident_cache_bytes=1024, old_graph_cache_preparation_ms=2.5,
                              dense_dangling_fallback=False)
            base = dict(dataset="LJ08", case=case, qualification=qualified.identity(qualification),
                spine_host_mode=resident.QUALIFIED_HOST, fresh_samples=dict(spine=1, gr=1),
                gr_sample_reused=False, original_artifacts=dict(spine_host=qualified.identity(host),
                    spine_image=dict(sha256=resident.board.SPINE_IMAGE_SHA256)),
                pins=dict(spine_host=qualified.identity(host)), correction=correction,
                row=dict(case=case, status="MEASURED", attempts=[dict(arm="spine"), dict(arm="gr")],
                    pair=correction_matrix.pair_with_scope(raw_pair, case),
                    comparison_log=qualified.identity(comparison),
                    rows=dict(spine=dict(stdout=qualified.identity(stdout)))))
            path = root / "result.json"
            path.write_text("{}")

            def validate(report):
                with patch.object(qualified.correction_retime, "reference",
                        return_value=(report, dict(resident_mhz=[140, 500, 430, 0]), [])), \
                        patch.object(qualified.host_correction, "admit", return_value=[]):
                    return qualified.validate_result(path, args, "LJ08")

            checked = validate(base)
            self.assertEqual(checked["status"], resident.MEASURED)
            self.assertEqual(checked["pair"]["speedup_gr_over_spine"], 0.5)
            for change in (dict(fresh_samples=dict(spine=1, gr=0)), dict(gr_sample_reused=True),
                           dict(spine_host_mode="old"), dict(dataset="LJ"),
                           dict(qualification={}), dict(correction={})):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    validate({**base, **change})
            for section, field, value in (
                ("original_artifacts", "spine_host", {}), ("pins", "spine_host", {}),
                ("original_artifacts", "spine_image", dict(sha256="changed-kernel")),
                ("row", "status", "FAILED_RETAINED"), ("row", "pair", {}),
                ("row", "attempts", [dict(arm="spine")])):
                report = deepcopy(base)
                report[section][field] = value
                with self.subTest(section=section, field=field), self.assertRaises(ValueError):
                    validate(report)


if __name__ == "__main__":
    unittest.main()
