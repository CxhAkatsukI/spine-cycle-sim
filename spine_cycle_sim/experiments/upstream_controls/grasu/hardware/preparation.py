"""Prepare a relocatable, byte-exact author-kernel packet from a clean revision."""

import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ..preparation import author_snapshot
from . import configuration as config


def checked_files(packet):
    expected = {"packet.json", "link.cfg", *["source/" + name for name in config.SOURCE_HASHES]}
    actual = {str(path.relative_to(packet)) for path in packet.rglob("*") if path.is_file()}
    if actual != expected or any(path.is_symlink() for path in packet.rglob("*")):
        raise ValueError("original G packet has missing, extra or symbolic files")
    for name, digest in config.SOURCE_HASHES.items():
        if sha256_file(packet / "source" / name) != digest:
            raise ValueError("byte-exact original G source required: " + name)
    if (packet / "link.cfg").read_text() != config.connectivity():
        raise ValueError("original G connectivity changed")
    return [identity(packet / name) for name in sorted(expected)]


def verify(packet):
    record = json.loads((packet / "packet.json").read_text())
    if record != contract():
        raise ValueError("original G packet contract differs")
    return checked_files(packet)


def contract():
    return {"schema_version": 1, "revision": config.REVISION, "clock_mhz": config.CLOCK_MHZ,
            "kernels": config.KERNELS, "source_hashes": config.SOURCE_HASHES,
            "memory_interfaces": 46, "segment_slots": 16, "cache_segments_per_half": 131072,
            "cache_storage": "original_URAM", "policy": config.POLICY,
            "claim": "original_source_U55C_150MHz_control_not_U250_200MHz_publication_reproduction",
            **dict.fromkeys(config.FLAGS, False)}


def prepare(root, upstream, packet):
    author = author_snapshot(root, upstream)
    if author["revision"] != config.REVISION:
        raise ValueError("wrong original G revision")
    source = upstream / config.SOURCE_DIRECTORY
    for name, digest in config.SOURCE_HASHES.items():
        if sha256_file(source / name) != digest:
            raise ValueError("original G build source does not match the clean snapshot")
    packet.mkdir(parents=True, exist_ok=False)
    (packet / "source").mkdir()
    for name in config.SOURCE_HASHES:
        shutil.copyfile(source / name, packet / "source" / name)
    (packet / "link.cfg").write_text(config.connectivity(), encoding="ascii")
    atomic_write_json(packet / "packet.json", contract())
    if author_snapshot(root, upstream) != author:
        raise ValueError("upstream changed while copying original G")
    return verify(packet)
