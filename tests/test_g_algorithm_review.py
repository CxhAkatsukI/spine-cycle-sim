"""Terminal-manifest and portable-capacity admission, with no FPGA tools."""

import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from test_g_algorithm_inspection import CAPACITY, fixture
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline import resource_delivery
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import inputs, inspection, review


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def capsule(root):
    root.mkdir()
    attempts = []
    for index, (field, filename) in enumerate((("physical_capacity", "uram_capacity.csv"),
                                             ("platform_uram_capacity", "platform_uram_capacity.csv"))):
        source = root / ("query" + str(index))
        source.mkdir()
        write(source / "results.json", {"status": resource_delivery.QUERY_STATUSES[index],
            "part": inspection.PART, "errors": [], field: CAPACITY,
            **dict.fromkeys(resource_delivery.CLAIMS, False)})
        (source / filename).write_text("region,uram_sites\nSLR0,320\nSLR1,320\nSLR2,320\ndevice,960\n")
        archive = root / (source.name + ".tar.gz")
        files = []
        with tarfile.open(archive, "w:gz") as stream:
            for path in sorted(source.iterdir()):
                stream.add(path, arcname=path.name, recursive=False)
                files.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        attempts.append({"kind": "query", "archive": archive.name, "sha256": sha256_file(archive),
                         "files": files, "status": resource_delivery.QUERY_STATUSES[index]})
    write(root / "index.json", {"status": resource_delivery.CHECKPOINT, "attempts": attempts,
        **dict.fromkeys((*resource_delivery.CLAIMS, "platform_free_capacity_admitted",
                         "publication_match_admitted"), False)})
    return root


def compile_fixture(root):
    compilation = root / "compile"
    (compilation / "packet/config").mkdir(parents=True)
    _, rows = fixture(compilation / "packet/config")
    source = root / "source/sources.json"
    write(source, {"integration_revision": "fixture-revision"})
    manifest = compilation / "manifest.json"
    write(manifest, {"source_manifest": identity(source), "integration_revision": "fixture-revision",
        "algorithm": "connected_components", "clock_mhz": 150, "pins": [identity(source)],
        "compiles": rows, **inputs.CLAIMS})
    result = {"status": "COMPILATION_PASS_AWAITING_RESOURCE_RTL_AND_ROUTE", "errors": [],
        "algorithm": "connected_components", "manifest": identity(manifest),
        "compiles": [{"kernel": row["kernel"], "xo": identity(Path(row["xo"])), "resources": {
            "exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None}} for row in rows],
        "memory_events_after": "oom 0\noom_kill 0\noom_group_kill 0\n", **inputs.CLAIMS}
    write(compilation / "execution.json", result)
    return compilation, rows


class ReviewTests(unittest.TestCase):
    def test_capacity_capsule_is_portable_and_hash_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = capsule(root / "storage")
            moved = root / "moved"
            storage.rename(moved)
            counts, pins = review.capacities(moved)
            self.assertEqual(counts, {"physical": CAPACITY, "platform": CAPACITY})
            self.assertEqual(len(pins), 3)
            (moved / "query0.tar.gz").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                review.capacities(moved)

    def test_missing_or_duplicate_query_cannot_substitute_for_capacity(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as temporary:
                storage = capsule(Path(temporary) / "storage")
                index = json.loads((storage / "index.json").read_text())
                if duplicate:
                    index["attempts"].append(index["attempts"][0])
                else:
                    index["attempts"].pop()
                write(storage / "index.json", index)
                with self.assertRaisesRegex(ValueError, "one independently"):
                    review.capacities(storage)

    def test_terminal_compile_review_records_inputs_but_no_hardware_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compilation, rows = compile_fixture(root)
            storage = capsule(root / "storage")
            with patch.object(review.inputs, "verify", return_value={"integration_revision": "fixture-revision"}), \
                    patch.object(review.commands, "compile_list", return_value=rows) as admission:
                result = review.run(compilation, storage, root / "review")
            admission.assert_called_once()
            self.assertEqual(result["status"], "EXPORT_AND_STORAGE_SCREEN_PASS_NOT_RTL_OR_ROUTE_ADMISSION")
            self.assertEqual(result["algorithm"], "connected_components")
            self.assertEqual(len(result["reports"]), 2)
            self.assertTrue(all(result[key] is False for key in inputs.CLAIMS))

    def test_nonterminal_changed_xo_missing_row_or_oom_is_retained(self):
        mutations = (lambda e: e.update(status="COMPILING_NOT_ROUTED"),
                     lambda e: e.update(board_admitted=True),
                     lambda e: e["compiles"].pop(),
                     lambda e: e["compiles"][0]["xo"].update(sha256="0" * 64),
                     lambda e: e["compiles"][0]["resources"].update(exit_code=1),
                     lambda e: e.update(memory_events_after="oom 1\noom_kill 0\n"))
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                compilation, rows = compile_fixture(root)
                storage = capsule(root / "storage")
                execution = compilation / "execution.json"
                value = json.loads(execution.read_text())
                mutate(value)
                write(execution, value)
                with patch.object(review.inputs, "verify", return_value={"integration_revision": "fixture-revision"}), \
                        patch.object(review.commands, "compile_list", return_value=rows), self.assertRaises(ValueError):
                    review.run(compilation, storage, root / "review")
                result = json.loads((root / "review/results.json").read_text())
                self.assertEqual(result["status"], "FAILED_RETAINED")
                self.assertTrue(result["errors"])
                self.assertTrue(all(result[key] is False for key in inputs.CLAIMS))


if __name__ == "__main__":
    unittest.main()
