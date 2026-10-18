"""Explicit offline model build; production headers, no vendor runtime or FPGA."""

def flags(variant):
    if variant not in ("release", "ubsan"):
        raise ValueError("named guarded variant required")
    optimization = (["-O2", "-DNDEBUG"] if variant == "release" else
                    ["-O1", "-g", "-fsanitize=undefined", "-fno-sanitize-recover=all"])
    return ["-std=c++20", *optimization, "-fno-fast-math", "-ffp-contract=off",
            "-Wall", "-Wextra", "-Werror"]


def command(compiler, source, production, binary, dependency, variant, target):
    if target not in ("offline", "model_tests"):
        raise ValueError("named offline variant/target required")
    return [str(compiler), *flags(variant), "-MD", "-MF", str(dependency), "-MT", "probe",
            "-I" + str(production / "include"), str(source / (target + ".cpp")),
            "-o", str(binary)]
