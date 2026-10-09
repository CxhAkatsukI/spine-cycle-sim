import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.audit_repository_structure import (
    build_inventory,
    check_document_layout,
    count_lines,
    DOCUMENT_GUIDES,
    document_locations,
    document_topic,
    expected_catalogs,
    render_document_catalog,
    render_script_catalog,
    script_topic,
    tracked_paths,
)


class RepositoryStructureTests(unittest.TestCase):
    def test_inventory_does_not_count_fixture_rows_as_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [Path("cpp/src/example.cpp"), Path("tests/data/example.slice")]
            for path in paths:
                (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / paths[0]).write_text("first\nsecond\n", encoding="ascii")
            (root / paths[1]).write_text("edge\n" * 100, encoding="ascii")
            inventory = build_inventory(root, paths)
            self.assertEqual(inventory["tracked_files"], 2)
            self.assertEqual(inventory["source_lines"], 2)

    def test_line_count_handles_empty_and_unterminated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.py"
            path.write_bytes(b"")
            self.assertEqual(count_lines(path), 0)
            path.write_bytes(b"first\nsecond")
            self.assertEqual(count_lines(path), 2)

    def test_failure_record_is_classified_by_topic_not_admitted_as_current(self):
        name = "current_fpga_spine_v14_so_failure_and_v15_freeze_20260812.md"
        self.assertEqual(document_topic(name), "FPGA alignment and calibration investigations")

    def test_document_catalog_excludes_nested_evidence_and_encodes_paths(self):
        catalog = render_document_catalog([
            Path("docs/spine example.md"),
            Path("docs/evidence/example.md"),
        ])
        self.assertIn("../spine%20example.md", catalog)
        self.assertNotIn("example.md](../example.md)", catalog)
        self.assertIn("not current/obsolete or pass/fail", catalog)

    def test_document_catalog_includes_relocated_records_but_not_archives_or_guides(self):
        catalog = render_document_catalog([
            Path("docs/implementation/spine/spine_example.md"),
            Path("docs/implementation/spine/README.md"),
            Path("docs/evaluation_refresh_20260810/package/example.md"),
            Path("docs/evidence/example.md"),
            Path("docs/repository/document_catalog.md"),
        ])
        self.assertIn("../implementation/spine/spine_example.md", catalog)
        self.assertNotIn("[README.md]", catalog)
        self.assertNotIn("[example.md]", catalog)
        self.assertNotIn("[document_catalog.md]", catalog)

    def create_document_layout(self, root):
        moves = {"docs/spine_example.md": "docs/implementation/spine/spine_example.md"}
        for relative in (*DOCUMENT_GUIDES, *moves.values()):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Example\n", encoding="ascii")
        mapping = root / "docs/repository/document_locations.json"
        mapping.write_text(json.dumps({"schema_version": 1, "moves": moves}), encoding="ascii")
        return moves

    def test_relocation_map_and_reading_guides_pass_layout_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_document_layout(root)
            self.assertEqual(check_document_layout(root), [])

    def test_layout_check_rejects_new_flat_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_document_layout(root)
            (root / "docs/new_milestone.md").write_text("# New\n", encoding="ascii")
            self.assertIn("Place this record in a topic directory: docs/new_milestone.md",
                          check_document_layout(root))

    def test_layout_check_rejects_incomplete_relocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            moves = self.create_document_layout(root)
            (root / next(iter(moves.values()))).unlink()
            self.assertEqual(len(check_document_layout(root)), 1)
            self.assertIn("Missing relocated record", check_document_layout(root)[0])

    def test_layout_check_rejects_a_copy_left_at_the_old_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_document_layout(root)
            (root / "docs/spine_example.md").write_text("# Example\n", encoding="ascii")
            self.assertIn("Old flat record still exists: docs/spine_example.md",
                          check_document_layout(root))

    def test_relocation_map_cannot_move_documents_into_frozen_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_document_layout(root)
            (root / "docs/repository/document_locations.json").write_text(json.dumps({
                "schema_version": 1,
                "moves": {"docs/spine_example.md": "docs/evidence/spine_example.md"},
            }), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "Unsafe or unsupported"):
                document_locations(root)

    def test_tracked_inventory_handles_unstaged_document_relocations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            moves = self.create_document_layout(root)
            git_result = SimpleNamespace(stdout=b"docs/spine_example.md\0")
            with patch("scripts.audit_repository_structure.subprocess.run", return_value=git_result):
                paths = tracked_paths(root)
            self.assertEqual(paths, [Path(next(iter(moves.values())))])
            self.assertEqual(build_inventory(root, paths)["top_level_markdown_records"], 0)

    def test_layout_check_requires_the_human_reading_guide(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_document_layout(root)
            (root / "docs/implementation/spine/README.md").unlink()
            self.assertEqual(check_document_layout(root), [
                "Missing reading guide: docs/implementation/spine/README.md",
            ])

    def test_catalog_order_is_deterministic(self):
        paths = [Path("docs/spine_z.md"), Path("docs/spine_a.md")]
        self.assertEqual(render_document_catalog(paths), render_document_catalog(reversed(paths)))

    def test_script_catalog_keeps_versioned_commands(self):
        catalog = render_script_catalog([
            Path("scripts/analyze_example_v1.py"),
            Path("scripts/analyze_example_v2.py"),
            Path("scripts/README.md"),
        ])
        self.assertIn("analyze_example_v1.py", catalog)
        self.assertIn("analyze_example_v2.py", catalog)
        self.assertNotIn("[README.md](README.md)", catalog)
        self.assertEqual(script_topic("run_example.sh"), "Execution and experiment drivers")

    def test_catalog_generation_includes_new_audit_entry_once(self):
        path = Path("scripts/audit_repository_structure.py")
        without = expected_catalogs([])[Path("scripts/CATALOG.md")]
        with_path = expected_catalogs([path])[Path("scripts/CATALOG.md")]
        self.assertEqual(without, with_path)
        self.assertEqual(with_path.count("[audit_repository_structure.py]"), 1)


if __name__ == "__main__":
    unittest.main()
