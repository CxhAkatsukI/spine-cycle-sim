"""Extra physical bandwidth must remain explicit and cannot admit complete R."""

from copy import deepcopy
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import (
    prefetch_analysis, reader_ports, reader_ports_analysis as analysis)
from spine_cycle_sim.experiments.evaluation_impact.r_credits.freeze import pin
from tests.test_regraph_prefetch_compact import with_transport, reference


def cases():
    rows = []
    for latency, reverse, ports in analysis.MATRIX:
        obs = with_transport()
        if ports == 2:
            obs.update(schema_version=3, cycles=90, physical_masters=8, masters_per_frontend=2)
            for w in obs["workers"]:
                w.update(max_parents=24, parents_per_port=[16, 8], sink_done=90)
        rows.append(dict(latency=latency, reverse=reverse, ports=ports, observations=obs))
    return rows


def before():
    return [{k: v for k, v in row.items() if k != "ports"} for row in cases() if row["ports"] == 1]


class ReaderPortsTests(unittest.TestCase):
    def test_fresh_core_driver_links_from_directory_and_retains_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "reference/inputs/warm_update"
            inputs.mkdir(parents=True)
            payload = inputs / "payload.bin"
            payload.write_bytes(b"frozen")
            (root / "CMakeLists.txt").write_text("fixture\n")
            compiler = root / "compiler"
            compiler.write_text("fixture\n")
            before_path, a4_path = root / "reference/results.json", root / "a4.json"
            before_path.write_text(json.dumps(dict(pins_unchanged=True, rows=[{}] * 4,
                status="PREFETCH_COMPACT_DIAGNOSTIC_COMPLETE_NOT_RETENTION", pins=[pin(payload)])))
            a4_path.write_text(json.dumps(dict(pins_unchanged=True, r_rows=[{}] * 32)))
            output, commands = root / "run", []

            def execute(command, cwd, stem, **kwargs):
                commands.append(command)
                failed = stem.name == "build_prefetch_compact"
                stdout = root / "stdout.txt"
                stdout.write_text("")
                return dict(exit_code=int(failed), timed_out=False, stdout=str(stdout))

            with patch.object(reader_ports, "ROOT", root), \
                 patch.object(reader_ports, "COMPILER", compiler), \
                 patch.object(reader_ports, "reservation", return_value=nullcontext({})), \
                 patch.object(reader_ports, "run_bounded", side_effect=execute):
                cpu = min(reader_ports.os.sched_getaffinity(0))
                with self.assertRaisesRegex(ValueError, "bounded reader-port check failed"):
                    reader_ports.run(output, before_path, a4_path, cpu)
            self.assertEqual(commands[-1][-2:], [
                str(output / "build/core/cpp/liboriginal_regraph_cycle.a"),
                str(output / "build/core/cpp/libspine_cycle_core.a")])
            self.assertEqual(json.loads((output / "results.json").read_text())["status"], "FAILED_RETAINED")

    def test_complete_comparison_is_only_reader_diagnostic(self):
        result = analysis.summarize(cases(), before(), reference())
        self.assertEqual(result["pre_edit_rows_exact"], 4)
        self.assertFalse(result["integrated_r_retention_passed"])
        self.assertFalse(result["input_layout_changed"])
        self.assertEqual(result["physical_masters"], 8)

    def test_explicit_physical_ports_and_finite_parent_limits_required(self):
        for key, value in (("physical_masters", 4), ("physical_masters", 8.0),
                           ("masters_per_frontend", 1), ("masters_per_frontend", True)):
            row = deepcopy(cases()[1]["observations"])
            row[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                prefetch_analysis.parse("PREFETCH_COMPACT " + json.dumps(row))
        for value in ([17, 8], [16], [16, True], [16, 0], [1, 1], None):
            row = deepcopy(cases()[1]["observations"])
            row["workers"][0]["parents_per_port"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                prefetch_analysis.parse("PREFETCH_COMPACT " + json.dumps(row))

    def test_old_cycles_and_new_physical_traffic_cannot_change(self):
        for index, owner, field, value in ((0, "total", "cycles", 99),
                (1, "total", "read_bytes", 2561), (1, "worker", "input_dummy", 5),
                (1, "worker", "max_parents", 33), (1, "total", "schema_version", 2)):
            rows = cases()
            target = rows[index]["observations"]
            if owner == "worker": target = target["workers"][0]
            target[field] = value
            with self.subTest(index=index, field=field), self.assertRaises(ValueError):
                analysis.summarize(rows, before(), reference())

    def test_complete_matrix_both_registration_orders_required(self):
        with self.assertRaises(ValueError):
            analysis.summarize(cases()[:-1], before(), reference())
        with self.assertRaises(ValueError):
            analysis.summarize(cases(), before()[:-1], reference())
        rows = cases()
        rows[3]["observations"]["cycles"] += 1
        with self.assertRaisesRegex(ValueError, "registration"):
            analysis.summarize(rows, before(), reference())


if __name__ == "__main__":
    unittest.main()
