"""Relocation changes dependency paths, not compile flags or numerical models."""

from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh import environment, study


class FigureEnvironmentTests(unittest.TestCase):
    def test_default_plugin_command_is_unchanged(self):
        implicit = study.plugin_command("c++", Path("core"), Path("plugin"))
        explicit = study.plugin_command("c++", Path("core"), Path("plugin"),
            sst_include=Path("/data/feiyang/sst/include"), dram=study.DRAM)
        self.assertEqual(implicit, explicit)
        self.assertIn("-O3", implicit)
        self.assertIn("-DNDEBUG", implicit)
        self.assertIn("-I/data/feiyang/sst/include", implicit)

    def test_relocated_plugin_replaces_only_environment_paths(self):
        command = study.plugin_command("c++", Path("core"), Path("plugin"),
                                      sst_include=Path("headers"), dram=Path("dram"))
        self.assertIn("-Iheaders", command)
        self.assertIn("-Idram/src", command)
        self.assertIn("-Ldram", command)
        self.assertIn("-Wl,-rpath,dram", command)
        self.assertNotIn("-I/data/feiyang/sst/include", command)

    def test_embedded_python_is_scoped_to_sst_not_supervisor(self):
        selected = environment.Environment(Path("compiler"), Path("sst"), Path("include"),
            Path("dram"), Path("python"), Path("pylib/libpython.so"))
        self.assertEqual(selected.prefix(), ["env", "LD_LIBRARY_PATH=dram:pylib", "PYTHONHOME=python"])
        self.assertIn("same host", selected.description()["host_timing_cohort"])

    def test_sst_uses_only_the_explicit_plugin_directory(self):
        selected = environment.Environment(Path("compiler"), Path("sst"),
                                           Path("include"), Path("dram"))
        command = selected.sst_command(cpu=7, library=Path("fresh-build"),
            configuration=Path("config.py"), parameters=Path("input.json"))
        self.assertEqual(command, ["env", "LD_LIBRARY_PATH=dram", "taskset", "-c", "7",
            "sst", "--no-env-config", "--lib-path=fresh-build", "config.py", "--", "input.json"])
        self.assertFalse(any(arg.startswith("--add-lib-path") for arg in command))

    def test_dependency_inventory_includes_headers_python_and_shared_library(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            names = ("compiler", "sst", "include/sst/config.h", "dram/libdramsim3.so",
                     "dram/src/dramsim3.h", "python/lib/os.py", "pylib/libpython.so")
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            selected = environment.Environment(*(root / name for name in
                ("compiler", "sst", "include", "dram", "python", "pylib/libpython.so")))
            self.assertEqual(set(selected.inputs()), {root / name for name in names})
            (root / "pylib/libpython.so").unlink()
            with self.assertRaisesRegex(ValueError, "dependency missing"):
                selected.inputs()

    def test_python_paths_must_be_paired(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "header").write_text("header")
            selected = environment.Environment(root / "compiler", root / "sst", root,
                                               root / "dram", root / "python")
            with self.assertRaisesRegex(ValueError, "specified together"):
                selected.inputs()


if __name__ == "__main__":
    unittest.main()
