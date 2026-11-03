"""Keep tail-publication bitstreams paired with the matching host ABI."""

import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.follow import matched_hosts
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity as board_identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import tail_publication as tail
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity


class TailRouteTest(unittest.TestCase):
    def test_only_gather_scalar_and_control_range_can_change(self):
        control = {"name": "S_AXI_CONTROL", "range": "0x30"}
        stream = {"name": "EDGE_BURST_IN", "dataWidth": "512"}
        old = {"control": "ap_ctrl_chain", "ports": [control, stream],
               "args": [{"name": str(i), "id": str(i)} for i in range(8)]}
        new = copy.deepcopy(old)
        new["ports"][0]["range"] = "0x38"
        new["args"][5:] = [
            dict(name="publication_rows", addressQualifier="0", id="5", port="S_AXI_CONTROL",
                 size="0x4", offset="0x30", hostOffset="0x0", hostSize="0x4", type="unsigned int"),
            *[dict(name=str(i), id=str(i + 1)) for i in range(5, 8)],
        ]
        macros = {"PARTITION_SIZE": "65536"}
        with patch.object(tail, "kernel_interface", side_effect=[
            (copy.deepcopy(old), macros), (new, {**macros, "GRASU_REGRAPH_TAIL_PUBLICATION": "1"}),
        ]):
            tail.check_gather("original", "candidate")
        new["ports"][1]["dataWidth"] = "256"
        with patch.object(tail, "kernel_interface", side_effect=[
            (old, macros), (new, {**macros, "GRASU_REGRAPH_TAIL_PUBLICATION": "1"}),
        ]), self.assertRaisesRegex(ValueError, "not limited"):
            tail.check_gather("original", "candidate")

    def test_host_manifest_and_reference_binary_are_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "old_ref"
            reference.write_bytes(b"original")
            args = argparse.Namespace(r_host=reference, r_candidate=root / "old_candidate")
            manifest = root / "manifest.json"
            builds = []
            for arm in ("reference", "candidate"):
                path = root / arm
                path.write_bytes(b"original" if arm == "reference" else b"tail")
                builds.append(dict(arm=arm, status="COMPILED", binary=board_identity(path),
                                   command=["g++"] + (["-DSPINE_RETENTION_TAIL_PUBLICATION=1"]
                                                       if arm == "candidate" else [])))
            manifest.write_text(json.dumps(dict(status="SINGLE_RUN_HOSTS_BUILD_PASS_NOT_BOARD",
                                                builds=builds, candidate_publication="tail")))
            with self.assertRaisesRegex(ValueError, "fixed host"):
                matched_hosts(args, {}, root)
            with self.assertRaisesRegex(ValueError, "do not match"):
                matched_hosts(args, {"tail_hosts": {"sha256": "wrong"}}, root)
            plan = {"tail_hosts": identity(manifest)}
            self.assertEqual(len(matched_hosts(args, plan, root)), 2)
            self.assertEqual(args.r_candidate, root / "candidate")
            args.r_host = reference
            reference.write_bytes(b"wrong")
            with self.assertRaisesRegex(ValueError, "control binary"):
                matched_hosts(args, plan, root)
            (root / "candidate").write_bytes(b"wrong")
            with self.assertRaisesRegex(ValueError, "pinned build input"):
                matched_hosts(args, plan, root)
