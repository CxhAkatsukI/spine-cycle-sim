"""Keep storage screens conservative and reject incomplete resource ledgers."""

from pathlib import Path
import json
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.resource_fit import (
    RESOURCES, account, platform_screen, query_capacity, resources, topology)
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.resource_probe import capacity, run


class ResourceTests(unittest.TestCase):
    def test_query_rejects_unbounded_time_before_creating_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "attempt"
            for timeout in (0, 299, 901, float("inf"), True):
                with self.assertRaises(ValueError):
                    run(output, Path(folder) / "environment.json", "previous", "route",
                        timeout_seconds=timeout)
                self.assertFalse(output.exists())

    def test_capacity_requires_complete_consistent_regions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "capacity.csv"
            path.write_text("region,uram_sites\nSLR0,320\nSLR1,320\nSLR2,320\ndevice,960\n")
            self.assertEqual(capacity(path)["device"], 960)
            for invalid in ("SLR0,320\nSLR1,320\nSLR2,320\ndevice,959\n",
                            "SLR0,320\nSLR0,320\nSLR1,320\nSLR2,320\ndevice,960\n",
                            "SLR0,320\nSLR1,320\ndevice,640\n"):
                path.write_text("region,uram_sites\n" + invalid)
                with self.assertRaises(ValueError):
                    capacity(path)

    def test_connectivity_preserves_repeated_keys(self):
        kernels, placements = topology("[connectivity]\nnk=cache:2:c1.c2\nnk=read:1\n"
                                       "slr=c1:SLR0\nslr=c2:SLR2\nslr=read_1:SLR1\n")
        self.assertEqual(kernels, {"cache": ["c1", "c2"], "read": ["read_1"]})
        self.assertEqual(len(placements), 3)

    def test_connectivity_rejects_missing_duplicate_or_unknown_units(self):
        valid = "[connectivity]\nnk=cache:1\nslr=cache_1:SLR0\n"
        for contents in (valid + "nk=cache:1\n", valid + "slr=cache_1:SLR1\n",
                         valid.replace("SLR0", "SLR3"), valid.replace("slr=cache_1:SLR0", ""),
                         valid + "slr=extra_1:SLR2\n", valid.replace("cache:1", "cache:2")):
            with self.assertRaises(ValueError):
                topology(contents)

    def test_slr_conflict_not_hidden_by_device_headroom(self):
        kernels = {"cache": ["c1", "c2"], "little": ["l1", "l2", "l3", "l4"]}
        placements = {"c1": "SLR0", "c2": "SLR2", "l1": "SLR0", "l2": "SLR1",
                      "l3": "SLR2", "l4": "SLR0"}
        estimates = {name: {**dict.fromkeys(RESOURCES, 0), "URAM": value} for name, value in
                     (("cache", 256), ("little", 64))}
        physical = {"SLR0": 320, "SLR1": 320, "SLR2": 320, "device": 960}
        result = account(kernels, placements, estimates, physical)
        self.assertEqual(result["hls_totals"]["URAM"], 768)
        self.assertFalse(result["total_uram_capacity_exceeded"])
        self.assertEqual(result["uram_oversubscribed_slrs"], ["SLR0"])
        placements["l4"] = "SLR1"
        balanced = account(kernels, placements, estimates, physical)
        self.assertEqual(balanced["uram_oversubscribed_slrs"], [])
        self.assertFalse(balanced["complete_g_resource_fit_admitted"])
        self.assertFalse(balanced["hardware_timing_admitted"])
        with self.assertRaises(ValueError):
            account(kernels, placements, {"cache": estimates["cache"]}, physical)

    def test_top_report_identity_and_nonnegative_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "hls.xml"
            contents = ("<Report><UserAssignments><TopModelName>cache</TopModelName></UserAssignments>"
                        "<AreaEstimates><Resources>" + "".join(f"<{name}>1</{name}>" for name in RESOURCES) +
                        "</Resources></AreaEstimates></Report>")
            path.write_text(contents)
            self.assertEqual(resources(path, "cache")["URAM"], 1)
            with self.assertRaises(ValueError):
                resources(path, "different_top")
            path.write_text(contents.replace("<URAM>1", "<URAM>-1"))
            with self.assertRaises(ValueError):
                resources(path, "cache")

    def test_platform_screen_does_not_promote_physical_headroom(self):
        physical = {"SLR0": 320, "SLR1": 320, "SLR2": 320, "device": 960}
        platform = {"SLR0": 256, "SLR1": 320, "SLR2": 320, "device": 896}
        ledger = {"hls_per_slr": {slr: {"URAM": 320} for slr in ("SLR0", "SLR1", "SLR2")},
                  "hls_totals": {"URAM": 960}}
        result = platform_screen(ledger, physical, platform)
        self.assertEqual(result["uram_oversubscribed_slrs"], ["SLR0"])
        self.assertTrue(result["total_uram_capacity_exceeded"])
        self.assertFalse(result["complete_g_resource_fit_admitted"])
        with self.assertRaises(ValueError):
            platform_screen(ledger, platform, physical)

    def test_query_requires_completed_unchanged_correct_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            attempt = Path(folder)
            table = attempt / "uram_capacity.csv"
            table.write_text("region,uram_sites\nSLR0,320\nSLR1,320\nSLR2,320\ndevice,960\n")
            result = {"status": "PHYSICAL_SITE_CAPACITY_QUERIED_NOT_ROUTE_ADMISSION",
                      "physical_capacity": capacity(table),
                      "artifacts": [{"path": str(table), "sha256": sha256_file(table)}],
                      **dict.fromkeys(("platform_available_resources_admitted",
                                       "complete_g_resource_fit_admitted", "hardware_timing_admitted"), False)}
            report = attempt / "results.json"
            report.write_text(json.dumps(result))
            self.assertEqual(query_capacity(attempt)["device"], 960)
            with self.assertRaises(ValueError):
                query_capacity(attempt, platform=True)
            result["hardware_timing_admitted"] = True
            report.write_text(json.dumps(result))
            with self.assertRaises(ValueError):
                query_capacity(attempt)
            result["hardware_timing_admitted"] = False
            report.write_text(json.dumps(result))
            table.write_text(table.read_text().replace("320", "319"))
            with self.assertRaises(ValueError):
                query_capacity(attempt)


if __name__ == "__main__":
    unittest.main()
