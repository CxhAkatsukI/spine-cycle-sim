"""Exact routed algorithm ABI checks; no FPGA tools or device programming."""

import copy
import unittest

from test_g_algorithm_inspection import CONFIG, interface
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import inspection, routing, topology


def fixture():
    interfaces = {"pma_to_regraph_adapter": interface("pma_to_regraph_adapter", "write_only"),
                  "consume": interface("consume", "read_only")}
    checked = {"status": routing.PASS, "interfaces": interfaces,
               "connections": inspection.check_connections(CONFIG, interfaces)}
    memory = [{"m_tag": f"HBM[{i}]", "m_type": "MEM_HBM", "m_used": "1", "m_sizeKB": "0x80000"}
              for i in range(32)]
    memory.append({"m_tag": "arbitrary_stream_name", "m_type": "MEM_STREAMING_CONNECTION", "m_used": "1"})
    kernels = [{"m_type": "IP_KERNEL", "m_name": kernel + ":" + instance, "m_ip_control": "AP_CTRL_CHAIN"}
               for kernel, instance in (("pma_to_regraph_adapter", "a"), ("consume", "b"))]
    bindings = [{"m_ip_layout_index": str(ip), "arg_index": str(arg), "mem_data_index": str(bank)}
                for ip, banks in ((0, range(23)), (1, [23])) for arg in (0, 1) for bank in banks]
    bindings += [{"m_ip_layout_index": str(ip), "arg_index": "3", "mem_data_index": "32"} for ip in (0, 1)]
    sections = {"clock": {"clock_freq_topology": {"m_count": "1", "m_clock_freq": [
        {"m_type": "DATA", "m_name": "DATA_CLK", "m_freq_Mhz": "150"}]}},
        "ip": {"ip_layout": {"m_count": "2", "m_ip_data": kernels}},
        "memory": {"mem_topology": {"m_count": str(len(memory)), "m_mem_data": memory}},
        "connectivity": {"connectivity": {"m_count": str(len(bindings)), "m_connection": bindings}}}
    return sections, checked


class TopologyTests(unittest.TestCase):
    def test_actual_aliases_ranges_and_stream_pairs_not_dc_names(self):
        sections, checked = fixture()
        result = topology.check(sections, CONFIG, checked)
        self.assertEqual(result["memory_argument_bindings"], 48)
        self.assertEqual(result["stream_pairs"], 1)
        self.assertEqual(result["kernel_instances"], 2)

    def test_bad_bank_range_rejected(self):
        for bank in ("HBM[32]", "HBM[2:1]", "DDR[0]", "HBM[0:32]"):
            with self.subTest(bank=bank), self.assertRaises(ValueError):
                topology.hbm_banks(bank)

    def test_wrong_clock_cu_control_count_or_capacity_rejected(self):
        changes = [lambda s: s["clock"]["clock_freq_topology"]["m_clock_freq"][0].update(m_freq_Mhz="149"),
                   lambda s: s["ip"]["ip_layout"]["m_ip_data"][0].update(m_ip_control="AP_CTRL_NONE"),
                   lambda s: s["ip"]["ip_layout"]["m_ip_data"][0].update(m_name="wrong:instance"),
                   lambda s: s["ip"]["ip_layout"].update(m_count="3"),
                   lambda s: s["memory"]["mem_topology"]["m_mem_data"][0].update(m_sizeKB="0x40000"),
                   lambda s: s["memory"]["mem_topology"]["m_mem_data"][0].update(m_used="0")]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                sections, checked = fixture()
                change(sections)
                topology.check(sections, CONFIG, checked)

    def test_negative_indices_wrong_alias_extra_or_duplicate_binding_rejected(self):
        for field, value in (("m_ip_layout_index", "-1"), ("mem_data_index", "-1"),
                             ("arg_index", "-1"), ("mem_data_index", "24"), ("arg_index", "2")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                sections, checked = fixture()
                sections["connectivity"]["connectivity"]["m_connection"][0][field] = value
                topology.check(sections, CONFIG, checked)
        sections, checked = fixture()
        table = sections["connectivity"]["connectivity"]
        table["m_connection"].append(copy.deepcopy(table["m_connection"][0]))
        table["m_count"] = str(len(table["m_connection"]))
        with self.assertRaisesRegex(ValueError, "bindings"):
            topology.check(sections, CONFIG, checked)

    def test_wrong_stream_pair_and_stale_review_rejected(self):
        sections, checked = fixture()
        sections["connectivity"]["connectivity"]["m_connection"][-1]["arg_index"] = "2"
        with self.assertRaisesRegex(ValueError, "AXIS"):
            topology.check(sections, CONFIG, checked)
        sections, checked = fixture()
        checked["connections"]["streams"][0]["fifo_depth"] = 16
        with self.assertRaisesRegex(ValueError, "review"):
            topology.check(sections, CONFIG, checked)


if __name__ == "__main__":
    unittest.main()
