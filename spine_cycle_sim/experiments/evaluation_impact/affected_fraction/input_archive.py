"""Archive exact updates without copying a full old graph for every point."""

import io
from pathlib import Path
import tarfile


def update_text(path, expected_vertices, expected_edges, expected_updates):
    with Path(path).open() as stream:
        header = tuple(map(int, next(stream).split()))
        if header != (expected_vertices, expected_edges, expected_updates):
            raise ValueError("graph header differs from the frozen CPU manifest")
        for _ in range(expected_edges):
            next(stream)
        rows = []
        for _ in range(expected_updates):
            fields = tuple(map(int, next(stream).split()))
            if len(fields) != 4 or fields[3] != 1:
                raise ValueError("expected four-field insertion records")
            rows.append(" ".join(map(str, fields)) + "\n")
        if stream.read().strip():
            raise ValueError("unexpected records after the declared updates")
    return "".join(rows).encode("ascii")


def archive_updates(manifests, output):
    with tarfile.open(output, "w:gz") as archive:
        for index, manifest in enumerate(manifests):
            for point in manifest["points"]:
                name = point["name"]
                if Path(name).name != name or name in (".", ".."):
                    raise ValueError("unsafe point name")
                data = update_text(point["graph"]["path"], manifest["vertices"],
                                   manifest["edges"], point["updates"])
                entry = tarfile.TarInfo(f"campaign-{index}/{name}.updates.txt")
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
