"""Original nine-CU topology and strict timing negatives; no FPGA programming."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.upstream_controls.grasu.hardware import configuration as config, gates, topology


def fixture():
    result = {"clock": list(config.CLOCK_TOPOLOGY), "kernels": [], "memory": [], "connections": []}
    for name, count in config.KERNELS.items():
        result["kernels"] += [(f"{name}:{name}_{i}", "AP_CTRL_CHAIN") for i in range(1, count + 1)]
    result["memory"] = [(f"HBM[{i}]", "MEM_HBM", "1", "0x80000") for i in range(4)]
    dispatch = "dispatch:dispatch_1"

    def stream(tag, source, target):
        result["memory"].append((tag, "MEM_STREAMING_CONNECTION", "1", "0"))
        result["connections"] += [(*source, tag), (*target, tag)]

    for i in range(1, 5):
        search = f"bin_search:bin_search_{i}"
        result["connections"] += [(search, argument, f"HBM[{i-1}]") for argument in range(9)]
        stream(f"search{i}", (search, 10), (dispatch, i))
    for i in range(1, 3):
        cache, ddr = f"process_cache:process_cache_{i}", f"process_ddr:process_ddr_{i}"
        result["connections"].append((cache, 0, f"HBM[{2*i-2}]"))
        result["connections"] += [(ddr, argument, f"HBM[{2*i-1}]") for argument in range(4)]
        stream(f"cache{i}", (dispatch, 4+i), (cache, 1))
        stream(f"ddr{i}", (dispatch, 6+i), (ddr, 4))
    return result


def metadata(directory, data):
    directory.mkdir()
    clocks = [{"m_type": kind, "m_name": name, "m_freq_Mhz": str(mhz)} for kind, name, mhz in data["clock"]]
    memory = [{"m_tag": tag, "m_type": kind, "m_used": used, "m_sizeKB": size}
              for tag, kind, used, size in data["memory"]]
    kernels = [{"m_type": "IP_KERNEL", "m_name": name, "m_ip_control": control} for name, control in data["kernels"]]
    ips, tags = {row["m_name"]: i for i, row in enumerate(kernels)}, {row["m_tag"]: i for i, row in enumerate(memory)}
    connections = [{"m_ip_layout_index": str(ips[name]), "arg_index": str(arg), "mem_data_index": str(tags[tag])}
                   for name, arg, tag in data["connections"]]
    for filename, wrapper, field, rows in (("clock", "clock_freq_topology", "m_clock_freq", clocks),
            ("memory", "mem_topology", "m_mem_data", memory), ("ip", "ip_layout", "m_ip_data", kernels),
            ("connectivity", "connectivity", "m_connection", connections)):
        (directory / (filename + ".json")).write_text(json.dumps({wrapper: {"m_count": str(len(rows)), field: rows}}))


TIMING = "WNS(ns) TNS endpoints total WHS THS endpoints total WPWS TPWS endpoints total\n---\n" \
         "0.002 0.000 0 100 0.009 0.000 0 100 1.000 0.000 0 100\n" \
         "All user specified timing constraints are met.\n"


class OriginalGraSURoutedTests(unittest.TestCase):
    def test_complete_topology_and_order_independence(self):
        data = fixture()
        topology.validate(data)
        for rows in data.values():
            rows.reverse()
        topology.validate(data)
        banks, streams = topology.expected_connections()
        self.assertEqual((len(banks), len(streams)), (46, 8))
        self.assertIn(("bin_search:bin_search_4", 8, "HBM[3]"), banks)
        self.assertIn(frozenset((("dispatch:dispatch_1", 8), ("process_ddr:process_ddr_2", 4))), streams)

    def test_missing_extra_and_changed_control_cus(self):
        for damage in ("missing", "extra", "control", "duplicate"):
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                data = fixture()
                if damage == "missing":
                    data["kernels"].pop()
                elif damage in ("extra", "duplicate"):
                    data["kernels"].append(data["kernels"][0] if damage == "duplicate" else ("foreign:foreign_1", "AP_CTRL_CHAIN"))
                else:
                    data["kernels"][0] = (data["kernels"][0][0], "AP_CTRL_HS")
                topology.validate(data)

    def test_every_clock_and_memory_binding_is_required(self):
        for key in ("clock", "connections"):
            for index in range(len(fixture()[key])):
                with self.subTest(key=key, index=index), self.assertRaises(ValueError):
                    data = fixture()
                    data[key].pop(index)
                    topology.validate(data)
        for key, row in (("clock", ("SYSTEM", "hbm_aclk", 430)),
                ("memory", ("HBM[0]", "MEM_HBM", "0", "524288")),
                ("memory", ("HBM[0]", "MEM_HBM", "1", "262144")),
                ("memory", ("HBM[0]", "MEM_DDR4", "1", "524288"))):
            with self.subTest(row=row), self.assertRaises(ValueError):
                data = fixture()
                index = next(i for i, old in enumerate(data[key]) if old[0] == row[0])
                data[key][index] = row
                topology.validate(data)

    def test_bad_tags_arguments_and_stream_pairing_rejected(self):
        mutations = [
            lambda d: d["memory"].append(d["memory"][0]),
            lambda d: d["connections"].append(d["connections"][0]),
            lambda d: d["connections"].__setitem__(0, ("foreign:foreign_1", 0, "HBM[0]")),
            lambda d: d["connections"].__setitem__(0, ("bin_search:bin_search_1", True, "HBM[0]")),
            lambda d: d["connections"].__setitem__(0, ("bin_search:bin_search_1", -1, "HBM[0]")),
            lambda d: d["connections"].__setitem__(0, ("bin_search:bin_search_1", 0, "missing")),
            lambda d: d["connections"].__setitem__(9, ("bin_search:bin_search_1", 9, "search1")),
            lambda d: d["memory"].__setitem__(4, ("search1", "MEM_STREAMING_CONNECTION", "0", "0")),
            lambda d: d["memory"].__setitem__(4, ("search1", "MEM_STREAMING_CONNECTION", "1", "64")),
            lambda d: d["connections"].__setitem__(10, d["connections"][9]),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ValueError):
                data = deepcopy(fixture())
                mutation(data)
                topology.validate(data)

    def test_routed_inspection_never_promotes_board_or_publication_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata(root / "metadata", fixture())
            timing = root / "impl_1_hw_bb_locked_timing_summary_routed.rpt"
            timing.write_text(TIMING)
            result = gates.inspect_routed(root / "metadata", root)
            self.assertEqual(result["timing"]["wns_ns"], 0.002)
            self.assertTrue(all(result[key] is False for key in config.FLAGS))
            self.assertIn("NOT_BOARD_ADMISSION", result["status"])
            for payload in (TIMING.replace("0.002", "-0.002"), TIMING.replace("0.002", "nan"),
                    TIMING.replace("0.009", "-0.009"), TIMING.replace("constraints are met", "constraints fail")):
                timing.write_text(payload)
                with self.assertRaises(ValueError):
                    gates.inspect_routed(root / "metadata", root)
            timing.unlink()
            with self.assertRaises(ValueError):
                gates.inspect_routed(root / "metadata", root)


if __name__ == "__main__":
    unittest.main()
