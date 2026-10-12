"""Extract only indexed regular evidence files, with bounded size and exact hashes."""

from contextlib import contextmanager
import hashlib
from pathlib import Path
import tarfile
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


@contextmanager
def extracted(archive: Path, record: dict, *, max_bytes: int):
    if sha256_file(archive) != record["archive_sha256"] or archive.stat().st_size != record["archive_bytes"]:
        raise ValueError("sealed model archive differs")
    entries = record["files"]
    expected = {row["path"]: row for row in entries}
    if (len(expected) != len(entries) or sum(row["bytes"] for row in entries) > max_bytes
            or any(Path(name).is_absolute() or ".." in Path(name).parts for name in expected)):
        raise ValueError("unsafe or duplicate evidence index")
    with tempfile.TemporaryDirectory() as temporary, tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        if len(members) != len(entries) or {row.name for row in members} != expected.keys():
            raise ValueError("evidence archive membership differs")
        root = Path(temporary)
        for member in members:
            item = expected[member.name]
            if not member.isfile() or member.size != item["bytes"]:
                raise ValueError("evidence member type or size differs")
            with stream.extractfile(member) as content:
                data = content.read()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("evidence member hash differs")
            path = root / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        yield root
