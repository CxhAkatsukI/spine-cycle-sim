"""Source packaging must preserve receipts and never rebuild a running host."""

import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.figure8_fpga import sources


class SourceParsers(unittest.TestCase):
    def test_dependencies_normalize_deduplicate_and_unescape(self):
        text = ("/tmp/output.o: /tmp/src/../host.cpp \\\n"
                " /tmp/space\\ name.hpp /tmp/host.cpp /tmp/hash\\#name.hpp\n"
                "/tmp/space\\ name.hpp:\n")
        self.assertEqual(sources.dependencies(text), {
            Path("/tmp/host.cpp"), Path("/tmp/space name.hpp"), Path("/tmp/hash#name.hpp")})

    def test_dependencies_reject_bad_rules_and_relative_paths(self):
        for text in ("no dependency separator", "output.o: relative.cpp"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                sources.dependencies(text)

    def test_source_hashes_preserve_spaces_and_normalize_paths(self):
        digest = "a" * 64
        text = f"{digest}  /tmp/sub/../space name.hpp\n{digest}  /tmp/space name.hpp\n"
        self.assertEqual(sources.source_hashes(text), {Path("/tmp/space name.hpp"): digest})

    def test_source_hashes_reject_invalid_or_conflicting_pins(self):
        for text in ("not a manifest", "g" * 64 + "  /tmp/a",
                     "a" * 63 + "  /tmp/a", "a" * 64 + " /tmp/a",
                     "a" * 64 + "  relative.cpp",
                     "a" * 64 + "  /tmp/a\n" + "b" * 64 + "  /tmp/a\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                sources.source_hashes(text)

    def test_commands_keep_flags_comments_continuations_and_quoted_paths(self):
        text = ("# compiler receipt\n"
                "prlimit --as=4294967296 timeout 180 g++ -O3 -DNDEBUG \\\n"
                " -Wl,-rpath,/opt/xrt/lib '/tmp/source tree/host.cpp' -o /tmp/host\n")
        argv, indices = sources.commands(text)
        self.assertEqual(indices, [4])
        self.assertEqual(argv, [["prlimit", "--as=4294967296", "timeout", "180", "g++",
                                 "-O3", "-DNDEBUG", "-Wl,-rpath,/opt/xrt/lib",
                                 "/tmp/source tree/host.cpp", "-o", "/tmp/host"]])

    def test_commands_reject_empty_receipts_shell_operators_and_ambiguous_compilers(self):
        for text in ("# no command", "echo build", "g++ c++ /tmp/a.cpp",
                     "g++ /tmp/a.cpp && echo done", "g++ /tmp/a.cpp > /tmp/log"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                sources.commands(text)


class SourceArchive(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="fig8 source tests ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.build = self.root / "build"
        self.output = self.root / "hosts.tar.gz"
        self.arm_sources, self.receipts = {}, {}
        for arm, (_, host_name) in sources.SOURCE_MACROS.items():
            directory = self.build / arm
            production = self.root / "frozen sources" / arm
            wrapper = self.root / "wrappers" / f"{arm}_persistent.cpp"
            host = production / host_name
            header = production / "include" / "shared header.hpp"
            paths = [wrapper, host, header]
            if arm == "spine":
                paths.append(production / "xcl2.cpp")
            for index, path in enumerate(paths):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"// frozen synthetic {arm} source {index}\n")
            self.arm_sources[arm] = paths
            directory.mkdir(parents=True)
            self.write_pins(arm)
            depfile = directory / f"{arm}_persistent.d"
            depfile.write_text(str(directory / "host.o") + ": \\\n " +
                               " \\\n ".join(str(path).replace(" ", "\\ ") for path in paths[:3]) + "\n")
            flags = ["g++", "-std=c++17", "-O3", "-DNDEBUG", "-DMAX_N=16777216",
                     "-I" + str(header.parent), "-I/fixture/sdk/include"]
            if arm == "gr":
                commands = [["prlimit", "--as=4294967296", "timeout", "180", *flags,
                             "-MMD", "-MF", str(depfile), str(wrapper),
                             "-L/fixture/sdk/lib", "-Wl,-rpath,/fixture/sdk/lib",
                             "-o", str(directory / "gr_persistent")]]
            else:
                xcl_dep = directory / "xcl2.d"
                xcl_dep.write_text(str(directory / "xcl2.o") + ": " +
                                   str(paths[3]).replace(" ", "\\ ") + "\n")
                commands = [[*flags, "-MMD", "-MF", str(depfile), "-MT", str(directory / "host.o"),
                             "-c", str(wrapper), "-o", str(directory / "host.o")],
                            [*flags, "-MMD", "-MF", str(xcl_dep), "-c", str(paths[3]),
                             "-o", str(directory / "xcl2.o")],
                            ["g++", str(directory / "host.o"), str(directory / "xcl2.o"),
                             "-o", str(directory / "spine_persistent.host"),
                             "-L/fixture/sdk/lib", "-Wl,-rpath,/fixture/sdk/lib"]]
            receipt = directory / ("build.command.txt" if arm == "gr" else "build_commands.txt")
            receipt.write_text("# exact synthetic commands\n" +
                               "\n\n".join(shlex.join(command) for command in commands) + "\n")
            self.receipts[arm] = receipt
            (directory / "not-packaged.o").write_bytes(b"object must be omitted")
            (directory / "not-packaged.host").write_bytes(b"binary must be omitted")

    def write_pins(self, arm, paths=None):
        paths = self.arm_sources[arm] if paths is None else paths
        pin = self.build / arm / "non_system_dependencies.sha256"
        pin.write_text("".join(hashlib.sha256(path.read_bytes()).hexdigest() +
                               "  " + str(path) + "\n" for path in paths))
        return pin

    def package(self):
        result = sources.archive(self.build, self.output)
        with tarfile.open(self.output, "r:gz") as stream:
            files = {}
            for member in stream.getmembers():
                self.assertTrue(member.isfile())
                self.assertFalse(Path(member.name).is_absolute())
                self.assertNotIn("..", Path(member.name).parts)
                files[member.name] = stream.extractfile(member).read()
        return result, files

    def extract_for_dry_run(self, files):
        destination = self.root / "extracted archive with spaces"
        for name, data in files.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return destination

    def dry_run(self, destination, *arguments, check=True):
        # A dry-run regression must not invoke a real compiler, even on failure.
        return subprocess.run([sys.executable, str(destination / "build.py"), "--dry-run",
                               "--cxx", "/nonexistent/no-compiler-allowed", *arguments],
                              check=check, text=True, capture_output=True, timeout=15)

    def test_archive_preserves_sources_receipts_and_all_checksums(self):
        originals = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        result, files = self.package()
        self.assertEqual(result["source_files"], {"gr": 3, "spine": 4})
        self.assertEqual(result["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(result["size_bytes"], self.output.stat().st_size)
        self.assertEqual(result["files"], len(files))
        manifest = json.loads(files["manifest.json"])
        checksums = {}
        for line in files["SHA256SUMS"].decode().splitlines():
            digest, name = line.split("  ", 1)
            checksums[name] = digest
        self.assertEqual(checksums.keys(), files.keys() - {"SHA256SUMS"})
        for name, expected in checksums.items():
            self.assertEqual(hashlib.sha256(files[name]).hexdigest(), expected)
        for name, expected in manifest["files"].items():
            self.assertEqual(hashlib.sha256(files[name]).hexdigest(), expected)
        for path, data in originals.items():
            self.assertEqual(path.read_bytes(), data)
            if path.suffix not in (".host", ".o"):
                self.assertEqual(files["files/" + str(path).lstrip("/")], data)
        self.assertFalse(any(name.endswith((".host", ".o")) for name in files))
        self.assertIn("build.py", files)
        self.assertIn("README.txt", files)

    def test_dry_run_relocates_sources_outputs_macros_and_preserves_flags(self):
        _, files = self.package()
        destination = self.extract_for_dry_run(files)
        result = self.dry_run(destination)
        commands = [shlex.split(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(commands), 4)
        for arm, (macro, _) in sources.SOURCE_MACROS.items():
            wrapper = self.arm_sources[arm][0]
            extracted_wrapper = destination / "files" / wrapper.relative_to("/")
            command = next(command for command in commands if str(extracted_wrapper) in command)
            host = destination / "files" / self.arm_sources[arm][1].relative_to("/")
            self.assertIn(f'-D{macro}="{host}"', command)
            for flag in ("-O3", "-DNDEBUG", "-DMAX_N=16777216", "-I/fixture/sdk/include"):
                self.assertIn(flag, command)
            include = destination / "files" / self.arm_sources[arm][2].parent.relative_to("/")
            self.assertIn("-I" + str(include), command)
        for command in commands:
            self.assertIn("/nonexistent/no-compiler-allowed", command)
            for index, value in enumerate(command):
                if value in ("-o", "-MF", "-MT"):
                    self.assertTrue(Path(command[index + 1]).is_relative_to(destination / "rebuilt"))
                if value.endswith((".cpp", ".o")):
                    self.assertTrue(Path(value).is_relative_to(destination))
        self.assertFalse((destination / "rebuilt").exists())

    def test_dry_run_selects_arm_and_explicitly_maps_sdk_prefixes(self):
        _, files = self.package()
        destination = self.extract_for_dry_run(files)
        result = self.dry_run(destination, "--arm", "gr", "--path-map", "/fixture/sdk=/new sdk",
                              "--path-map", "/fixture=/less-specific")
        commands = [shlex.split(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(commands), 1)
        for flag in ("-I/new sdk/include", "-L/new sdk/lib", "-Wl,-rpath,/new sdk/lib"):
            self.assertIn(flag, commands[0])
        self.assertFalse((destination / "rebuilt").exists())

    def test_dry_run_rejects_invalid_sdk_mapping(self):
        _, files = self.package()
        destination = self.extract_for_dry_run(files)
        for mapping in ("missing-separator", "relative=/absolute", "/absolute=relative"):
            with self.subTest(mapping=mapping):
                result = self.dry_run(destination, "--path-map", mapping, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("absolute OLD=NEW", result.stderr)
        self.assertFalse((destination / "rebuilt").exists())

    def test_hash_mismatch_rejects_archive_before_creation(self):
        self.arm_sources["gr"][0].write_text("// changed after source pinning\n")
        with self.assertRaisesRegex(ValueError, "source hash mismatch"):
            sources.archive(self.build, self.output)
        self.assertFalse(self.output.exists())

    def test_dependency_without_pin_rejects_archive_before_creation(self):
        self.write_pins("spine", self.arm_sources["spine"][:-1])
        with self.assertRaisesRegex(ValueError, "dependencies lack source hashes"):
            sources.archive(self.build, self.output)
        self.assertFalse(self.output.exists())

    def test_missing_dependency_receipt_rejects_archive(self):
        (self.build / "gr" / "gr_persistent.d").unlink()
        with self.assertRaisesRegex(ValueError, "missing dependency files"):
            sources.archive(self.build, self.output)
        self.assertFalse(self.output.exists())

    def test_g_source_manifest_fallback_is_supported_and_archived(self):
        pin = self.build / "gr" / "non_system_dependencies.sha256"
        fallback = pin.with_name("gr_persistent.sources.sha256")
        pin.rename(fallback)
        result, files = self.package()
        self.assertEqual(result["source_files"]["gr"], 3)
        self.assertEqual(files["files/" + str(fallback).lstrip("/")], fallback.read_bytes())

    def test_existing_archive_is_not_overwritten(self):
        self.output.write_bytes(b"frozen prior archive")
        with self.assertRaises(FileExistsError):
            sources.archive(self.build, self.output)
        self.assertEqual(self.output.read_bytes(), b"frozen prior archive")

    def test_cli_packages_synthetic_build_without_compiling(self):
        result = subprocess.run([sys.executable, "-m", sources.__name__,
                                 "--build-root", str(self.build), "--output", str(self.output)],
                                check=True, text=True, capture_output=True, timeout=15)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["path"], str(self.output))
        self.assertEqual(receipt["source_files"], {"gr": 3, "spine": 4})
        self.assertEqual(receipt["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
