import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from spine_cycle_sim.experiments.publication_admission.history.git_store import blob, parse_tree, snapshot
from spine_cycle_sim.experiments.publication_admission.history.inspection import inspect_archive, inspect_sources, text_record


class HistoryParsingTests(unittest.TestCase):
    def contract(self):
        return {"limits": {"archive_bytes": 10000, "archive_members": 10,
            "archive_expanded_bytes": 10000, "text_bytes": 1000},
            "text_suffixes": [".cpp", ".h"], "temporal_terms": ["timestamp", "temporal"]}

    def archive(self, files):
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in files:
                archive.writestr(name, data)
        return result.getvalue()

    def test_nul_tree_records_preserve_spaces_and_tabs_in_paths(self):
        oid = b"a" * 40
        result = parse_tree(b"100644 blob " + oid + b"\tsrc/a b\tc.h\0", 1)
        self.assertEqual(result[0]["path"], "src/a b\tc.h")

    def test_tree_count_and_record_shape_are_bounded(self):
        record = b"100644 blob " + b"a" * 40 + b"\tx.h\0"
        with self.assertRaisesRegex(ValueError, "tree-entry"):
            parse_tree(record * 2, 1)
        with self.assertRaises(ValueError):
            parse_tree(b"100644 tree a\tx.h\0", 1)

    def test_geometry_and_temporal_hits_have_original_lines(self):
        result = text_record("source.h", b"#define SEGMENT_SIZE 16\nconst int segment_size = 8;\n// timestamp\n", ["timestamp"])
        self.assertEqual([(x["line"], x["value"]) for x in result["geometry_declarations"]], [(1, 16), (2, 8)])
        self.assertEqual(result["temporal_term_hits"], [{"line": 3, "text": "// timestamp"}])

    def test_archive_source_inspection_is_not_execution(self):
        data = self.archive([("old/src/config.h", "#define MAX_SEGMENT_SIZE 16\n"),
            ("old/output.bin", "binary"), ("__MACOSX/old/src/config.h", "ignored"), ("old/build/config.h", "generated")])
        result = inspect_archive(data, self.contract())
        self.assertEqual(result["members"], 4)
        self.assertEqual(len(result["source_text"]), 1)
        self.assertEqual(result["source_text"][0]["geometry_declarations"][0]["value"], 16)
        self.assertFalse(result["binary_or_generated_members_executed"])

    def test_declared_saved_history_without_source_extension_is_inspected(self):
        contract = self.contract()
        contract["archive_extra_text_prefixes"] = ["old/.history/"]
        data = self.archive([("old/.history/abcdef", "#define SEGMENT_SIZE 8\n// timestamp\n")])
        result = inspect_archive(data, contract)
        self.assertEqual(result["source_text"][0]["geometry_declarations"][0]["value"], 8)
        self.assertEqual(len(result["source_text"][0]["temporal_term_hits"]), 1)

    def test_archive_rejects_unsafe_member_path(self):
        for name in ("../src/config.h", "/root/src/config.h"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsafe"):
                inspect_archive(self.archive([(name, "data")]), self.contract())

    def test_archive_compressed_and_expanded_bounds(self):
        data = self.archive([("old/src/config.h", "x" * 200)])
        for field, maximum, message in (("archive_bytes", 1, "compressed"),
                ("archive_expanded_bytes", 10, "expanded"), ("archive_members", 0, "expanded"),
                ("text_bytes", 10, "source-text")):
            contract = self.contract()
            contract["limits"][field] = maximum
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                inspect_archive(data, contract)


class GitHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.command("init", "-q")
        (self.root / "src").mkdir()
        (self.root / "src/config.h").write_text("#define SEGMENT_SIZE 16\n")
        self.command("add", "src")
        self.command("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial")
        self.head = self.command("rev-parse", "HEAD").decode().strip()
        self.spec = {"head": self.head, "expected_commits": 1, "source_prefixes": ["src/"]}
        self.limits = {"commits": 4, "tree_entries": 4, "text_bytes": 1000}

    def command(self, *arguments):
        return subprocess.check_output(["git", "-C", str(self.root), *arguments], stderr=subprocess.PIPE)

    def test_history_and_author_source_inspection_preserve_worktree(self):
        before = snapshot(self.root, self.spec, self.limits)
        result = inspect_sources(self.root, before, self.spec,
            {"limits": self.limits, "text_suffixes": [".h"], "temporal_terms": ["timestamp"]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["geometry_declarations"][0]["value"], 16)
        self.assertEqual(snapshot(self.root, self.spec, self.limits), before)
        self.assertEqual(self.command("status", "--porcelain"), b"")

    def test_modified_or_untracked_author_checkout_rejected(self):
        (self.root / "untracked.txt").write_text("unknown")
        with self.assertRaisesRegex(ValueError, "pinned and clean"):
            snapshot(self.root, self.spec, self.limits)

    def test_wrong_pin_and_commit_count_rejected(self):
        for change in ({"head": "0" * 40}, {"expected_commits": 2}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                snapshot(self.root, {**self.spec, **change}, self.limits)

    def test_shallow_history_rejected_without_fetching_implicitly(self):
        with patch("spine_cycle_sim.experiments.publication_admission.history.git_store.git", return_value=b"true\n"):
            with self.assertRaisesRegex(ValueError, "complete fetched"):
                snapshot(self.root, self.spec, self.limits)

    def test_blob_size_bound_precedes_read(self):
        oid = self.command("rev-parse", "HEAD:src/config.h").decode().strip()
        self.assertEqual(blob(self.root, oid, 1000), b"#define SEGMENT_SIZE 16\n")
        with self.assertRaisesRegex(ValueError, "blob read bound"):
            blob(self.root, oid, 1)


if __name__ == "__main__":
    unittest.main()
