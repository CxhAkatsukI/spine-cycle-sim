import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.bitstream import normalized_topology, parse_routed_timing
from spine_cycle_sim.experiments.sharded_k4_stages.board import hardware_command, require_idle_board
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link, tree_rss_kib
from spine_cycle_sim.experiments.sharded_k4_stages.routing import adapter_interface, relocate_config
from spine_cycle_sim.experiments.sharded_k4_stages.rtl import parse_cosim_report


class RouteGateTests(unittest.TestCase):
    def test_process_tree_includes_workers_but_not_other_users(self):
        table = "10 1 10 100\n11 10 10 200\n12 11 12 300\n13 1 10 400\n20 1 20 9000\n"
        self.assertEqual(tree_rss_kib(table, 10), (1000, [10, 11, 12, 13]))
        with self.assertRaises(ValueError):
            tree_rss_kib("1 2 3", 1)

    def test_config_preserves_repeated_keys_and_topology(self):
        top = "platform=frozen.xpfm\nsave-temps=1\n"
        for key in ("messageDb", "temp_dir", "report_dir", "log_dir", "remote_ip_cache"):
            top += f"{key}=/frozen/{key}\n"
        topology = "[connectivity]\nnk=adapter:4\nnk=gather:4\nsp=a:HBM[0:22]\nsp=b:HBM[23]\n"
        contents = top + topology
        relocated = relocate_config(contents, Path("/candidate"))
        self.assertEqual(relocated.split("[connectivity]")[1], topology.split("[connectivity]")[1])
        self.assertIn("remote_ip_cache=/candidate/ip_cache", relocated)
        self.assertTrue(relocated.startswith("platform=frozen.xpfm\nsave-temps=1\n"))
        with self.assertRaises(ValueError):
            relocate_config(contents.replace("temp_dir=/frozen/temp_dir\n", ""), Path("/candidate"))
        with self.assertRaises(ValueError):
            relocate_config("temp_dir=x\n" + contents, Path("/candidate"))

    def test_xo_reads_structured_abi_and_both_define_styles(self):
        xml = ('<root><kernel name="pma_to_regraph_adapter" hwControlProtocol="ap_ctrl_chain" '
               'compileOptions="-D A=1 -DB=2"><ports><port name="GMEM0" dataWidth="512"/>'
               '</ports><args><arg name="pma0" id="0" offset="0x10"/></args></kernel></root>')
        with tempfile.TemporaryDirectory() as directory:
            xo = Path(directory) / "adapter.xo"
            with zipfile.ZipFile(xo, "w") as archive:
                archive.writestr("adapter/kernel.xml", xml)
            abi, flags = adapter_interface(xo)
            self.assertEqual(flags, {"A": "1", "B": "2"})
            self.assertEqual(abi["args"][0]["offset"], "0x10")
            self.assertEqual(abi["ports"][0]["dataWidth"], "512")

    def test_cosim_requires_a_unique_passing_rtl_row(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "cosim.rpt"
            report.write_text("| Verilog | Pass | 12 | 100 | 200 | NA | NA | NA |\n")
            self.assertEqual(parse_cosim_report(report)["latency_max_cycles"], 200)
            for contents in ("| Verilog | Fail | 12 | 100 | 200 |", "| Verilog | Pass | NA | NA | NA |",
                             report.read_text() * 2):
                report.write_text(contents)
                with self.assertRaises(ValueError):
                    parse_cosim_report(report)

    def test_watchdog_saves_exit_and_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            complete = run_link([sys.executable, "-c", "print('done')"], root,
                                root / "complete", timeout=5, tree_memory_gib=1,
                                reserve_gib=0, poll_seconds=0.02)
            self.assertEqual(complete["exit_code"], 0)
            self.assertEqual(complete["stop_reason"], "process_exit")
            killed = run_link([sys.executable, "-c", "import time; time.sleep(10)"], root,
                              root / "timeout", timeout=1, tree_memory_gib=1,
                              reserve_gib=0, poll_seconds=0.02)
            self.assertEqual(killed["stop_reason"], "timeout")
            self.assertLess(killed["exit_code"], 0)
            self.assertEqual(json.loads((root / "timeout.resources.json").read_text()), killed)

    def test_clock_and_connectivity_normalize_indices_not_addresses(self):
        sections = {
            "clock": {"clock_freq_topology": {"m_count": "1", "m_clock_freq": [
                {"m_type": "DATA", "m_name": "DATA_CLK", "m_freq_Mhz": "150"}]}},
            "memory": {"mem_topology": {"m_count": "2", "m_mem_data": [
                {"m_tag": "HBM[0]", "m_type": "MEM_HBM", "m_used": "1", "m_sizeKB": "0x80000"},
                {"m_tag": "HBM[23]", "m_type": "MEM_HBM", "m_used": "1", "m_sizeKB": "0x80000"}]}},
            "ip": {"ip_layout": {"m_count": "2", "m_ip_data": [
                {"m_name": "adapter:adapter_1", "m_type": "IP_KERNEL", "m_ip_control": "AP_CTRL_CHAIN"},
                {"m_name": "hbm:hbm_1", "m_type": "IP_KERNEL", "m_ip_control": "AP_CTRL_CHAIN"}]}},
            "connectivity": {"connectivity": {"m_count": "2", "m_connection": [
                {"m_ip_layout_index": "0", "arg_index": "0", "mem_data_index": "0"},
                {"m_ip_layout_index": "1", "arg_index": "2", "mem_data_index": "1"}]}},
        }
        expected = normalized_topology(sections)
        altered = json.loads(json.dumps(sections))
        altered["ip"]["ip_layout"]["m_ip_data"].reverse()
        for row in altered["connectivity"]["connectivity"]["m_connection"]:
            row["m_ip_layout_index"] = str(1 - int(row["m_ip_layout_index"]))
        self.assertEqual(expected, normalized_topology(altered))
        altered["connectivity"]["connectivity"]["m_connection"][0]["mem_data_index"] = "1"
        self.assertNotEqual(expected, normalized_topology(altered))
        altered["ip"]["ip_layout"]["m_count"] = "3"
        with self.assertRaises(ValueError):
            normalized_topology(altered)

    def test_timing_rejects_setup_hold_and_pulse_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "timing.rpt"
            columns = ["0.003", "0.000", "0", "100", "0.009", "0.000", "0", "100",
                       "0.000", "0.000", "0", "100"]
            def write(values):
                report.write_text("    WNS(ns) TNS(ns) ...\n -----\n " + " ".join(values) +
                                  "\n\nAll user specified timing constraints are met.\n")
            write(columns)
            self.assertEqual(parse_routed_timing(report)["wns_ns"], 0.003)
            for index in (0, 4, 8):
                bad = list(columns)
                bad[index] = "-0.001"
                write(bad)
                with self.assertRaises(ValueError):
                    parse_routed_timing(report)

    def test_board_check_rejects_occupancy_and_fuser_errors(self):
        from subprocess import CompletedProcess
        for code in (0, 2):
            with patch("spine_cycle_sim.experiments.sharded_k4_stages.board.subprocess.run",
                       return_value=CompletedProcess([], code, "123", "")):
                with self.assertRaises(RuntimeError):
                    require_idle_board(Path("/dev/example"))
        with patch("spine_cycle_sim.experiments.sharded_k4_stages.board.subprocess.run",
                   return_value=CompletedProcess([], 1, "", "")):
            require_idle_board(Path("/dev/example"))

    def test_shared_host_command_preserves_production_flags(self):
        command = hardware_command(Path("/integration"), {"algorithm": "weighted_sssp", "graph": "/graph", "source": "0"},
                                   Path("/host"), Path("/original.xclbin"), Path("/run"), 0, 600, "1")
        self.assertEqual(command[:5], ["env", "GRASU_SHARDED_EVENT_TRACE=1", "GRASU_UPDATE_REPEATS=1",
                                       "bash", "/integration/scripts/run_pma_native_hw.sh"])
        for key, value in (("--source", "0"), ("--max-supersteps", "256"), ("--timeout", "580"),
                           ("--device-index", "0"), ("--xclbin", "/original.xclbin")):
            self.assertEqual(command[command.index(key) + 1], value)


if __name__ == "__main__":
    unittest.main()
