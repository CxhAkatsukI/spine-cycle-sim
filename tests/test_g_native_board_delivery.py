import copy
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.native_board import analysis, delivery, execution, preparation
from test_g_native_board import fixture, transcript

EVIDENCE = Path(__file__).resolve().parents[1] / (
    "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/"
    "hardware_validation/complete_pipeline/continuous_board/guarded_host_evidence")


def passing_fixture():
    index = json.loads((EVIDENCE / "index.json").read_text())
    with tarfile.open(EVIDENCE / index["attempts"][0]["archive"]) as bundle:
        reference = {"reference/" + item.name: bundle.extractfile(item).read().decode("utf-8")
                     for item in bundle if item.isfile() and "/" not in item.name}
    old = json.loads(reference["reference/results.json"])
    contract = {"cases": [preparation.CASE], "regression_cases": old["contract"]["cases"]}
    report = {"status": analysis.PASS, "errors": [], "contract": contract,
              "regression": [{**row, "equivalent": True} for row in old["cases"]],
              "binary_sha256": {"probe": "a" * 64, "regression-probe": "b" * 64},
              "policy": {"tree_memory_gib": 4, "reserve_gib": 32, "allow_bounded_builds": True},
              "admission": {"admitted": True, "policy": "full_finite_budgets_plus_reserve_atomic_lease"},
              "memory_events_after": "oom 0\noom_kill 0\noom_group_kill 0\n",
              **dict.fromkeys(analysis.CLAIMS, False)}
    setup, batches = fixture()
    native = transcript(setup, batches)
    report["cases"] = [{"case": preparation.CASE["case"], **analysis.analyze(preparation.CASE, native, "")}]
    files = {**reference, "native_board_contract.json": json.dumps(contract)}
    labels = ["compile-regression", "compile-native", *(case["case"] for case in contract["regression_cases"]),
              preparation.CASE["case"]]
    report["steps"] = []
    for label in labels:
        step = {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None,
                "tree_memory_gib": 4, "reserve_gib": 32}
        report["steps"].append({"label": label, **step})
        files["raw/" + label + ".resources.json"] = json.dumps(step)
        for stream in ("stdout", "stderr"):
            name = label + "." + stream + ".txt"
            files["raw/" + name] = (native if stream == "stdout" else "") if label == preparation.CASE["case"] \
                else reference.get("reference/" + name, "")
    return report, files


def materialize_fixture(root):
    attempt, runners = root / "synthetic-attempt", root / "runners"
    report, files = passing_fixture()
    for name, contents in files.items():
        path = attempt / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    runner = runners / "native_board/study.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# Synthetic runner identity for archive tests only.\n")
    source = attempt / "source/control.cpp"
    source.parent.mkdir()
    source.write_text("// Synthetic source identity for archive tests only.\n")
    report["pins"] = [{"path": str(path), "sha256": sha256_file(path)} for path in (source, runner)]
    for name in report["binary_sha256"]:
        path = attempt / name
        path.write_text("synthetic binary placeholder: " + name)
        report["binary_sha256"][name] = sha256_file(path)
    (attempt / "results.json").write_text(json.dumps(report))
    return attempt, runners


class NativeDeliveryTests(unittest.TestCase):
    def test_synthetic_package_roundtrip_has_no_live_source_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, runners = materialize_fixture(root)
            output = root / "portable"
            with patch.object(delivery, "ROOT", runners):
                index = delivery.package(output, attempt)
            entry = index["attempts"][0]
            self.assertNotIn("probe", {item["path"] for item in entry["files"]})
            self.assertNotIn("regression-probe", {item["path"] for item in entry["files"]})
            self.assertTrue(any(name.startswith("runner_snapshot/") for name in entry["pin_members"].values()))
            for path in (*attempt.rglob("*"), *runners.rglob("*")):
                if path.is_file():
                    path.unlink()
            self.assertEqual(delivery.verify(output), index)

    def test_packaged_missing_runner_or_source_pin_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, runners = materialize_fixture(root)
            output = root / "portable"
            with patch.object(delivery, "ROOT", runners):
                index = delivery.package(output, attempt)
            for pin in index["attempts"][0]["pin_members"]:
                changed = copy.deepcopy(index)
                del changed["attempts"][0]["pin_members"][pin]
                (output / "index.json").write_text(json.dumps(changed))
                with self.subTest(pin=pin), self.assertRaises(ValueError):
                    delivery.verify(output)

    def test_complete_synthetic_native_and_archived_old_raw_replay(self):
        report, files = passing_fixture()
        delivery.recheck(report, files.__getitem__)
        self.assertEqual(len(report["steps"]), 9)
        self.assertEqual(sum(len(row["rows"]) for row in report["regression"]), 18)
        self.assertEqual(len(report["cases"][0]["rows"]), 3)

    def test_claim_promotion_or_incomplete_budgets_binary_or_regression_rejected(self):
        report, files = passing_fixture()
        changes = [lambda r: r.update(production_baseline_admitted=True),
                   lambda r: r["steps"].pop(), lambda r: r["regression"].pop(),
                   lambda r: r["binary_sha256"].clear(),
                   lambda r: r["binary_sha256"].update(probe="not-a-digest"),
                   lambda r: r["policy"].update(reserve_gib=0),
                   lambda r: r["admission"].update(admitted=False),
                   lambda r: r.update(memory_events_after="oom 1\noom_kill 0\noom_group_kill 0\n")]
        for change in changes:
            changed = copy.deepcopy(report)
            change(changed)
            with self.assertRaises(ValueError):
                delivery.recheck(changed, files.__getitem__)

    def test_changed_raw_resource_reference_or_diagnostics_rejected(self):
        report, files = passing_fixture()
        case = report["regression"][0]["case"]
        for name, value in (("raw/compile-native.stderr.txt", "warning"),
                            ("raw/compile-native.resources.json", "{}"),
                            ("raw/" + preparation.CASE["case"] + ".stderr.txt", "unknown diagnostic"),
                            ("reference/" + case + ".stdout.txt", "changed reference")):
            with self.subTest(name=name), self.assertRaises(ValueError):
                delivery.recheck(report, {**files, name: value}.__getitem__)

    def test_wait_timeout_is_retained_but_not_promoted_to_a_run(self):
        report, files = passing_fixture()
        report.update(status="FAILED_RETAINED", errors=["memory admission deadline"], steps=[],
                      cases=[], regression=[], binary_sha256={})
        delivery.recheck(report, files.__getitem__)
        report["errors"] = []
        with self.assertRaises(ValueError):
            delivery.recheck(report, files.__getitem__)

    def test_board_identity_requires_preprogramming_bdf_guard(self):
        report, _ = passing_fixture()
        report["pins"] = []
        expected = 'std::getenv("CONTINUOUS_G_EXPECT_BDF") CL_DEVICE_PCIE_BDF cl::Program(context'
        for source, allowed in ((expected, True), ("cl::Program(context " + expected, False),
                                (expected.replace("CL_DEVICE_PCIE_BDF", "unguarded"), False)):
            with patch.object(Path, "read_text", side_effect=[json.dumps(report), source]), \
                    patch.object(delivery, "validate"), patch.object(execution, "identity", return_value={}):
                if allowed:
                    execution.host_identity(Path("/preflight"))
                else:
                    with self.assertRaises(ValueError):
                        execution.host_identity(Path("/preflight"))


if __name__ == "__main__":
    unittest.main()
