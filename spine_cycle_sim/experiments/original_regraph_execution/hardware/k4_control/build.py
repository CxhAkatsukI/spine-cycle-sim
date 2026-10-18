"""Explicit offline model build; production headers, no vendor runtime or FPGA."""

def command(compiler, source, production, binary, dependency, variant, target):
    if variant not in ("release", "ubsan") or target not in ("offline", "model_tests"):
        raise ValueError("named offline variant/target required")
    flags = (["-O2", "-DNDEBUG"] if variant == "release" else
             ["-O1", "-g", "-fsanitize=undefined", "-fno-sanitize-recover=all"])
    return [str(compiler), "-std=c++20", *flags, "-fno-fast-math", "-ffp-contract=off",
            "-Wall", "-Wextra", "-Werror", "-MD", "-MF", str(dependency), "-MT", "probe",
            "-I" + str(production / "include"), str(source / (target + ".cpp")),
            "-o", str(binary)]
