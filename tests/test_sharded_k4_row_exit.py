"""Reject unpinned latency changes and incomplete/reused RTL invocations."""

import copy
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_exit_contract import parse_trace, TRIALS
from spine_cycle_sim.experiments.sharded_k4_stages.sst_candidate import component_parameters, load_profile

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "configs/architectures/grasu_regraph_routed_sssp_compute_v4.json"
PACKAGE = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst/empty_row_rtl"


def trace():
    lines = []
    for index, (offset, delay) in enumerate(TRIALS):
        start = 11 + index * 79
        lines.append(f"EMPTY_SEGMENT offset={offset} ready_delay={delay} start_cycle={start} "
                     f"exit_cycle={start+1} done_cycle={start+73} elapsed=73")
    return "\n".join(lines) + "\nEMPTY_SEGMENT_PASS cases=6\n"


class EmptyExitTests(unittest.TestCase):
    def test_repeated_latency_and_protocol(self):
        self.assertEqual(len(parse_trace(trace())), 6)

    def test_bad_or_partial_trace_rejected(self):
        for text in (trace().replace("elapsed=73", "elapsed=0", 1),
                     trace().replace("done_cycle=84", "done_cycle=85"),
                     trace().replace("start_cycle=90", "start_cycle=80"),
                     trace().replace("exit_cycle=12", "exit_cycle=13"),
                     trace().replace("ready_delay=100", "ready_delay=0"),
                     trace().split("\n", 1)[1], trace() + "FATAL: AXI request emitted\n",
                     trace() + "EMPTY_SEGMENT_PASS cases=6\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_trace(text)

    def test_explicit_profile_only(self):
        config = {"fixture": "in", "output": "out", "dram_output": "dram", "arm": "original", "max_cycles": 1000}
        for version in (1, 2, 3, 4):
            config["profile"] = str(PROFILE.with_name(f"grasu_regraph_routed_sssp_compute_v{version}.json"))
            result = component_parameters(ROOT, config)
            self.assertEqual("routed_empty_exit" in result, version == 4)
            if version == 4:
                self.assertEqual(result["routed_empty_exit"], 1)
                self.assertEqual(result["routed_stream_depths"], 1)
                self.assertEqual(result["independent_read_write"], 1)

    def test_silent_change_rejected(self):
        profile = json.loads(PROFILE.read_text())
        changes = [lambda p: p["fixed_model"].update(adapter_empty_segment_exit_cycles=72),
                   lambda p: p["fixed_model"].update(adapter_min_read_to_use=144),
                   lambda p: p["target"].update(empty_exit_flow_sha256="wrong"),
                   lambda p: p["target"]["empty_exit_rtl_sha256"]["candidate"].update(helper="wrong")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            for change in changes:
                bad = copy.deepcopy(profile)
                change(bad)
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    load_profile(ROOT, path)

    def test_portable_rtl_archive_and_traces(self):
        index = json.loads((PACKAGE / "rtl_raw_index.json").read_text())
        archive = PACKAGE / "raw_rtl.tar.gz"
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), index["archive"]["sha256"])
        report = json.loads((PACKAGE / "rtl.json").read_text())
        self.assertFalse(report["hardware_timing_admitted"])
        self.assertFalse(report["timing_fit_performed"])
        with tarfile.open(archive) as stream:
            self.assertEqual(set(stream.getnames()), {pin["archive_path"] for pin in index["files"]})
            for pin in index["files"]:
                self.assertEqual(hashlib.sha256(stream.extractfile(pin["archive_path"]).read()).hexdigest(), pin["sha256"])
            for arm in ("original", "candidate"):
                text = stream.extractfile(f"{arm}/simulate.stdout.txt").read().decode()
                self.assertEqual(parse_trace(text), report["arms"][arm]["trials"])
            self.assertIn("rejected_start_held_until_done/simulate.stdout.txt", stream.getnames())


if __name__ == "__main__":
    unittest.main()
