from pathlib import Path
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware import control_build as build


class ControlBuildTests(unittest.TestCase):
    def command(self, variant="release", target="control"):
        return build.command(Path("compiler"), Path("source"), Path("binary"), Path("deps"), variant, target)

    def test_explicit_xilinx_link_and_runpath_not_generic_opencl(self):
        for variant in ("release", "ubsan"):
            with self.subTest(variant=variant):
                command = self.command(variant)
                self.assertIn(str(build.XRT / "lib/libxilinxopencl.so"), command)
                self.assertIn("-Wl,-rpath," + str(build.XRT / "lib"), command)
                self.assertNotIn("-lOpenCL", command)
                self.assertEqual("-fsanitize=undefined" in command, variant == "ubsan")
                self.assertIn("-Werror", command)

    def test_model_tests_do_not_link_or_load_opencl(self):
        command = self.command(target="model_tests")
        self.assertFalse(any("libxilinxopencl" in token or "rpath" in token for token in command))

    def test_unknown_build_or_target_rejected(self):
        for variant, target in (("debug", "control"), ("release", "other")):
            with self.assertRaises(ValueError):
                self.command(variant, target)

    def test_loader_requires_exact_pinned_runtime_without_diagnostics(self):
        expected = Path("/opt/xilinx/xrt/lib/libxilinxopencl.so.2.18.179")
        with patch.object(build, "runtime_inputs", return_value=[expected]), \
                patch.object(build, "library_paths", return_value=[expected]):
            self.assertEqual(build.resolved_libraries("loader output", ""), [expected])
            with self.assertRaisesRegex(ValueError, "diagnostic"):
                build.resolved_libraries("loader output", "warning")
        with patch.object(build, "runtime_inputs", return_value=[expected]), \
                patch.object(build, "library_paths", return_value=[Path("/other/libxilinxopencl.so.2")]):
            with self.assertRaisesRegex(ValueError, "explicitly pinned"):
                build.resolved_libraries("loader output", "")

    def test_existing_runtime_gate_rejects_cuda_icd_and_missing_libraries(self):
        for output in ("libOpenCL.so.1 => /cuda/libOpenCL.so.1 (0x1)", "dependency => not found"):
            with patch("pathlib.Path.resolve", autospec=True, side_effect=lambda path, **_: path), \
                    self.assertRaises(ValueError):
                build.resolved_libraries(output, "")


if __name__ == "__main__":
    unittest.main()
