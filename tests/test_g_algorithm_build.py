"""Portable source and algorithm/ABI admission tests; no vendor tools."""

import copy
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import commands, inputs, study


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def fixture(root, algorithm):
    source = root / "source"
    packet = root / "packet"
    lines = []
    kernels = commands.PURE if algorithm == "connected_components" else commands.PR
    for kernel in sorted(kernels):
        flags = []
        relative = "integration/kernels/" + kernel + "/top.cpp"
        if kernel == "bin_search":
            relative = "integration/kernels/grasu_complete/search_binding/top.cpp"
        if kernel == "process_cache":
            relative = "integration/kernels/grasu_complete/process_cache.cpp"
            flags.append("-DCACHE_BANK_REGISTERED")
        if kernel in ("process_cache", "process_ddr") and algorithm == "connected_components":
            flags.append("-DGRASU_ENABLE_COMPLETION_TOKEN")
        if kernel == "pma_to_regraph_adapter":
            flags.extend("-DGRASU_REGRAPH_" + flag for flag in sorted(commands.BANK_FLAGS))
        if kernel in ("regraph_pagerank_apply", "regraph_pagerank_source_prepare"):
            flags.append("-DGRASU_REGRAPH_PAGERANK_MODE=" + ("1" if algorithm == "full_pagerank" else "2"))
        cpp = source / relative
        config = packet / "config" / (kernel + ".cfg")
        write(cpp, "// test source\n")
        write(config, "kernel=" + kernel + "\n")
        argv = ["v++", "--target", "hw", "--compile", "--kernel_frequency", "150",
                "--config", str(config), "-o", str(packet / "build" / (kernel + ".xo")),
                *flags, str(cpp)]
        lines.append(shlex.join(argv))
    write(packet / "compile_commands.sh", "#!/bin/bash\n" + "\n".join(lines) + "\n")
    return source, packet


class AlgorithmCommandsTests(unittest.TestCase):
    def test_complete_kernel_sets_and_exact_tool(self):
        for algorithm in inputs.ALGORITHMS:
            with self.subTest(algorithm=algorithm), tempfile.TemporaryDirectory() as temporary:
                source, packet = fixture(Path(temporary), algorithm)
                rows = commands.compile_list(packet, algorithm, "/explicit/v++", source)
                self.assertEqual(len(rows), 11 if algorithm == "connected_components" else 12)
                self.assertTrue(all(row["argv"][0] == "/explicit/v++" for row in rows))

    def test_reject_changed_clock_target_missing_duplicate_or_escaped_source(self):
        mutations = (lambda text: text.replace("--kernel_frequency 150", "--kernel_frequency 200", 1),
                     lambda text: text.replace("--target hw", "--target sw_emu", 1),
                     lambda text: "\n".join(text.splitlines()[:-1]),
                     lambda text: text + text.splitlines()[1] + "\n")
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                source, packet = fixture(Path(temporary), "connected_components")
                file = packet / "compile_commands.sh"
                file.write_text(mutate(file.read_text()))
                with self.assertRaises(ValueError):
                    commands.compile_list(packet, "connected_components", "/tool", source)
        with tempfile.TemporaryDirectory() as temporary:
            source, packet = fixture(Path(temporary), "connected_components")
            file = packet / "compile_commands.sh"
            file.write_text(file.read_text().replace(str(source), "/outside-source", 1))
            with self.assertRaisesRegex(ValueError, "escaped"):
                commands.compile_list(packet, "connected_components", "/tool", source)

    def test_reject_abi_policy_and_mode_changes(self):
        changes = (("connected_components", "-DGRASU_REGRAPH_BANK_STREAM=1", ""),
                   ("connected_components", "-DGRASU_REGRAPH_ROW_LINE_READ=1",
                    "-DGRASU_REGRAPH_ROW_LINE_READ=1 -DGRASU_REGRAPH_ROW_LINE_READ=0"),
                   ("connected_components", "-DCACHE_BANK_REGISTERED", "-DGRASU_PURE_PIPELINE_DIRECT_CACHE"),
                   ("connected_components", "-DGRASU_ENABLE_COMPLETION_TOKEN", ""),
                   ("residual_pagerank", "-DCACHE_BANK_REGISTERED",
                    "-DCACHE_BANK_REGISTERED -DGRASU_ENABLE_COMPLETION_TOKEN"),
                   ("residual_pagerank", "-DGRASU_REGRAPH_PAGERANK_MODE=2", "-DGRASU_REGRAPH_PAGERANK_MODE=1"))
        for algorithm, before, after in changes:
            with self.subTest(algorithm=algorithm, before=before), tempfile.TemporaryDirectory() as temporary:
                source, packet = fixture(Path(temporary), algorithm)
                file = packet / "compile_commands.sh"
                file.write_text(file.read_text().replace(before, after, 1))
                with self.assertRaises(ValueError):
                    commands.compile_list(packet, algorithm, "/tool", source)


class AlgorithmInputsTests(unittest.TestCase):
    def prepare(self, root):
        integration, grasu, regraph = (root / name for name in ("integration", "GraSU", "ReGraph"))
        for owner, members in ((integration, ("kernels", "include", "scripts")),
                               (grasu, ("GraSU/GraSU_kernels/src", "GraSU/GraSU/src", "u55c_hbm/config")),
                               (regraph, ("acc_template", "acc_udfs"))):
            for member in members:
                write(owner / member / "fixture.h", "// source\n")
        subprocess.run(["git", "init", "-q", str(integration)], check=True)
        subprocess.run(["git", "-C", str(integration), "add", "."], check=True)
        subprocess.run(["git", "-C", str(integration), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
        output = root / "frozen"
        manifest = inputs.prepare(integration, grasu, regraph, output)
        return integration, grasu, regraph, output, manifest

    def test_freeze_is_portable_and_does_not_claim_hardware(self):
        with tempfile.TemporaryDirectory() as temporary:
            integration, grasu, regraph, output, manifest = self.prepare(Path(temporary))
            for root in (integration, grasu, regraph):
                shutil.rmtree(root)
            moved = output.parent / "moved"
            output.rename(moved)
            self.assertEqual(inputs.verify(moved), manifest)
            self.assertTrue(all(manifest[key] is False for key in inputs.CLAIMS))

    def test_changed_unindexed_duplicate_or_unsafe_source_fails(self):
        mutations = (lambda m: m.update(board_admitted=True),
                     lambda m: m["files"].append(m["files"][0]),
                     lambda m: m["files"][0].update(member="../escape"),
                     lambda m: m["files"][0].update(member=""),
                     lambda m: m["files"].pop())
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temporary:
                _, _, _, output, manifest = self.prepare(Path(temporary))
                changed = copy.deepcopy(manifest)
                mutate(changed)
                write(output / "sources.json", json.dumps(changed))
                with self.assertRaises(ValueError):
                    inputs.verify(output)
        for mode in ("changed", "unindexed"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                _, _, _, output, manifest = self.prepare(Path(temporary))
                member = manifest["files"][0]["member"] if mode == "changed" else "source/extra.h"
                write(output / member, "changed")
                with self.assertRaises(ValueError):
                    inputs.verify(output)

    def test_dirty_source_cannot_be_frozen(self):
        with tempfile.TemporaryDirectory() as temporary:
            integration, grasu, regraph, _, _ = self.prepare(Path(temporary))
            write(integration / "include/fixture.h", "uncommitted")
            with self.assertRaisesRegex(ValueError, "commit"):
                inputs.prepare(integration, grasu, regraph, Path(temporary) / "second")

    def test_generation_is_explicit_per_algorithm(self):
        for algorithm in inputs.ALGORITHMS:
            with self.subTest(algorithm=algorithm):
                argv, env = inputs.generation(Path("/sources"), Path("/out"), algorithm,
                                              Path("/tools"), Path("/platform.xpfm"))
                self.assertEqual(commands.value(argv, "--algorithm"), algorithm)
                self.assertEqual(commands.value(argv, "--adapter-policy"), "bank-stream")
                self.assertEqual(commands.value(argv, "--grasu-implementation"), "complete-search-cache")
                self.assertEqual(env["GRI_ROOT"], "/sources/source/integration")

    def test_unbounded_service_cannot_start_tools_and_retains_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, _, source, _ = self.prepare(root)
            group = root / "cgroup"
            write(group / "memory.events", "oom 0\noom_kill 0\n")
            output = root / "compile"
            with patch.object(study, "current", return_value=group), \
                    patch.object(study, "verify", side_effect=ValueError("unbounded")), \
                    patch.object(study.environment, "capture") as capture:
                with self.assertRaisesRegex(ValueError, "unbounded"):
                    study.run(source, output, "connected_components", root / "tools",
                              root / "platform", root / "compatibility", root / "shim")
                capture.assert_not_called()
            report = json.loads((output / "execution.json").read_text())
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertTrue(all(report[key] is False for key in inputs.CLAIMS))


if __name__ == "__main__":
    unittest.main()
