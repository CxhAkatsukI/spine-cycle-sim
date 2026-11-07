"""Archive the declared persistent-host sources without rebuilding either host."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import tarfile


SOURCE_MACROS = {
    "gr": ("GRASU_PERSISTENT_HOST_SOURCE", "sharded_k4_native_host.cpp"),
    "spine": ("SPINE_SETUP_ONCE_HOST_SOURCE", "host_partitioned_algorithms_smoke.cpp"),
}

BUILD_SCRIPT = '''#!/usr/bin/env python3
"""Rebuild archived hosts into rebuilt/, never the original build directory."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess

root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text())
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--arm", choices=("gr", "spine", "all"), default="all")
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--cxx", default="g++", help="C++ compiler executable")
parser.add_argument("--path-map", action="append", default=[], metavar="OLD=NEW",
                    help="relocate an external SDK prefix, not archived sources")
args = parser.parse_args()
sdk_maps = []
for item in args.path_map:
    old, separator, new = item.partition("=")
    if not separator or not Path(old).is_absolute() or not Path(new).is_absolute():
        parser.error("--path-map requires absolute OLD=NEW paths")
    sdk_maps.append((Path(old), Path(new)))
sdk_maps.sort(key=lambda pair: len(str(pair[0])), reverse=True)
build_root = Path(manifest["build_root"])
sources = {Path(path) for arm in manifest["builds"].values() for path in arm["sources"]}

def relocate(value):
    if not value.startswith("/"):
        return value
    path = Path(os.path.normpath(value))
    if path.is_relative_to(build_root):
        return str(root / "rebuilt" / path.relative_to(build_root))
    if any(source == path or path in source.parents for source in sources):
        return str(root / "files" / path.relative_to("/"))
    for old, new in sdk_maps:
        if path.is_relative_to(old):
            return str(new / path.relative_to(old))
    return value

def argument(value):
    for prefix in ("-I", "-L", "-isystem", "-iquote", "-Wl,-rpath,"):
        if value.startswith(prefix + "/"):
            return prefix + relocate(value[len(prefix):])
    return relocate(value)

for arm, build in manifest["builds"].items():
    if args.arm not in (arm, "all"):
        continue
    work = root / "rebuilt" / arm
    if not args.dry_run:
        work.mkdir(parents=True, exist_ok=True)
    for recorded, compiler in zip(build["commands"], build["compiler_indices"]):
        command = [argument(value) for value in recorded]
        command[compiler] = args.cxx
        if any(Path(value).name == arm + "_persistent.cpp" for value in recorded):
            name, source = build["source_macro"]
            command.insert(compiler + 1, '-D' + name + '="' + relocate(source) + '"')
        print(shlex.join(command), flush=True)
        if not args.dry_run:
            subprocess.run(command, cwd=work, check=True)
'''

ARCHIVE_README = """Persistent Fig. 8 host source archive

files/<absolute path without leading slash> preserves frozen source layout.
manifest.json records both builds, source hashes and parsed original commands.
SHA256SUMS covers every other archive member. Original .d, command and hash
receipts are retained byte-for-byte under files/. Binaries, objects, graph
inputs, images and experiment results are deliberately not bundled.

Extract into a new directory; from that directory run:
  sha256sum -c SHA256SUMS
  python3 build.py --dry-run
  python3 build.py --arm gr
  python3 build.py --arm spine

Rebuilds write only to rebuilt/. No FPGA is launched. Install a compatible
C++17 compiler, XRT/OpenCL and Xilinx HLS/Vitis SDK headers separately. SDK
paths retain recorded defaults and can be relocated explicitly, for example:
  python3 build.py --path-map /opt/xilinx/xrt=/new/xrt --dry-run

Source/include and output paths are relocated, and GRASU_PERSISTENT_HOST_SOURCE
and SPINE_SETUP_ONCE_HOST_SOURCE select the extracted production sources.
No source bytes, optimization flags, capacity definitions or timing logic
are rewritten. The original binary hashes are provenance, not a guarantee
that another compiler/toolchain will produce bit-identical binaries.
"""


def absolute(value):
    path = Path(os.path.normpath(value))
    if not path.is_absolute():
        raise ValueError("absolute dependency paths required: " + str(path))
    return path


def dependencies(text):
    """Read the single-target GNU -MMD rules used by these two builds."""
    paths = set()
    for line in text.replace("\\\n", " ").splitlines():
        if not line.strip():
            continue
        _, separator, prerequisites = line.partition(":")
        if not separator:
            raise ValueError("invalid dependency rule: " + line)
        paths.update(absolute(path) for path in shlex.split(prerequisites, comments=True))
    return paths


def source_hashes(text):
    hashes = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, separator, name = line.partition("  ")
        if not separator or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid SHA-256 source manifest line: " + line)
        path = absolute(name)
        if path in hashes and hashes[path] != digest:
            raise ValueError("conflicting source hashes: " + str(path))
        hashes[path] = digest
    return hashes


def commands(text):
    parsed, indices = [], []
    for line in text.replace("\\\n", " ").splitlines():
        tokens = shlex.split(line, comments=True)
        if not tokens:
            continue
        compilers = [index for index, token in enumerate(tokens)
                     if Path(token).name in ("g++", "c++")]
        if len(compilers) != 1:
            raise ValueError("expected one C++ compiler in command: " + line)
        if any(token in (";", "&&", "||", "|", ">", "<") for token in tokens):
            raise ValueError("shell operators are not supported in build receipts")
        parsed.append(tokens)
        indices.append(compilers[0])
    if not parsed:
        raise ValueError("empty build command receipt")
    return parsed, indices


def archive(build_root, output):
    build_root, output = Path(build_root).resolve(), Path(output).absolute()
    files, builds = {}, {}

    def capture(path):
        path = absolute(str(path))
        name = "files/" + path.relative_to("/").as_posix()
        if name not in files:
            files[name] = path.read_bytes()
        return files[name]

    for arm, (macro, host_name) in SOURCE_MACROS.items():
        directory = build_root / arm
        depfiles = sorted(directory.glob("*.d"))
        if not depfiles:
            raise ValueError("missing dependency files in " + str(directory))
        declared = set()
        for path in depfiles:
            declared.update(dependencies(capture(path).decode()))
        pin = directory / "non_system_dependencies.sha256"
        if not pin.exists() and arm == "gr":
            pin = directory / "gr_persistent.sources.sha256"
        hashes = source_hashes(capture(pin).decode())
        missing = declared - hashes.keys()
        if missing:
            raise ValueError("dependencies lack source hashes: " + ", ".join(map(str, sorted(missing))))
        for path, expected in hashes.items():
            if hashlib.sha256(capture(path)).hexdigest() != expected:
                raise ValueError("source hash mismatch: " + str(path))
        hosts = [path for path in declared if path.name == host_name]
        if len(hosts) != 1:
            raise ValueError("expected one pinned host source: " + host_name)
        command_files = [path for path in directory.glob("*.txt") if "command" in path.name]
        if len(command_files) != 1:
            raise ValueError("expected one command receipt in " + str(directory))
        argv, indices = commands(capture(command_files[0]).decode())
        builds[arm] = dict(sources={str(path): digest for path, digest in sorted(hashes.items())},
                           commands=argv, compiler_indices=indices,
                           source_macro=[macro, str(hosts[0])])
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix in (".d", ".sha256", ".txt", ".md"):
                capture(path)
        for path in declared:
            if path.name == "gr_persistent.cpp":
                extra_pin = path.parent / "gr_source_pins.sha256"
                if extra_pin.exists():
                    capture(extra_pin)

    capture(Path(__file__).resolve())
    files["build.py"] = BUILD_SCRIPT.encode()
    files["README.txt"] = ARCHIVE_README.encode()
    manifest = dict(format=1, build_root=str(build_root), builds=builds,
                    files={name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())})
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    files["SHA256SUMS"] = "".join(hashlib.sha256(data).hexdigest() + "  " + name + "\n"
                                  for name, data in sorted(files.items())).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "x:gz") as stream:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name == "build.py" else 0o644
            stream.addfile(info, io.BytesIO(data))
    return dict(path=str(output), size_bytes=output.stat().st_size,
                sha256=hashlib.sha256(output.read_bytes()).hexdigest(), files=len(files),
                source_files={arm: len(build["sources"]) for arm, build in builds.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(archive(args.build_root, args.output), indent=2))


if __name__ == "__main__":
    main()
