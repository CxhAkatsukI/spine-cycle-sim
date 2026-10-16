import copy
import json
import unittest

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import diagnostics


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.note = {"kind": "note", "message": diagnostics.RENAME_MESSAGE, "children": [],
                     "locations": [{"caret": {"file": "/usr/include/CL/cl2.hpp", "line": 18}}]}

    def test_empty_array_and_exact_header_note(self):
        self.assertEqual(diagnostics.review("", "[]\n"), [])
        self.assertEqual(diagnostics.review("", json.dumps([self.note])), [self.note])

    def test_unknown_kind_message_nested_or_duplicate_diagnostics(self):
        altered = []
        for key, value in (("kind", "warning"), ("message", "other note"),
                           ("children", [{"kind": "warning"}]), ("locations", [])):
            note = copy.deepcopy(self.note)
            note[key] = value
            altered.append([note])
        altered += [[self.note, self.note], [None], {}, None, 42]
        for records in altered:
            with self.subTest(records=records), self.assertRaises(ValueError):
                diagnostics.review("", json.dumps(records))

    def test_location_must_be_real_header_shape(self):
        for caret in ({"file": "/source/host.cpp", "line": 18}, {"file": "cl2.hpp", "line": 18},
                      {"file": "/usr/include/CL/cl2.hpp", "line": 0}, {"line": 18}, None):
            note = copy.deepcopy(self.note)
            note["locations"] = [{"caret": caret}]
            with self.subTest(caret=caret), self.assertRaises(ValueError):
                diagnostics.review("", json.dumps([note]))

    def test_unstructured_stderr_and_stdout_are_not_ignored(self):
        for stdout, stderr in (("build warning", "[]"), ("", ""), ("", "warning"),
                               ("", "[]\nwarning"), ("", "[{]")):
            with self.subTest(stdout=stdout, stderr=stderr), self.assertRaises(ValueError):
                diagnostics.review(stdout, stderr)


if __name__ == "__main__":
    unittest.main()
