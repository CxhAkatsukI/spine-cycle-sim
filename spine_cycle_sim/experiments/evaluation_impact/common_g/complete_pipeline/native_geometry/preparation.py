"""Freeze native coverage separately from existing real-input and route pins."""

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..host_prepared.preparation import command as real_command, prepare as real_prepare
from .analysis import CONTRACT


def prepare(output, upstream, integration):
    pins, _ = real_prepare(output, upstream, integration)
    root = Path(__file__).resolve().parents[6]
    groups = {"native_geometry": sorted((root / "cpp/tests/evaluation_impact/common_g/complete_pipeline/native_geometry").glob("*.?pp")),
              "runner/native_geometry": sorted(Path(__file__).parent.glob("*.py"))}
    for group, paths in groups.items():
        if not paths:
            raise ValueError("native coverage source group is empty: " + group)
        target = output / "source" / group
        target.mkdir(parents=True)
        for path in paths:
            frozen = target / path.name
            shutil.copy2(path, frozen)
            digest = sha256_file(frozen)
            if sha256_file(path) != digest:
                raise ValueError("native source changed during freeze")
            pins.append({"original": str(path), "path": str(frozen), "sha256": digest})
    atomic_write_json(output / "native_contract.json", CONTRACT)
    pins.append({"path": str(output / "native_contract.json"), "sha256": sha256_file(output / "native_contract.json")})
    return pins


def command(source, include, compiler, binary):
    argv = real_command(source, include, compiler, binary)
    argv[argv.index(str(source / "host_prepared/control.cpp"))] = str(source / "native_geometry/control.cpp")
    return argv
