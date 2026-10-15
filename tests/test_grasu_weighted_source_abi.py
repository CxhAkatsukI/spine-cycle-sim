import tempfile
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.evaluation_impact.common_g.weighted_abi.analysis import (
    ARMS, EXPECTED, FINAL, FINITE_FINAL, INSERTIONS, WARNING_PAIR, analyze, expected_cases,
)
from spine_cycle_sim.experiments.evaluation_impact.common_g.weighted_abi.preparation import (
    command, prepare,
)


def stdout(search_mode="pristine"):
    footer = [FINITE_FINAL, FINAL] if search_mode == "finite_pipeline" else [FINAL]
    return "\n".join([
        f"WEIGHTED_ABI_PASS case={case} arm={arm} operations={values[0]} "
        f"segments={values[1] + 8} shards={values[1]} edges={values[2]}"
        for case, values in expected_cases(search_mode).items() for arm in ARMS
    ] + footer) + "\n"


def stderr(search_mode="pristine"):
    count = INSERTIONS + (130 if search_mode == "finite_pipeline" else 0)
    return "\n".join(WARNING_PAIR * count) + "\n"


class WeightedAbiTests(unittest.TestCase):
    def test_complete_matrix(self):
        self.assertEqual(len(analyze(stdout(), stderr())), 8)

    def test_finite_search_requires_its_extra_case_marker_and_diagnostics(self):
        mode = "finite_pipeline"
        rows = analyze(stdout(mode), stderr(mode), search_mode=mode)
        self.assertEqual(len(rows), 10)
        self.assertEqual(sum(row["operations"] for row in rows), 682)
        for output, errors, scope in ((stdout(), stderr(), mode),
                                      (stdout(mode), stderr(), mode),
                                      (stdout(mode), stderr(mode), "pristine"),
                                      (stdout(mode).replace(FINITE_FINAL, ""), stderr(mode), mode),
                                      (stdout(mode).replace("operations=260", "operations=259"),
                                       stderr(mode), mode)):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                analyze(output, errors, search_mode=scope)
        with self.assertRaisesRegex(ValueError, "undeclared search mode"):
            analyze(stdout(), stderr(), search_mode="invented")

    def test_missing_duplicate_reordered_and_diagnostics_rejected(self):
        lines = stdout().splitlines()
        for changed in (lines[1:], [lines[0], *lines[0:-1]],
                        [lines[1], lines[0], *lines[2:]], [*lines, "extra"]):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    analyze("\n".join(changed), stderr())
        with self.assertRaises(ValueError):
            analyze(stdout(), "leftover stream warning")

    def test_changed_scope_and_timing_promotion_rejected(self):
        for before, after in (("operations=36", "operations=35"),
                              ("timing_admitted=false", "timing_admitted=true"),
                              ("segments=10", "segments=1"),
                              ("arm=original_cache", "arm=registered_cache")):
            with self.subTest(before=before):
                with self.assertRaises(ValueError):
                    analyze(stdout().replace(before, after, 1), stderr())

    def test_width_warnings_are_not_silently_ignored(self):
        for changed in ("", stderr() + "warning\n", stderr().replace("WARNING", "other", 1),
                        stderr() + "\n".join(WARNING_PAIR) + "\n"):
            with self.subTest(stderr=changed):
                with self.assertRaises(ValueError):
                    analyze(stdout(), changed)

    def test_adapter_flags_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            resident = command(folder, folder, "resident", "g++", folder / "probe")
            candidate = command(folder, folder, "bank_stream", "g++", folder / "probe")
            self.assertNotIn("-DGRASU_REGRAPH_BANK_STREAM=1", resident)
            self.assertIn("-DGRASU_REGRAPH_BANK_STREAM=1", candidate)
            self.assertIn("-DGRASU_REGRAPH_BANK_FIFO_LINES=256", candidate)
            self.assertIn("-DGRASU_REGRAPH_DIRECTORY_TILE_ROWS=1024", candidate)
            self.assertNotIn("-DWEIGHTED_FINITE_SEARCH", candidate)
            finite = command(folder, folder, "bank_stream", "g++", folder / "probe",
                             search_mode="finite_pipeline")
            self.assertIn("-DWEIGHTED_FINITE_SEARCH", finite)
            self.assertIn("-D_GTHREAD_USE_COND_INIT_FUNC", finite)
            with self.assertRaises(ValueError):
                command(folder, folder, "invented", "g++", folder / "probe")
            with self.assertRaises(ValueError):
                command(folder, folder, "resident", "g++", folder / "probe", search_mode="invented")

    def test_finite_source_is_frozen_with_the_composition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream, integration = root / "upstream", root / "integration"
            paths = [upstream / name for name in
                     ("kernel_config.h", "kernel_bin_search.cpp", "kernel_process_cache.cpp")]
            paths += [integration / name for name in (
                "include/weighted_pma_graph.hpp", "repos/GraSU/GraSU/GraSU_kernels/src/kernel_config.h",
                "repos/GraSU/GraSU/GraSU_kernels/src/kernel_dispatch.cpp",
                "kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp")]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("frozen fixture\n")
            output = root / "attempt"
            pins = prepare(output, upstream, integration, search_mode="finite_pipeline")
            names = [Path(pin["path"]).relative_to(output / "source").as_posix() for pin in pins]
            for name in ("search_pipeline/top.cpp", "search_pipeline/search_worker.hpp",
                         "search_pipeline/finite_host.hpp", "finite_search.hpp"):
                self.assertIn(name, names)
            self.assertEqual(len(set(names)), len(names))


if __name__ == "__main__":
    unittest.main()
