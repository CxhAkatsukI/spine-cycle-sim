import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import active_min_admission as gate


class ActiveMinJointAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.host = self.make("host", "native host")
        self.image = self.make("candidate.hw.xclbin", "repaired image")
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()

    def make(self, name, text):
        path = self.root / name
        path.write_text(text)
        return path

    def report(self, name, data):
        return self.make(name, json.dumps(data))

    def test_rejects_pending_or_wrong_algorithm_even_with_pass_flag(self):
        for status, algorithm in (("WAITING_FOR_ROUTE", "cc"), ("PAIRED_ACTIVE_MIN_R_GATE_PASS", "weighted_sssp")):
            with self.subTest(status=status, algorithm=algorithm), self.assertRaisesRegex(ValueError, "not admitted"):
                path = self.report("r.json", dict(status=status, algorithm=algorithm, retention_gate_pass=True))
                gate.replay_r(path, "cc", self.inputs, gate.identity(self.host), gate.identity(self.image))

    def test_joint_admission_requires_same_image_host_and_clocks(self):
        host = gate.identity(self.host)
        r_report = self.report("r.json", dict(status="PAIRED_ACTIVE_MIN_R_GATE_PASS", algorithm="cc"))
        decision = {"report": gate.identity(r_report), "candidate_clock": {"driver_reported_mhz": [150, 500, 450, 0]}}
        with patch.dict(gate.g_control.HOST_SHA256, {"cc": host["sha256"]}), \
                patch.object(gate.active_min_pair, "candidate_route", return_value=(gate.artifact.identity(self.image), [])), \
                patch.object(gate, "replay_r", return_value=decision) as r, \
                patch.object(gate, "replay_g", return_value={**decision, "reference": gate.identity(r_report)}) as g:
            args = ("cc", self.root, self.host, r_report, self.inputs,
                    self.root / "g.json", self.root / "public-g.json")
            admitted = gate.admit(*args)
            self.assertEqual(admitted["status"], "BASELINE_STAGES_ADMITTED_NOT_CONVERGENCE")
            for mocked in (g, r):
                self.assertEqual(mocked.call_args.args[-2:], (host, gate.identity(self.image)))
            g.return_value = {**decision, "candidate_clock": {"driver_reported_mhz": [140, 500, 450, 0]}}
            with self.assertRaisesRegex(ValueError, "clocks differ"):
                gate.admit(*args)
            self.host.write_text("different host")
            with self.assertRaisesRegex(ValueError, "exact CC/SSSP native host"):
                gate.admit(*args)

    def test_returned_route_replay_binds_exact_topology_proof(self):
        pair = gate.active_min_pair
        route = self.root / "returned"
        (route / "route").mkdir(parents=True)
        self.image = self.make("returned/route/candidate.hw.xclbin", "verified binary")
        predecessor = self.make("predecessor", "original image")
        timing = self.make("returned/route/timing.rpt", "routed timing")
        capsule = self.make("capsule.json", "build inputs")
        pins = [gate.artifact.identity(capsule)]
        parameters = ["a" * 64, str(capsule.parent), "/platform", str(predecessor)]
        (self.root / "candidate_admission").mkdir()
        proof = self.report("candidate_admission/summary.json", {
            "status": "ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD",
            "candidate": gate.artifact.identity(self.image),
            "timing": {"report": gate.artifact.identity(timing)},
            "pins": [*pins, gate.artifact.identity(predecessor)],
        })
        record = {"directory": str(route), "parameters": parameters, "proof": gate.artifact.identity(proof)}
        with patch.object(pair.replacement_return, "verify",
                          side_effect=lambda *_: ({}, {"mode": "destination"}, list(pins))):
            image, replayed = pair.replay_returned_route(route, "cc", record, self.root)
            self.assertEqual(image, gate.artifact.identity(self.image))
            self.assertIn(record["proof"], replayed)
            with self.assertRaisesRegex(ValueError, "exact R board receipt"):
                pair.replay_returned_route(self.root, "cc", record, self.root)
            with self.assertRaisesRegex(ValueError, "mode or topology"):
                pair.replay_returned_route(route, "weighted_sssp", record, self.root)
            proof.write_text(proof.read_text() + "\n")
            with self.assertRaisesRegex(ValueError, "mode or topology"):
                pair.replay_returned_route(route, "cc", record, self.root)

    def test_g_remote_ready_requires_matching_collector_and_image(self):
        route = self.root / "returned"
        (route / "route").mkdir(parents=True)
        image = self.make("returned/route/candidate.hw.xclbin", "verified binary")
        service = dict(LoadState="loaded", InvocationID="b" * 32, ActiveState="active", SubState="exited",
                       Result="success", MainPID="0", ExecMainStatus="0")
        digest = "a" * 64
        transfer = self.report("transfer.json", dict(status="REMOTE_REPLACEMENT_LINK_VERIFIED_NOT_BOARD_EVIDENCE",
                                                    receipt_sha256=digest, candidate=gate.artifact.identity(image)))
        ready = gate.g_control.active_min_follow.returned_ready
        self.assertEqual(ready("candidate", route, digest, service, service["InvocationID"], True),
                         gate.artifact.identity(transfer))
        with self.assertRaisesRegex(ValueError, "invocation changed"):
            ready("candidate", route, digest, service, "c" * 32, True)
        image.write_text("different image")
        with self.assertRaisesRegex(ValueError, "verified collector receipt"):
            ready("candidate", route, digest, service, service["InvocationID"], True)

    def test_g_replay_rejects_image_mismatch_or_stale_raw_log(self):
        host, image = gate.identity(self.host), gate.identity(self.image)
        reference = self.report("reference.json", {})
        graph = gate.identity(self.make("au.graph", "frozen batch"))
        stdout = self.make("stdout", "candidate events")
        row = {"stdout": gate.identity(stdout), "stderr": gate.identity(self.make("stderr", "")),
               "oracle": gate.identity(self.make("oracle", "pma result")), "clock_evidence": {}}
        row["command"] = [host["path"], "--update-only", image["path"], graph["path"], row["oracle"]["path"]]
        profile = {"config": {"static_edges": "390847"}}
        comparison = {"retention_gate_pass": True}
        report = dict(status="G_GATE_PASS_FOR_ACTIVE_MIN_IMAGE", algorithm="cc", bdf=gate.g_control.BDF,
                      device=gate.g_control.DEVICE, repetitions=1, board_launch_attempted=True,
                      image=gate.artifact.identity(self.image), pins=[host, gate.identity(reference), graph],
                      profile=profile, comparison=comparison, row=row)
        with patch.object(gate.g_control, "reference_arm", return_value=(graph, {}, {}, [], {}, {})), \
                patch.object(gate, "update_only_profile", return_value=profile), \
                patch.object(gate.g_control, "compare", return_value=comparison), \
                patch.object(gate.clocks, "replay", return_value={"binary": image}) as replay:
            path = self.report("g.json", report)
            self.assertEqual(gate.replay_g(path, reference, "cc", host, image)["comparison"], comparison)
            replay.return_value = {"binary": {**image, "sha256": "bad"}}
            with self.assertRaisesRegex(ValueError, "raw event/PMA"):
                gate.replay_g(path, reference, "cc", host, image)
            stdout.write_text("changed raw events")
            with self.assertRaisesRegex(ValueError, "hardware evidence changed"):
                gate.replay_g(path, reference, "cc", host, image)

    def test_r_replay_rejects_pass_label_with_over_budget_events(self):
        host, image = gate.identity(self.host), gate.identity(self.image)
        (self.root / "offline").mkdir()
        raw = [self.report("offline/result.json", dict(status="A4_ACTIVE_MIN_OFFLINE_PASS_NOT_FPGA", algorithm="cc",
                                                       vertices=735324, logical_edges=5158388, tasks=48)),
               self.make("offline/expected.u32le", "expected")]
        raw += [self.make(f"inputs/{name}.u32le", name) for name in gate.active_min.INPUTS + gate.active_min.STATE["cc"]]
        pins = [gate.artifact.identity(path) for path in [self.host, self.image, *raw]]
        execution = {key: gate.identity(self.make(key, key)) for key in ("stdout", "stderr")}
        command = [host["path"], "--active-min-once", image["path"], str(self.inputs), str(raw[1]),
                   str(self.root / "candidate")]
        ref = dict(execution=execution, clock_evidence={}, analysis={"event_span_ns": 100})
        current = dict(execution={**execution, "command": command}, clock_evidence={}, analysis={"event_span_ns": 115})
        clock = {"binary": image, "bdf": gate.R_BDF, "driver_reported_mhz": [150, 500, 450, 0]}
        comparison = gate.r_candidate.compare(ref["analysis"], current["analysis"], clock, clock)
        path = self.report("r.json", dict(status="PAIRED_ACTIVE_MIN_R_GATE_PASS", algorithm="cc", bdf=gate.R_BDF,
                                         boundary=gate.active_min.BOUNDARY, requested_runs_per_arm=1,
                                         attempts=["reference", "candidate"], convergence_measured=False,
                                         retention_gate_pass=True, arms={"reference": ref, "candidate": current},
                                         pins=pins, comparison=comparison))
        with patch.object(gate.clocks, "replay", return_value=clock), \
                patch.object(gate.active_min, "inspect", return_value=ref["analysis"]), \
                patch.object(gate.r_candidate, "inspect", return_value=current["analysis"]) as observed:
            args = (path, "cc", self.inputs, host, image)
            self.assertEqual(gate.replay_r(*args)["comparison"], comparison)
            observed.return_value = {"event_span_ns": 116}
            with self.assertRaisesRegex(ValueError, "15 percent"):
                gate.replay_r(*args)
            observed.return_value = current["analysis"]
            original = gate.identity(self.report("original-pair.json", {}))
            retained = json.loads(path.read_text())
            ref["execution"]["command"] = [str(self.host), "board", "cc", str(self.inputs),
                                           "original/reference", str(self.image), "0"]
            retained.update(attempts=["candidate"], retained_reference_pair=original,
                            pins=[*pins, original], arms={"reference": ref, "candidate": current})
            self.report(path.name, retained)
            with patch.object(gate.active_min_pair, "retained_reference", return_value=(ref, original)) as replay:
                self.assertEqual(gate.replay_r(*args)["comparison"], comparison)
                self.assertEqual(replay.call_args.args[2].reference_host, self.host)
                replay.return_value = ({**ref, "analysis": {}}, original)
                with self.assertRaisesRegex(ValueError, "retained R arm differs"):
                    gate.replay_r(*args)
