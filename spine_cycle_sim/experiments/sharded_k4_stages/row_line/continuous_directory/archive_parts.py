"""Transport the unchanged sealed archive below GitHub's per-file limit."""

from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file

ARCHIVE = "raw_continuous_directory.tar.gz"
PART_BYTES = 64 * 1024**2


def split(archive, destination, *, part_bytes=PART_BYTES):
    if not 0 < part_bytes <= PART_BYTES or destination.exists():
        raise ValueError("bounded parts and a fresh destination required")
    destination.mkdir(parents=True)
    parts = []
    with archive.open("rb") as source:
        while data := source.read(part_bytes):
            name = f"{ARCHIVE}.part{len(parts) + 1:02d}"
            path = destination / name
            with path.open("xb") as output:
                output.write(data)
            parts.append({"path": name, "bytes": len(data), "sha256": sha256_file(path)})
    if not parts:
        raise ValueError("empty archive")
    return parts


@contextmanager
def assembled(destination, record):
    if "archive_parts" not in record:
        yield destination / ARCHIVE
        return
    parts = record["archive_parts"]
    if (not parts or len(parts) > 8 or type(record["archive_bytes"]) is not int
            or sum(item["bytes"] for item in parts) != record["archive_bytes"]):
        raise ValueError("archive part geometry differs")
    with tempfile.TemporaryDirectory(prefix="continuous-archive-") as temporary:
        archive = Path(temporary) / ARCHIVE
        with archive.open("xb") as output:
            for number, item in enumerate(parts, 1):
                name = f"{ARCHIVE}.part{number:02d}"
                path = destination / name
                if (item["path"] != name or type(item["bytes"]) is not int
                        or not 0 < item["bytes"] <= PART_BYTES
                        or path.is_symlink() or path.stat().st_size != item["bytes"]
                        or sha256_file(path) != item["sha256"]):
                    raise ValueError("archive part identity differs")
                with path.open("rb") as source:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        if sha256_file(archive) != record["archive_sha256"]:
            raise ValueError("reassembled archive hash differs")
        yield archive
