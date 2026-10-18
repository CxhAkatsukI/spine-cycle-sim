"""Explicit XRT host and pure-schedule builds; this command admits no bitstream."""

from ..control_build import XRT, resolved_libraries, runtime_inputs
from .build import flags


def command(compiler, source, production, binary, dependency, variant, target):
    if target not in ("control", "schedule_tests"):
        raise ValueError("named guarded K4 board-host target required")
    result = [str(compiler), *flags(variant), "-MD", "-MF", str(dependency), "-MT", "probe",
              "-I" + str(production / "include"), "-I" + str(XRT / "include"),
              str(source / (target + ".cpp")), "-o", str(binary)]
    if target == "control":
        result += [str(XRT / "lib/libxilinxopencl.so"), "-Wl,-rpath," + str(XRT / "lib")]
    return result
