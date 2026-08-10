from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def write_slice(path: Path, *, vertices: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# vertices={vertices}\n0 1 1 1\n", encoding="ascii")


def case_result(root: Path, system: str, updates: int, raw: Path) -> None:
    write_json(
        root / "runs_update_only" / f"{system}_u{updates}" / "case_result.json",
        {
            "status": "PASS",
            "raw_result_path": str(raw),
            "raw_result_sha256": "test",
            "row": {
                "core_mhz": 100.0,
                "updates": updates,
                "cycles": 1000,
                "measurement_window": "dynamic_e2e_to_convergence",
            },
        },
    )


class CurrentFig8UpdateOnlyBuilderTests(unittest.TestCase):
    def test_builds_partial_evidence_from_current_device_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            formal = root / "formal"
            graph = formal / "workloads" / "sx_askubuntu" / "graphs" / "g.slice"
            update = formal / "workloads" / "sx_askubuntu" / "updates" / "u.slice"
            write_slice(graph)
            write_slice(update)
            write_json(
                formal
                / "workloads"
                / "sx_askubuntu"
                / "materialization_manifest.json",
                {
                    "graphs": {"directed": {"path": str(graph)}},
                    "updates": [
                        {
                            "projection": "directed",
                            "scenario": "insert",
                            "user_mutations": 8,
                            "path": str(update),
                        }
                    ],
                },
            )
            spine_raw = root / "spine_raw.json"
            grasu_raw = root / "grasu_raw.json"
            write_json(
                spine_raw,
                {
                    "success": True,
                    "maintenance_cycles": 10,
                    "backend_traffic": {"combined": {"requests": 1, "bytes": 64}},
                    "update_backend_traffic": {
                        "combined": {"requests": 1, "bytes": 64}
                    },
                },
            )
            write_json(
                grasu_raw,
                {
                    "success": True,
                    "update_cycles": 20,
                    "backend_traffic": {"combined": {"requests": 2, "bytes": 128}},
                    "update_backend_traffic": {
                        "combined": {"requests": 2, "bytes": 128}
                    },
                },
            )
            case_result(formal, "spine", 8, spine_raw)
            case_result(formal, "grasu_regraph_k4_shared", 8, grasu_raw)
            host_tool = root / "host_tool.py"
            host_tool.write_text(
                "#!/usr/bin/env python3\n"
                "print('{\"updates\":8,\"batch_count\":1,"
                "\"spine_host_preprocess_ns\":1000,"
                "\"grasu_host_preprocess_ns\":2000,"
                "\"spine_initial_h2d_bytes\":64,"
                "\"grasu_initial_h2d_bytes\":128,"
                "\"spine_update_h2d_bytes\":16,"
                "\"grasu_update_h2d_bytes\":16}')\n",
                encoding="ascii",
            )
            host_tool.chmod(0o755)
            out = root / "out"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_current_fig8_update_only_evidence.py"),
                    "--formal-root",
                    str(formal),
                    "--out-root",
                    str(out),
                    "--host-tool",
                    str(host_tool),
                    "--host-repeats",
                    "1",
                    "--batch-update-count",
                    "8",
                    "--cross-update-count",
                    "8",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )

            self.assertIn("FIG8_CURRENT_UPDATE_ONLY_PARTIAL", completed.stdout)
            manifest = json.loads((out / "manifest.json").read_text())
            comparison = json.loads(
                (out / "batch_sensitivity" / "b8" / "comparison.json").read_text()
            )

        self.assertEqual(manifest["status"], "PARTIAL_CURRENT_MODEL_DATA")
        self.assertEqual(comparison["logical_updates"], 8)
        self.assertEqual(comparison["correctness"], "pass")


if __name__ == "__main__":
    unittest.main()
