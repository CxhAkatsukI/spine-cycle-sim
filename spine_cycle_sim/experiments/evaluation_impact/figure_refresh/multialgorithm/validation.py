"""Reconcile CC/ResPR exports with frozen commands, states and physical ledgers."""

import hashlib
import json
import math
from pathlib import Path
import struct
import io
import tarfile

from .. import analysis
from ..matrix import HISTORICAL_ROOTS


EXPECTED = {(a, d) for a in ("SSSP", "CC", "ResPR") for d in ("AU", "SU", "WK")}


def replay_sources(replay, matrix):
    if replay.get("status") != "SSSP_READ_CREDIT_CORRECTION":
        raise ValueError("explicit read-credit replay status required")
    pins = {p["path"]: p for p in matrix["pins"]}
    shared = [p for p in replay["pins"] if p["path"] in pins]
    if (len([p for p in shared if p["path"].endswith(".a")]) != 2 or
            not any("/cpp/tests/evaluation_impact/" in p["path"] for p in shared) or
            any(p != pins[p["path"]] for p in shared)):
        raise ValueError("SSSP replay and matrix source/core identities differ")


def core_gates(report, matrix, read, prefix, *, expected_tests=39):
    if report.get("status") != "COMPLETE_CORE_GATES" or report.get("pins_unchanged") is not True:
        raise ValueError("successful unchanged core regression required")
    steps = report.get("steps", [])
    if len(steps) != 4 or any(s["exit_code"] or s["timed_out"] for s in steps):
        raise ValueError("complete configure, build, PageRank and full-core gates required")
    if f"100% tests passed, 0 tests failed out of {expected_tests}" not in read(prefix + "ctest.stdout.txt").decode():
        raise ValueError(f"all {expected_tests} registered core tests must pass")
    pins = {p["path"]: p for p in matrix["pins"]}
    if any(p != pins.get(p["path"]) for p in report["pins"]
           if not p["path"].endswith("/sources.tar.gz")):
        raise ValueError("core regression and matrix source identities differ")
    source_snapshot(report, read, prefix)


def energy_details(read, directory):
    fields = ("act_energy", "act_stb_energy", "pre_stb_energy", "read_energy",
              "write_energy", "ref_energy", "refb_energy", "sref_energy")
    totals = dict(total_energy_pj=0.0, **{k + "_pj": 0.0 for k in fields},
                  num_read_cmds=0, num_write_cmds=0)
    for channel in range(32):
        contents = json.loads(read(directory + f"/dram/channel{channel}/dramsim3.json"))
        for entry in contents.values():
            for key in ("total_energy", *fields, "num_read_cmds", "num_write_cmds"):
                value = entry[key]
                value = sum(value.values()) if isinstance(value, dict) else value
                if not math.isfinite(value) or value < 0:
                    raise ValueError("invalid all-channel energy component")
                totals[key if key.startswith("num_") else key + "_pj"] += value
    if not math.isclose(sum(totals[k + "_pj"] for k in fields), totals["total_energy_pj"],
                        rel_tol=1e-9, abs_tol=1e-3) or totals["total_energy_pj"] <= 0:
        raise ValueError("energy components do not conserve total")
    return totals


def source_snapshot(report, read, prefix):
    blob = read(prefix + "sources.tar.gz")
    pins = report["pins"]
    archive_pin = [p for p in pins if p["path"].endswith("/" + prefix + "sources.tar.gz")]
    if len(archive_pin) != 1 or hashlib.sha256(blob).hexdigest() != archive_pin[0]["sha256"]:
        raise ValueError("source snapshot identity differs")
    roots = [p["path"].removesuffix("cpp/CMakeLists.txt") for p in pins
             if p["path"].endswith("/cpp/CMakeLists.txt")]
    if len(roots) != 1:
        raise ValueError("source snapshot requires one repository root")
    identities = {p["path"]: p for p in pins}
    with tarfile.open(fileobj=io.BytesIO(blob)) as source:
        names = source.getnames()
        if len(names) != len(set(names)):
            raise ValueError("duplicate source snapshot members")
        for member in source.getmembers():
            match = identities.get(roots[0] + member.name)
            if not member.isfile() or match is None:
                raise ValueError("source member has no unique pin")
            if hashlib.sha256(source.extractfile(member).read()).hexdigest() != match["sha256"]:
                raise ValueError("source member differs from frozen pin")


def selection(report, identity, *, expected=EXPECTED):
    if (report.get("pins_unchanged") is not True or report.get("failures") != [] or
            report.get("status") != "COMPLETE_SUPPORTED_SCOPE" or
            report.get("baseline_admitted") is not False):
        raise ValueError("complete unchanged exploratory matrix required")
    cases = {(c["algorithm"], c["dataset"]): c for c in report["matrix"]}
    rows = {(r["algorithm"], r["dataset"]): r for r in report["rows"]}
    if (len(report["matrix"]) != len(expected) or len(report["rows"]) != len(expected) or
            set(cases) != expected or set(rows) != expected):
        scope = "nine-pair" if expected == EXPECTED else "requested"
        raise ValueError("exact " + scope + " registered matrix required")
    result = []
    for key, case in cases.items():
        row = rows[key]
        if (case["updates"] != 8 or case["projection"] !=
                {"SSSP": "directed", "CC": "reciprocal", "ResPR": "residual_sink_free"}[key[0]] or
                case["physical_update_records"] != (16 if key[0] == "CC" else 8) or
                (key[0] == "SSSP" and case.get("root") != HISTORICAL_ROOTS[key[1]])):
            raise ValueError("registered graph projection and update count required")
        if analysis.comparison(case, {a: row[a] for a in ("spine", "gr")}) != row:
            raise ValueError("comparison arithmetic or prediction boundary changed")
        if any(row["spine"]["state_hashes"][k] != row["gr"]["state_hashes"][k]
               for k in ("old_state", "expected")):
            raise ValueError("both arms must share old convergence and independent oracle")
        result.append(dict(row, case=case, **identity))
    return result


def pagerank_threshold(config, model, vertices):
    # Sealed older runs omitted the parameter and used the size-scaled rule.
    value = config.get("residual_epsilon", 1e-5 / vertices)
    try:
        epsilon = struct.unpack("<f", struct.pack("<f", value))[0]
    except (TypeError, OverflowError, struct.error) as error:
        raise ValueError("positive finite FP32 epsilon required") from error
    if not math.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("positive finite FP32 epsilon required")
    if (("residual_epsilon" in config) != ("residual_epsilon" in model) or
            ("residual_epsilon" in config and epsilon != model["residual_epsilon"])):
        raise ValueError("PageRank threshold differs from model identity")
    damping = struct.unpack("<f", struct.pack("<f", 0.85))[0]
    return epsilon, vertices * epsilon / (1.0 - damping)


def validate_raw(comparisons, read, *, expected=EXPECTED):
    for row in comparisons:
        prefix = Path(row["source_report"]).parent.name + "/"
        blob = read(prefix + "results.json")
        if hashlib.sha256(blob).hexdigest() != row["source_report_sha256"]:
            raise ValueError("selected report identity changed")
        report = json.loads(blob)
        selected = [r for r in selection(report, {}, expected=expected) if
                    (r["algorithm"], r["dataset"]) == (row["algorithm"], row["dataset"])]
        if len(selected) != 1 or dict(selected[0], source_report=row["source_report"],
                                     source_report_sha256=row["source_report_sha256"]) != row:
            raise ValueError("selected comparison differs from frozen report")
        source_snapshot(report, read, prefix)
        for arm in ("spine", "gr"):
            arm_result = row[arm]
            name = Path(arm_result["evidence"]).name
            steps = [s for s in report["steps"] if Path(s["stdout"]).name == name + ".stdout.txt"]
            if len(steps) != 1 or steps[0]["exit_code"] or steps[0]["timed_out"]:
                raise ValueError("successful bounded device command required")
            if json.loads(read(prefix + "raw/" + name + ".resources.json")) != steps[0]:
                raise ValueError("command resource record differs")
            text = read(prefix + "raw/" + name + ".stdout.txt").decode()
            raw = [json.loads(s.removeprefix("WARM_RESULT ")) for s in text.splitlines()
                   if s.startswith("WARM_RESULT ")]
            if (len(raw) != 1 or "REFRESH_COMPLETE" not in text or
                    any(arm_result.get(k) != v for k, v in raw[0].items()) or
                    raw[0].get("correctness") is not True or raw[0].get("ledger_closed") is not True):
                raise ValueError("arm differs from correctness-admitted raw result")
            config = json.loads(read(prefix + name + "/config.json"))
            if config["arm"] != arm or any(config[k] != row["case"][v] for k, v in
                    (("algorithm", "algorithm"), ("graph", "graph"), ("updates", "update_file"))):
                raise ValueError("arm input configuration differs")
            if row["algorithm"] == "SSSP" and config["root"] != row["case"]["root"]:
                raise ValueError("SSSP source vertex differs")
            for state in ("old_state", "expected", "final"):
                state_blob = read(prefix + name + "/" + state + ".u32le")
                if (len(state_blob) != 4 * row["case"]["vertices"] or
                        hashlib.sha256(state_blob).hexdigest() != arm_result["state_hashes"][state]):
                    raise ValueError("complete state identity differs")
            if row["algorithm"] in ("SSSP", "CC"):
                if arm_result["state_hashes"]["final"] != arm_result["state_hashes"]["expected"]:
                    raise ValueError("SSSP/CC must exactly match their independent oracle")
            else:
                epsilon, bound = pagerank_threshold(config, report.get("model", {}), row["case"]["vertices"])
                oracle = [json.loads(s.removeprefix("PR_ORACLE ")) for s in text.splitlines()
                          if s.startswith("PR_ORACLE ")]
                if (len(oracle) != 1 or any(not math.isfinite(v) or v < 0 for v in oracle[0].values()) or
                        oracle[0]["l1_error"] > oracle[0]["l1_error_bound"] or
                        not math.isclose(oracle[0]["l1_error_bound"], bound, rel_tol=2e-5)):
                    raise ValueError("independent PageRank L1 oracle gate failed")
                if arm == "spine" and arm_result.get("correction_oracle_directed") is not True:
                    raise ValueError("Spine correction replay boundary must remain visible")
                residual = read(prefix + name + "/residual.u32le")
                if len(residual) != 4 * row["case"]["vertices"]:
                    raise ValueError("complete residual state required")
                if any(not math.isfinite(v) or abs(v) > epsilon for (v,) in struct.iter_unpack("<f", residual)):
                    raise ValueError("stored PageRank residual did not converge")
            ledger = json.loads(read(prefix + name + "/backend.json"))
            if (ledger["ledger_closed"] is not True or ledger["pending_intents"] or ledger["pending_grants"] or
                    len({ledger[k] for k in ("unique_intents", "grants", "consumed_grants")}) != 1):
                raise ValueError("physical request ledger did not drain")
            details = energy_details(read, prefix + name)
            if details != arm_result["energy_details"] or details["total_energy_pj"] != arm_result["energy_pj"]:
                raise ValueError("all-channel DRAMSim3 energy differs")
