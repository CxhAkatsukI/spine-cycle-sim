import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh import input_relocation
from spine_cycle_sim.experiments.evaluation_impact.r_credits.freeze import pin


class FigureInputRelocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.json"
        self.original = dict(graph="/old/graph", updates="/old/updates", batch_count=10,
                             dataset="fixture", grasu_partition_vertices=65536)
        self.source.write_text(json.dumps(self.original))
        self.replacements = {}
        for name in ("graph", "updates"):
            path = self.root / name
            path.write_text(name)
            self.replacements[name] = (path, pin(path)["sha256"])
        self.output = self.root / "relocated.json"

    def test_preserves_semantics_and_indexes_source_and_transferred_inputs(self):
        result = input_relocation.prepare(self.source, self.output, self.replacements)
        self.assertEqual(json.loads(self.source.read_text()), self.original)
        self.assertEqual(result["batch_count"], 10)
        self.assertEqual(result["grasu_partition_vertices"], 65536)
        self.assertEqual(result["input_relocation"]["source_manifest"], pin(self.source))
        for name, (path, _) in self.replacements.items():
            self.assertEqual(result[name], str(path))
            self.assertEqual(result["input_relocation"]["inputs"][name], pin(path))

    def test_changed_transfer_cannot_create_a_manifest(self):
        self.replacements["graph"][0].write_text("changed")
        with self.assertRaisesRegex(ValueError, "digest differs"):
            input_relocation.prepare(self.source, self.output, self.replacements)
        self.assertFalse(self.output.exists())

    def test_cannot_overwrite_a_previous_run(self):
        self.output.write_text("previous")
        with self.assertRaisesRegex(ValueError, "must be new"):
            input_relocation.prepare(self.source, self.output, self.replacements)
        self.assertEqual(self.output.read_text(), "previous")

    def test_both_paths_must_be_explicit(self):
        with self.assertRaisesRegex(ValueError, "both graph and updates"):
            input_relocation.prepare(self.source, self.output,
                                     {"graph": self.replacements["graph"]})
