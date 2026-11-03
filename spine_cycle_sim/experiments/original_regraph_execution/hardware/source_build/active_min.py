"""Prepare explicit min-label CC and weighted SSSP A4 source overlays."""

from pathlib import Path
import shutil
import subprocess

from .. import artifact
from . import configuration as config, snapshot


def validate_input(topology: str, algorithm: str, weighted_udf: Path | None) -> None:
    config.validate_algorithm(topology, algorithm)
    if (weighted_udf is not None) != (algorithm == "weighted_sssp"):
        raise ValueError("a pinned weighted UDF is required only for weighted_sssp")


def prepare(root: Path, source: Path, output: Path, *, topology: str, algorithm: str,
            weighted_udf: Path | None) -> dict:
    validate_input(topology, algorithm, weighted_udf)
    if algorithm == "pr":
        return {"algorithm": "pr", "pins": [], "little_entry": None}

    inputs = root / "cpp/tests/original_regraph/hardware"
    destination = output / "algorithm"
    udf = destination / "udf/l2.h"
    udf.parent.mkdir(parents=True)
    little_entry = None
    if algorithm == "cc":
        original = inputs / "cc_min_label/l2.h"
        pins = [artifact.identity(original)]
        shutil.copy2(original, udf)
    else:
        helper = inputs / "sssp_weighted"
        script = helper / "prepare.py"
        assert weighted_udf is not None
        pins = [artifact.identity(path) for path in (script, helper / "edge_word.hpp", weighted_udf)]
        derivation = destination / "derivation"
        subprocess.run([str(config.GENERATOR_PYTHON), str(script), str(source),
                        str(weighted_udf), str(derivation)], check=True, timeout=30)
        little = destination / "little"
        shutil.copytree(source / "acc_template/kernel_little_gs", little)
        for name in ("acc_scatter.h", "kernel_scatter_gather.cpp", "edge_word.hpp"):
            shutil.copy2(derivation / name, little / name)
        shutil.copy2(derivation / "l2.h", udf)
        little_entry = str(little / "kernel_scatter_gather.cpp")
    snapshot.unchanged(pins)
    pins += [artifact.identity(path) for path in sorted(destination.rglob("*")) if path.is_file()]
    return {"algorithm": algorithm, "pins": pins, "little_entry": little_entry,
            "changes": ["min-label CC UDF"] if algorithm == "cc" else
                       ["weighted SSSP UDF", "Little compact weight decoding"]}


def check_apply_bank(connectivity: Path, topology: str, algorithm: str) -> None:
    expected = config.argument_names("kernelApply", topology, algorithm=algorithm)[0]
    bindings = [line.strip() for line in connectivity.read_text().splitlines()
                if line.strip().startswith("sp=kernelApply_1.")]
    if bindings != [f"sp=kernelApply_1.{expected}:HBM[30]"]:
        raise ValueError("generated Apply state port must occupy the original HBM[30] bank")
