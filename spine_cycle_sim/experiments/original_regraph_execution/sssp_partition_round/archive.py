"""Losslessly compact the existing sealed tar format for repository delivery."""

import gzip
import hashlib
import lzma
import shutil
import tarfile
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..sssp_real_round.delivery import seal


def seal_compact(files, archive):
    if archive.exists():
        raise ValueError("refuse to overwrite evidence archive")
    # Reuse the established safety/member/source checks without changing its
    # hash-frozen implementation. Only the lossless compression format changes.
    with tempfile.TemporaryDirectory(prefix="sssp-archive-", dir=archive.parent) as temporary:
        from pathlib import Path
        packed = Path(temporary) / "sealed.tar.gz"
        index = seal(files, packed)
        with gzip.open(packed, "rb") as source, lzma.open(archive, "xb", preset=6) as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
    with tarfile.open(archive, "r:xz") as bundle:
        if bundle.getnames() != [row["path"] for row in index]:
            raise ValueError("compacted archive membership changed")
        for row in index:
            with bundle.extractfile(row["path"]) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != row["sha256"]:
                    raise ValueError("compacted archive bytes changed")
    if any(sha256_file(path) != row["sha256"] for (path, _), row in zip(files, index, strict=True)):
        raise ValueError("source changed during compression")
    return index
