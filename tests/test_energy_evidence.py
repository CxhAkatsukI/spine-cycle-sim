from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.evidence.energy import (
    EnergyEvidenceError,
    activity_count,
    aggregate_dramsim3,
    analyze_energy_manifest,
    parse_cacti_output,
    render_cacti_config,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "configs/evidence/onchip_energy_20260725.json"

CACTI_OUTPUT = """\
array type                    : Scratch RAM
---------- CACTI-P, test ----------
    Total cache size (bytes): 32768
    Number of banks: 1
    Block size (bytes): 8
    Read/write Ports: 1
    Read ports: 0
    Write ports: 0
    Technology size (nm): 32
    Access time (ns): 0.5 (@DVS_Level0)
    Cycle time (ns): 0.2 (@DVS_Level0)
    Total dynamic read energy per access (nJ): 0.01 (@DVS_Level0)
    Total dynamic write energy per access (nJ): 0.02 (@DVS_Level0)
    Total leakage power of a bank without power gating, including its network outside (mW): 3.5 (@DVS_Level0)
    Cache height x width (mm): 0.2 x 0.3
    Best Ndwl : 2
    Best Ndbl : 4
    Best Nspd : 1
    Best Ndcm : 1
    Best Ndsam L1 : 1
    Best Ndsam L2 : 2
"""


def _bundle(items: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(items):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


class EnergyEvidenceTests(unittest.TestCase):
    def test_parses_cacti_baseline_values(self) -> None:
        result = parse_cacti_output(CACTI_OUTPUT)
        self.assertEqual(result["geometry"]["size_bytes"], 32768)
        self.assertEqual(result["read_energy_nj"], 0.01)
        self.assertEqual(result["write_energy_nj"], 0.02)
        self.assertAlmostEqual(result["area_mm2"], 0.06)
        self.assertEqual(result["organization"]["ndbl"], 4)

    def test_rejects_non_scratchpad_or_voltage_failure(self) -> None:
        with self.assertRaises(EnergyEvidenceError):
            parse_cacti_output(CACTI_OUTPUT.replace("Scratch RAM", "Cache"))
        with self.assertRaises(EnergyEvidenceError):
            parse_cacti_output(CACTI_OUTPUT + "User defined Vdd is too low.\n")

    def test_renders_canonical_port_geometry(self) -> None:
        config = render_cacti_config(
            {
                "size_bytes": 262144,
                "word_bytes": 4,
                "banks": 1,
                "technology_nm": 32,
                "temperature_k": 350,
                "read_write_ports": 0,
                "read_ports": 1,
                "write_ports": 1,
            }
        )
        self.assertIn("-cache type \"ram\"", config)
        self.assertIn("-exclusive read port 1", config)
        self.assertIn("-exclusive write port 1", config)
        self.assertIn("-output/input bus width 32", config)

    def test_activity_terms_sum_lists_and_apply_physical_multiplier(self) -> None:
        document = {"rounds": [2, 3], "marks": 7}
        count = activity_count(
            document,
            [{"path": "rounds", "multiplier": 64}, {"path": "marks"}],
            "test",
        )
        self.assertEqual(count, 327)

    def test_activity_rejects_fractional_or_missing_counts(self) -> None:
        with self.assertRaises(EnergyEvidenceError):
            activity_count({"value": 1}, [{"path": "value", "multiplier": 0.5}], "x")
        with self.assertRaises(EnergyEvidenceError):
            activity_count({}, [{"path": "missing"}], "x")

    def test_aggregates_nested_dramsim3_and_validates_bundle(self) -> None:
        rows = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dram = root / "dram"
            dram.mkdir()
            for channel in range(2):
                payload = json.dumps(
                    {
                        "0": {
                            "num_reads_done": channel + 1,
                            "num_writes_done": channel + 2,
                            "num_act_cmds": channel + 3,
                            "num_pre_cmds": channel + 4,
                            "total_energy": float(100 + channel),
                        }
                    },
                    sort_keys=True,
                ).encode()
                name = f"ch{channel}.json.gz"
                (dram / name).write_bytes(gzip.compress(payload, mtime=0))
                rows.append((name, payload))
            result = aggregate_dramsim3(
                root,
                {
                    "directory": "dram",
                    "glob": "*.json.gz",
                    "expected_files": 2,
                    "content_bundle_sha256": _bundle(rows),
                },
                "test",
            )
        self.assertEqual(result["reads"], 3)
        self.assertEqual(result["writes"], 5)
        self.assertEqual(result["total_energy_pj"], 201.0)

    def test_rejects_invalid_dramsim3_count_or_energy(self) -> None:
        for field, value in (
            ("num_reads_done", True),
            ("num_writes_done", -1),
            ("total_energy", float("nan")),
        ):
            with self.subTest(field=field, value=value):
                row = {
                    "num_reads_done": 1,
                    "num_writes_done": 2,
                    "num_act_cmds": 3,
                    "num_pre_cmds": 4,
                    "total_energy": 5.0,
                }
                row[field] = value
                payload = json.dumps({"0": row}, sort_keys=True).encode()
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    dram = root / "dram"
                    dram.mkdir()
                    (dram / "ch0.json.gz").write_bytes(
                        gzip.compress(payload, mtime=0)
                    )
                    with self.assertRaises(EnergyEvidenceError):
                        aggregate_dramsim3(
                            root,
                            {
                                "directory": "dram",
                                "glob": "*.json.gz",
                                "expected_files": 1,
                                "content_bundle_sha256": _bundle(
                                    [("ch0.json.gz", payload)]
                                ),
                            },
                            "test",
                        )

    def test_frozen_manifest_closes_activity_dram_and_selected_arrays(self) -> None:
        ledger = analyze_energy_manifest(MANIFEST)
        self.assertEqual(ledger["status"], "PASS")
        self.assertEqual(len(ledger["runs"]), 2)
        by_id = {run["run_id"]: run for run in ledger["runs"]}
        spine = by_id["spine_weighted_sssp_selected_arrays"]
        grasu = by_id["grasu_regraph_weighted_sssp_selected_arrays"]
        self.assertEqual(
            spine["dram"]["reads"] + spine["dram"]["writes"],
            spine["backend_requests"],
        )
        self.assertEqual(
            grasu["dram"]["reads"] + grasu["dram"]["writes"],
            grasu["backend_requests"],
        )
        self.assertEqual(len(spine["selected_onchip"]["arrays"]), 3)
        self.assertEqual(len(grasu["selected_onchip"]["arrays"]), 2)
        self.assertEqual(
            spine["partial_energy_ledger"]["claim_label"],
            "partial_sum_not_total_accelerator_energy",
        )

    def test_manifest_hash_mismatch_is_fatal(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        broken = copy.deepcopy(manifest)
        broken["runs"][0]["activity"]["content_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            # Preserve the original repository-root interpretation.
            broken["repository_root"] = str(ROOT)
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaises(EnergyEvidenceError):
                analyze_energy_manifest(path)

    def test_manifest_profile_or_clock_mismatch_is_fatal(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        mutations = (
            ("profile_id", "wrong-profile"),
            ("clock_mhz", 142.0),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                broken = copy.deepcopy(manifest)
                broken["runs"][0][field] = value
                broken["repository_root"] = str(ROOT)
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "broken.json"
                    path.write_text(json.dumps(broken), encoding="utf-8")
                    with self.assertRaises(EnergyEvidenceError):
                        analyze_energy_manifest(path)


if __name__ == "__main__":
    unittest.main()
