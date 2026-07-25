"""Reproducible CACTI-P and execution-driven energy evidence.

The ledger deliberately keeps three claim domains separate:

* DRAMSim3 reports HBM energy for the simulated memory command stream;
* CACTI-P characterizes selected ASIC SRAM arrays; and
* simulator counters provide dynamic read/write activity for those arrays.

It does not reinterpret either source as FPGA board power or as complete
accelerator energy.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Iterable


_FLOAT_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_CACTI_SOURCE_PATTERNS = ("*.cc", "*.h", "*.mk", "makefile")
_CLAIM_CLASS = "simulated_activity_plus_dramsim3_and_cacti_selected_arrays"


class EnergyEvidenceError(ValueError):
    """Raised when energy evidence is incomplete, inconsistent, or mislabeled."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_content(path: Path) -> tuple[bytes, dict[str, Any]]:
    archive = path.read_bytes()
    try:
        content = gzip.decompress(archive) if path.suffix == ".gz" else archive
    except gzip.BadGzipFile as exc:
        raise EnergyEvidenceError(f"invalid gzip artifact: {path}") from exc
    return content, {
        "path": str(path),
        "archive_sha256": _sha256(archive),
        "content_sha256": _sha256(content),
        "archive_bytes": len(archive),
        "content_bytes": len(content),
        "compression": "gzip" if path.suffix == ".gz" else "none",
    }


def _resolve(root: Path, path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _validated_content(
    root: Path, artifact: dict[str, Any], context: str
) -> tuple[bytes, dict[str, Any]]:
    required = {"path", "archive_sha256", "content_sha256"}
    if not isinstance(artifact, dict) or set(artifact) != required:
        raise EnergyEvidenceError(f"{context} artifact fields must be {sorted(required)}")
    content, identity = _read_content(_resolve(root, artifact["path"]))
    for key in ("archive_sha256", "content_sha256"):
        if identity[key] != artifact[key]:
            raise EnergyEvidenceError(
                f"{context} {key} mismatch: expected {artifact[key]}, "
                f"got {identity[key]}"
            )
    identity["path"] = artifact["path"]
    return content, identity


def cacti_source_files(source_dir: str | Path) -> list[Path]:
    """Return the compilation-relevant CACTI-P source set in stable order."""

    root = Path(source_dir)
    files: set[Path] = set()
    for pattern in _CACTI_SOURCE_PATTERNS:
        files.update(path for path in root.glob(pattern) if path.is_file())
    if not files or not (root / "cacti.mk").is_file():
        raise EnergyEvidenceError(f"CACTI-P source tree is incomplete: {root}")
    return sorted(files, key=lambda path: path.name)


def cacti_source_identity(source_dir: str | Path) -> dict[str, Any]:
    """Hash names and bytes, excluding generated objects and binaries."""

    root = Path(source_dir)
    digest = hashlib.sha256()
    entries = []
    for path in cacti_source_files(root):
        data = path.read_bytes()
        name = path.relative_to(root).as_posix()
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
        entries.append({"path": name, "sha256": _sha256(data), "bytes": len(data)})
    return {
        "tree_sha256": digest.hexdigest(),
        "file_count": len(entries),
        "files": entries,
    }


def build_cacti_p(
    source_dir: str | Path, build_dir: str | Path, *, jobs: int = 2
) -> dict[str, Any]:
    """Build the 2014 CACTI-P source with a pinned 64-bit compatibility patch."""

    source = Path(source_dir)
    build = Path(build_dir)
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    for path in cacti_source_files(source):
        shutil.copy2(path, build / path.name)

    makefile_path = build / "cacti.mk"
    makefile = makefile_path.read_text(encoding="utf-8")
    old = "CXX = g++ -m32\nCC  = gcc -m32"
    new = "CXX = g++\nCC  = gcc"
    if makefile.count(old) != 1:
        raise EnergyEvidenceError(
            "CACTI-P cacti.mk does not match the pinned -m32 compatibility patch"
        )
    makefile_path.write_text(makefile.replace(old, new), encoding="utf-8")
    command = ["make", f"NTHREADS=1", f"-j{jobs}"]
    completed = subprocess.run(
        command,
        cwd=build,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or not (build / "cacti").is_file():
        raise EnergyEvidenceError(
            "CACTI-P build failed:\n" + completed.stdout + completed.stderr
        )
    binary = build / "cacti"
    return {
        "binary": str(binary),
        "binary_sha256": _sha256(binary.read_bytes()),
        "command": command,
        "compatibility_patch": {
            "scope": "build_copy_only",
            "before": old,
            "after": new,
            "reason": "host has no 32-bit libstdc++ development headers",
        },
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _positive_int(spec: dict[str, Any], key: str, default: int | None = None) -> int:
    value = spec.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EnergyEvidenceError(f"CACTI geometry {key} must be a positive integer")
    return value


def _nonnegative_int(spec: dict[str, Any], key: str, default: int = 0) -> int:
    value = spec.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EnergyEvidenceError(f"CACTI geometry {key} must be a nonnegative integer")
    return value


def render_cacti_config(spec: dict[str, Any]) -> str:
    """Render the constrained scratchpad configuration used by this project."""

    size = _positive_int(spec, "size_bytes")
    word = _positive_int(spec, "word_bytes")
    banks = _positive_int(spec, "banks", 1)
    technology_nm = _positive_int(spec, "technology_nm", 32)
    temperature_k = _positive_int(spec, "temperature_k", 350)
    rw_ports = _nonnegative_int(spec, "read_write_ports")
    read_ports = _nonnegative_int(spec, "read_ports")
    write_ports = _nonnegative_int(spec, "write_ports")
    if rw_ports + read_ports + write_ports == 0:
        raise EnergyEvidenceError("CACTI geometry requires at least one memory port")
    if size % word != 0 or word > size:
        raise EnergyEvidenceError("CACTI size_bytes must be divisible by word_bytes")
    if technology_nm not in (22, 32, 40, 45, 65, 90):
        raise EnergyEvidenceError(f"unsupported CACTI-P technology node: {technology_nm}")

    technology_um = technology_nm / 1000.0
    return f"""# Generated by spine-cycle-sim; do not hand edit.
-size (bytes) {size}
-Power Gating - \"false\"
-Power Gating Performance Loss 0.01
-block size (bytes) {word}
-associativity 1
-read-write port {rw_ports}
-exclusive read port {read_ports}
-exclusive write port {write_ports}
-single ended read ports 0
-search port 0
-UCA bank count {banks}
-technology (u) {technology_um:.3f}
-page size (bits) 8192
-burst length 8
-internal prefetch width 8
-Data array cell type - \"itrs-hp\"
-Data array peripheral type - \"itrs-hp\"
-Tag array cell type - \"itrs-hp\"
-Tag array peripheral type - \"itrs-hp\"
-hp Vdd (V) \"default\"
-lstp Vdd (V) \"default\"
-lop Vdd (V) \"default\"
-DVS(V): 0.8 1.1 1.3 1.4 1.5
-Long channel devices - \"false\"
-Powergating voltage (V) 0
-output/input bus width {word * 8}
-operating temperature (K) {temperature_k}
-cache type \"ram\"
-tag size (b) 0
-access mode (normal, sequential, fast) - \"normal\"
-design objective (weight delay, dynamic power, leakage power, cycle time, area) 0:0:0:100:0
-deviate (delay, dynamic power, leakage power, cycle time, area) 100000:100000:100000:20:100000
-NUCAdesign objective (weight delay, dynamic power, leakage power, cycle time, area) 100:100:0:0:100
-NUCAdeviate (delay, dynamic power, leakage power, cycle time, area) 10:10000:10000:10000:10000
-Optimize ED or ED^2 (ED, ED^2, NONE): \"NONE\"
-Cache model (NUCA, UCA) - \"UCA\"
-NUCA bank count 0
-Wire signalling (fullswing, lowswing, default) - \"default\"
-Wire inside mat - \"semi-global\"
-Wire outside mat - \"semi-global\"
-Interconnect projection - \"conservative\"
-Core count 4
-Cache level (L2/L3) - \"L2\"
-Add ECC - \"false\"
-Print level (DETAILED, CONCISE) - \"CONCISE\"
-Print input parameters - \"true\"
-Force cache config - \"false\"
-Ndwl 1
-Ndbl 1
-Nspd 0
-Ndcm 1
-Ndsam1 0
-Ndsam2 0
"""


def _line_number(text: str, label: str) -> float:
    match = re.search(
        rf"^\s*{re.escape(label)}\s*:\s*(?P<value>{_FLOAT_RE})",
        text,
        re.MULTILINE,
    )
    if not match:
        raise EnergyEvidenceError(f"CACTI-P output lacks {label!r}")
    value = float(match.group("value"))
    if not math.isfinite(value) or value < 0:
        raise EnergyEvidenceError(f"invalid CACTI-P value for {label}: {value}")
    return value


def parse_cacti_output(text: str) -> dict[str, Any]:
    """Parse baseline-DVS scratchpad timing, energy, leakage, and area."""

    if "CACTI-P" not in text or "array type                    : Scratch RAM" not in text:
        raise EnergyEvidenceError("output is not a successful CACTI-P Scratch RAM run")
    if "User defined Vdd is too low" in text:
        raise EnergyEvidenceError("CACTI-P rejected the configured voltage")
    dimensions = re.search(
        rf"^\s*Cache height x width \(mm\):\s*(?P<height>{_FLOAT_RE})\s*x\s*"
        rf"(?P<width>{_FLOAT_RE})\s*$",
        text,
        re.MULTILINE,
    )
    if not dimensions:
        raise EnergyEvidenceError("CACTI-P output lacks array dimensions")
    height = float(dimensions.group("height"))
    width = float(dimensions.group("width"))
    best: dict[str, float | int] = {}
    for key, label, cast in (
        ("ndwl", "Best Ndwl", int),
        ("ndbl", "Best Ndbl", int),
        ("nspd", "Best Nspd", float),
        ("ndcm", "Best Ndcm", int),
        ("ndsam1", "Best Ndsam L1", int),
        ("ndsam2", "Best Ndsam L2", int),
    ):
        best[key] = cast(_line_number(text, label))
    return {
        "tool": "CACTI-P 6.5 (June 2014)",
        "claim_label": "projected_asic_sram_characterization",
        "geometry": {
            "size_bytes": int(_line_number(text, "Total cache size (bytes)")),
            "banks": int(_line_number(text, "Number of banks")),
            "word_bytes": int(_line_number(text, "Block size (bytes)")),
            "read_write_ports": int(_line_number(text, "Read/write Ports")),
            "read_ports": int(_line_number(text, "Read ports")),
            "write_ports": int(_line_number(text, "Write ports")),
            "technology_nm": int(_line_number(text, "Technology size (nm)")),
        },
        "access_time_ns": _line_number(text, "Access time (ns)"),
        "cycle_time_ns": _line_number(text, "Cycle time (ns)"),
        "read_energy_nj": _line_number(
            text, "Total dynamic read energy per access (nJ)"
        ),
        "write_energy_nj": _line_number(
            text, "Total dynamic write energy per access (nJ)"
        ),
        "leakage_power_mw": _line_number(
            text,
            "Total leakage power of a bank without power gating, including its network outside (mW)",
        ),
        "height_mm": height,
        "width_mm": width,
        "area_mm2": height * width,
        "organization": best,
    }


def run_cacti(binary: str | Path, config: str, work_dir: str | Path) -> dict[str, Any]:
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    config_path = work / "array.cfg"
    config_path.write_text(config, encoding="utf-8")
    completed = subprocess.run(
        [str(Path(binary).resolve()), "-infile", config_path.name],
        cwd=work,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise EnergyEvidenceError(
            f"CACTI-P failed with exit {completed.returncode}:\n"
            + completed.stdout
            + completed.stderr
        )
    parsed = parse_cacti_output(completed.stdout)
    return {
        "config": config,
        "config_sha256": _sha256(config.encode("utf-8")),
        "stdout": completed.stdout,
        "stdout_sha256": _sha256(completed.stdout.encode("utf-8")),
        "stderr": completed.stderr,
        "result": parsed,
    }


def _json_path(document: Any, path: str) -> Any:
    current = document
    for token in path.split(".") if path else ():
        if isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise EnergyEvidenceError(f"activity JSON path not found: {path}")
    return current


def _numeric_sum(value: Any, context: str) -> float:
    if isinstance(value, bool):
        raise EnergyEvidenceError(f"boolean is not an activity count: {context}")
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or value < 0:
            raise EnergyEvidenceError(f"invalid activity value at {context}: {value}")
        return float(value)
    if isinstance(value, list):
        return sum(_numeric_sum(item, context) for item in value)
    if isinstance(value, dict):
        return sum(_numeric_sum(item, context) for item in value.values())
    raise EnergyEvidenceError(f"non-numeric activity value at {context}")


def activity_count(document: Any, terms: list[dict[str, Any]], context: str) -> int:
    if not isinstance(terms, list):
        raise EnergyEvidenceError(f"{context} terms must be a list")
    total = 0.0
    for term in terms:
        if not isinstance(term, dict) or set(term) not in ({"path"}, {"path", "multiplier"}):
            raise EnergyEvidenceError(f"invalid activity term in {context}: {term!r}")
        multiplier = term.get("multiplier", 1)
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)):
            raise EnergyEvidenceError(f"invalid activity multiplier in {context}")
        total += _numeric_sum(_json_path(document, term["path"]), term["path"]) * multiplier
    rounded = round(total)
    if total < 0 or abs(total - rounded) > 1e-9:
        raise EnergyEvidenceError(f"{context} does not resolve to an integer count: {total}")
    return int(rounded)


def _bundle_digest(items: Iterable[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(items):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def _dramsim_count(row: dict[str, Any], key: str, path: Path) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EnergyEvidenceError(f"{path} has invalid nonnegative count {key}")
    return value


def _dramsim_energy(row: dict[str, Any], key: str, path: Path) -> float:
    value = row.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise EnergyEvidenceError(f"{path} has invalid nonnegative energy {key}")
    return float(value)


def aggregate_dramsim3(
    root: Path, spec: dict[str, Any], context: str
) -> dict[str, Any]:
    required = {"directory", "glob", "expected_files", "content_bundle_sha256"}
    if not isinstance(spec, dict) or set(spec) != required:
        raise EnergyEvidenceError(f"{context} DRAM fields must be {sorted(required)}")
    directory = _resolve(root, spec["directory"])
    files = sorted(directory.glob(spec["glob"]))
    if len(files) != spec["expected_files"]:
        raise EnergyEvidenceError(
            f"{context} expected {spec['expected_files']} DRAM files, found {len(files)}"
        )
    totals = {
        "reads": 0,
        "writes": 0,
        "activates": 0,
        "precharges": 0,
        "total_energy_pj": 0.0,
    }
    bundle_items = []
    identities = []
    for file in files:
        content, identity = _read_content(file)
        try:
            document = json.loads(content)
        except json.JSONDecodeError as exc:
            raise EnergyEvidenceError(f"invalid DRAMSim3 JSON: {file}") from exc
        if not isinstance(document, dict) or len(document) != 1:
            raise EnergyEvidenceError(f"unexpected DRAMSim3 JSON root: {file}")
        row = next(iter(document.values()))
        if not isinstance(row, dict):
            raise EnergyEvidenceError(f"unexpected DRAMSim3 channel row: {file}")
        for output, key in (
            ("reads", "num_reads_done"),
            ("writes", "num_writes_done"),
            ("activates", "num_act_cmds"),
            ("precharges", "num_pre_cmds"),
        ):
            totals[output] += _dramsim_count(row, key, file)
        totals["total_energy_pj"] += _dramsim_energy(row, "total_energy", file)
        relative = file.relative_to(directory).as_posix()
        bundle_items.append((relative, content))
        identity["path"] = relative
        identities.append(identity)
    observed_bundle = _bundle_digest(bundle_items)
    if observed_bundle != spec["content_bundle_sha256"]:
        raise EnergyEvidenceError(
            f"{context} DRAM content bundle mismatch: expected "
            f"{spec['content_bundle_sha256']}, got {observed_bundle}"
        )
    return {
        **totals,
        "content_bundle_sha256": observed_bundle,
        "files": identities,
        "claim_label": "dramsim3_hbm_only",
    }


def _validate_characterization_geometry(
    expected: dict[str, Any], observed: dict[str, Any], char_id: str
) -> None:
    for key in (
        "size_bytes",
        "word_bytes",
        "banks",
        "read_write_ports",
        "read_ports",
        "write_ports",
        "technology_nm",
    ):
        default = 1 if key == "banks" else 32 if key == "technology_nm" else 0
        if expected.get(key, default) != observed[key]:
            raise EnergyEvidenceError(
                f"{char_id} geometry mismatch for {key}: expected "
                f"{expected.get(key, default)}, got {observed[key]}"
            )


def _load_characterizations(
    root: Path, entries: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    results: dict[str, dict[str, Any]] = {}
    ledger = []
    for entry in entries:
        char_id = entry.get("characterization_id")
        if not isinstance(char_id, str) or not char_id or char_id in results:
            raise EnergyEvidenceError(f"invalid or duplicate characterization_id: {char_id!r}")
        geometry = entry.get("geometry")
        if not isinstance(geometry, dict):
            raise EnergyEvidenceError(f"{char_id} lacks geometry")
        expected_config = render_cacti_config(geometry).encode("utf-8")
        config, config_identity = _validated_content(root, entry["config"], f"{char_id}.config")
        if config != expected_config:
            raise EnergyEvidenceError(f"{char_id} archived config is not canonical")
        output, output_identity = _validated_content(root, entry["output"], f"{char_id}.output")
        try:
            output_text = output.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EnergyEvidenceError(f"{char_id} output is not UTF-8") from exc
        parsed = parse_cacti_output(output_text)
        _validate_characterization_geometry(geometry, parsed["geometry"], char_id)
        results[char_id] = parsed
        ledger.append(
            {
                "characterization_id": char_id,
                "geometry": geometry,
                "result": parsed,
                "config_identity": config_identity,
                "output_identity": output_identity,
            }
        )
    return results, ledger


def analyze_energy_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Validate a frozen energy manifest and produce a selected-array ledger."""

    path = Path(manifest_path)
    manifest_bytes = path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise EnergyEvidenceError(f"invalid energy manifest: {path}") from exc
    if manifest.get("schema_version") != 1:
        raise EnergyEvidenceError("only energy schema_version=1 is supported")
    if manifest.get("claim_class") != _CLAIM_CLASS:
        raise EnergyEvidenceError("unsafe or unsupported energy claim class")
    repository_root = manifest.get("repository_root")
    if not isinstance(repository_root, str) or not repository_root:
        raise EnergyEvidenceError("energy manifest lacks repository_root")
    root = (path.resolve().parent / repository_root).resolve()
    chars, char_ledger = _load_characterizations(
        root, manifest.get("characterizations", [])
    )
    if not chars:
        raise EnergyEvidenceError("energy manifest has no CACTI characterizations")

    runs = manifest.get("runs")
    if not isinstance(runs, list) or not runs:
        raise EnergyEvidenceError("energy manifest has no runs")
    run_results = []
    seen_runs: set[str] = set()
    for run in runs:
        run_id = run.get("run_id")
        if not isinstance(run_id, str) or not run_id or run_id in seen_runs:
            raise EnergyEvidenceError(f"invalid or duplicate run_id: {run_id!r}")
        seen_runs.add(run_id)
        activity_bytes, activity_identity = _validated_content(
            root, run["activity"], f"{run_id}.activity"
        )
        try:
            activity = json.loads(activity_bytes)
        except json.JSONDecodeError as exc:
            raise EnergyEvidenceError(f"invalid activity JSON for {run_id}") from exc
        profile_bytes, profile_identity = _validated_content(
            root, run["profile"], f"{run_id}.profile"
        )
        try:
            profile = json.loads(profile_bytes)
        except json.JSONDecodeError as exc:
            raise EnergyEvidenceError(f"invalid architecture profile for {run_id}") from exc
        if profile.get("profile_id") != run["profile_id"]:
            raise EnergyEvidenceError(
                f"{run_id} profile_id mismatch: expected {run['profile_id']}, "
                f"got {profile.get('profile_id')}"
            )
        assertions = run.get("activity_assertions")
        if not isinstance(assertions, list) or not assertions:
            raise EnergyEvidenceError(f"{run_id} requires activity identity assertions")
        for assertion in assertions:
            if not isinstance(assertion, dict) or set(assertion) != {"path", "equals"}:
                raise EnergyEvidenceError(f"{run_id} has an invalid activity assertion")
            observed = _json_path(activity, assertion["path"])
            if observed != assertion["equals"]:
                raise EnergyEvidenceError(
                    f"{run_id} assertion failed at {assertion['path']}: "
                    f"expected {assertion['equals']!r}, got {observed!r}"
                )
        success = _json_path(activity, run["success_path"])
        mismatches = _json_path(activity, run["correctness_mismatches_path"])
        if success is not True or mismatches != 0:
            raise EnergyEvidenceError(
                f"{run_id} activity is correctness-ineligible: "
                f"success={success!r}, mismatches={mismatches!r}"
            )
        cycles = activity_count(
            activity, [{"path": run["cycles_path"]}], f"{run_id}.cycles"
        )
        clock_mhz = run.get("clock_mhz")
        if not isinstance(clock_mhz, (int, float)) or clock_mhz <= 0:
            raise EnergyEvidenceError(f"{run_id} has invalid clock_mhz")
        profile_clocks = profile.get("clocks")
        if not isinstance(profile_clocks, list):
            raise EnergyEvidenceError(f"{run_id} profile has no clocks")
        matching_clocks = [
            clock for clock in profile_clocks if clock.get("name") == run["clock_name"]
        ]
        if len(matching_clocks) != 1 or abs(
            float(matching_clocks[0].get("achieved_mhz", -1)) - float(clock_mhz)
        ) > 1e-9:
            raise EnergyEvidenceError(f"{run_id} clock does not match its profile")
        runtime_ns = cycles * 1000.0 / float(clock_mhz)
        dram = aggregate_dramsim3(root, run["dram"], run_id)
        backend_requests = activity_count(
            activity,
            [{"path": run["backend_requests_path"]}],
            f"{run_id}.backend_requests",
        )
        if dram["reads"] + dram["writes"] != backend_requests:
            raise EnergyEvidenceError(
                f"{run_id} DRAM requests do not close: "
                f"{dram['reads']}+{dram['writes']} != {backend_requests}"
            )

        arrays = []
        onchip_dynamic = 0.0
        onchip_leakage = 0.0
        onchip_area = 0.0
        for array in run.get("arrays", []):
            char_id = array.get("characterization_id")
            if char_id not in chars:
                raise EnergyEvidenceError(f"{run_id} references unknown {char_id!r}")
            if array.get("activity_scope") != "total_physical_array_accesses":
                raise EnergyEvidenceError(
                    f"{run_id}.{array.get('array_id')} has ambiguous activity scope"
                )
            instances = _positive_int(array, "instances")
            reads = activity_count(
                activity, array.get("read_terms", []), f"{run_id}.{array['array_id']}.reads"
            )
            writes = activity_count(
                activity,
                array.get("write_terms", []),
                f"{run_id}.{array['array_id']}.writes",
            )
            char = chars[char_id]
            dynamic = (
                reads * char["read_energy_nj"] + writes * char["write_energy_nj"]
            ) * 1000.0
            leakage = char["leakage_power_mw"] * instances * runtime_ns
            area = char["area_mm2"] * instances
            onchip_dynamic += dynamic
            onchip_leakage += leakage
            onchip_area += area
            arrays.append(
                {
                    "array_id": array["array_id"],
                    "hardware_mapping": array["hardware_mapping"],
                    "characterization_id": char_id,
                    "instances": instances,
                    "reads": reads,
                    "writes": writes,
                    "dynamic_energy_pj": dynamic,
                    "leakage_energy_pj": leakage,
                    "selected_array_energy_pj": dynamic + leakage,
                    "projected_asic_sram_area_mm2": area,
                    "claim_label": "selected_array_projected_asic_sram",
                }
            )
        if not arrays:
            raise EnergyEvidenceError(f"{run_id} has no selected on-chip arrays")
        selected = onchip_dynamic + onchip_leakage
        run_results.append(
            {
                "run_id": run_id,
                "system": run["system"],
                "profile_id": run["profile_id"],
                "comparison_role": run["comparison_role"],
                "claim_label": run["claim_label"],
                "cycles": cycles,
                "clock_mhz": float(clock_mhz),
                "runtime_ns": runtime_ns,
                "backend_requests": backend_requests,
                "dram": dram,
                "selected_onchip": {
                    "dynamic_energy_pj": onchip_dynamic,
                    "leakage_energy_pj": onchip_leakage,
                    "total_energy_pj": selected,
                    "projected_asic_sram_area_mm2": onchip_area,
                    "arrays": arrays,
                    "coverage": run["selected_array_coverage"],
                    "claim_label": "partial_selected_array_energy_not_total_accelerator",
                },
                "partial_energy_ledger": {
                    "dram_energy_pj": dram["total_energy_pj"],
                    "selected_onchip_energy_pj": selected,
                    "sum_pj": dram["total_energy_pj"] + selected,
                    "claim_label": "partial_sum_not_total_accelerator_energy",
                },
                "activity_identity": activity_identity,
                "profile_identity": profile_identity,
                "omitted_energy": run["omitted_energy"],
            }
        )

    try:
        display = str(path.resolve().relative_to(root))
    except ValueError:
        display = str(path.resolve())
    return {
        "schema_version": 1,
        "claim_class": _CLAIM_CLASS,
        "status": "PASS",
        "manifest": display,
        "manifest_sha256": _sha256(manifest_bytes),
        "cacti": manifest["cacti"],
        "characterizations": char_ledger,
        "runs": run_results,
        "limitations": manifest["limitations"],
    }


def reproduce_cacti_characterizations(
    manifest_path: str | Path,
    source_dir: str | Path,
    work_dir: str | Path,
) -> dict[str, Any]:
    """Rebuild CACTI-P and require byte-identical pinned characterizations."""

    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = (manifest_path.resolve().parent / manifest["repository_root"]).resolve()
    identity = cacti_source_identity(source_dir)
    expected_source = manifest["cacti"]["source_tree_sha256"]
    if identity["tree_sha256"] != expected_source:
        raise EnergyEvidenceError(
            f"CACTI source mismatch: expected {expected_source}, "
            f"got {identity['tree_sha256']}"
        )
    work = Path(work_dir)
    build = build_cacti_p(source_dir, work / "build")
    reproductions = []
    for entry in manifest["characterizations"]:
        char_id = entry["characterization_id"]
        run = run_cacti(
            build["binary"], render_cacti_config(entry["geometry"]), work / char_id
        )
        expected_config, _ = _validated_content(root, entry["config"], f"{char_id}.config")
        expected_output, _ = _validated_content(root, entry["output"], f"{char_id}.output")
        if run["config"].encode("utf-8") != expected_config:
            raise EnergyEvidenceError(f"{char_id} regenerated config differs")
        if run["stdout"].encode("utf-8") != expected_output:
            raise EnergyEvidenceError(f"{char_id} regenerated CACTI output differs")
        reproductions.append(
            {
                "characterization_id": char_id,
                "config_sha256": run["config_sha256"],
                "output_sha256": run["stdout_sha256"],
                "status": "PASS",
            }
        )
    return {
        "status": "PASS",
        "source_identity": identity,
        "build": build,
        "characterizations": reproductions,
    }
