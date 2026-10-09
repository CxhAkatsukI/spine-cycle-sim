"""Damage isolated source inputs and observed packets; never rewrite accepted evidence."""

from pathlib import Path
import shutil
import struct
import tempfile

from .analysis import analyze

INPUT_NEGATIVES = (
    ("header", "adapter.u32le", 0, 0, "descriptor header"),
    ("assignment", "adapter.u32le", 10, 3, "task assignment/geometry"),
    ("row_bounds", "rows.u32le", 0, 1, "contiguous row bounds"),
    ("destination", "pma.u32le", 0, 65536, "local destination domain"),
    ("edge_value", "pma.u32le", 0, None, "logical edge multiset changed"),
    ("truncated", "pma.u32le", None, None, "row/PMA extent"),
)


def input_negatives(binary: Path, source: Path, output: Path, execute):
    records = []
    for name, filename, word, value, diagnostic in INPUT_NEGATIVES:
        directory = output / "negative" / name; inputs, capture = directory / "input", directory / "capture"
        inputs.mkdir(parents=True); capture.mkdir()
        for path in source.iterdir():
            if path.name != filename: (inputs / path.name).symlink_to(path)
        target = inputs / filename; shutil.copyfile(source / filename, target)
        with target.open("r+b") as stream:
            if word is None: stream.truncate(4)
            else:
                stream.seek(word * 4)
                if value is None:
                    value = struct.unpack("<I", stream.read(4))[0] ^ 1; stream.seek(word * 4)
                stream.write(struct.pack("<I", value))
        step = execute("negative_" + name, [str(binary), str(inputs), str(capture)], expected_code=1)
        if diagnostic not in Path(step["stderr"]).read_text(): raise ValueError("adapter negative hit wrong gate: " + name)
        records.append({"id": name, "rejected": True, "diagnostic": diagnostic})
    return records


def capture_negatives(inputs: Path, capture: Path, stdout: Path, stderr: Path):
    records = []
    with tempfile.TemporaryDirectory(prefix="adapter-capture-negative-") as temporary:
        directory = Path(temporary); payload = directory / "adapter_edges.u32le"; out = directory / "out"; err = directory / "err"
        for name in ("source", "destination", "truncated", "trailing", "counter", "diagnostic"):
            shutil.copyfile(capture / payload.name, payload); shutil.copyfile(stdout, out); shutil.copyfile(stderr, err)
            with payload.open("r+b") as stream:
                if name in ("source", "destination"):
                    offset = 0 if name == "source" else 4; stream.seek(offset); value = struct.unpack("<I", stream.read(4))[0] ^ 1
                    stream.seek(offset); stream.write(struct.pack("<I", value))
                elif name == "truncated": stream.truncate(payload.stat().st_size - 8)
                elif name == "trailing": stream.seek(0, 2); stream.write(b"\0")
            if name == "counter": out.write_text(out.read_text().replace('"passed":true', '"passed":1'))
            if name == "diagnostic": err.write_text("runtime error: injected UB\n")
            expected = "packet value/order" if name in ("source", "destination") else "extent" if name in ("truncated", "trailing") else "counters" if name == "counter" else "diagnostics"
            try: analyze(inputs, directory, out, err)
            except ValueError as error:
                if expected not in str(error): raise ValueError("adapter capture hit wrong gate: " + name) from error
                records.append({"id": name, "rejected": True, "diagnostic": str(error)})
            else: raise ValueError("adapter damaged capture accepted: " + name)
    return records
