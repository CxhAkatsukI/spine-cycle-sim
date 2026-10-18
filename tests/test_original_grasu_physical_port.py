"""External AXI control contracts; these mocks do not validate Vivado or FPGA timing."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.physical_port import probe


ASSETS = Path(probe.__file__).parent


def proof(path):
    root = ET.Element("physical_port", profile=probe.PROFILE,
        masters="46", kernel_ingress="22", host_ingress="1", source_modified="false",
        routed="false", board_measured="false")
    for cu in range(1, 5):
        for half in range(2):
            group = ET.SubElement(root, "group", name=f"/g_metadata_{cu}_{half}",
                bank=f"HBM_MEM{cu-1:02d}", slave=f"/hmss_0/S{cu*2+half:02d}_AXI",
                clock="clock", reset="reset")
            for index in range(4):
                ET.SubElement(group, "master", name=f"/bin_search_{cu}/m_axi_gmem{half*4+index}")
    ET.ElementTree(root).write(path)
    return root


class OriginalGPhysicalPortTests(unittest.TestCase):
    def tcl(self, body):
        if not shutil.which("tclsh"):
            self.skipTest("tclsh unavailable")
        script = f"""
if {{[catch {{
source {{{ASSETS / 'pre_link.tcl'}}}
{body}
}} message]}} {{puts stderr $message; exit 1}}
"""
        return subprocess.run(["tclsh"], input=script, text=True, capture_output=True, timeout=10)

    def test_exact_metadata_groups_and_direct_edge_path(self):
        result = self.tcl("""
for {set cu 1} {$cu <= 4} {incr cu} {
    for {set port 0} {$port < 8} {incr port} {
        set bank [list [format HBM_MEM%02d [expr {$cu-1}]]]
        set actual [::spine_g_ports::classify /bin_search_$cu/m_axi_gmem$port $bank]
        set expected [list /g_metadata_${cu}_[expr {$port/4}] [expr {$port%4}]]
        if {$actual ne $expected} {error "wrong grouping"}
    }
}
if {[::spine_g_ports::classify /bin_search_1/m_axi_gmem_edges HBM_MEM00] ne {}} {error "edge grouped"}
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_bank_and_nonzero_first_lane_fail_before_bd_edit(self):
        for body in (
                "::spine_g_ports::classify /bin_search_1/m_axi_gmem0 HBM_MEM01",
                "::spine_g_ports::map /bin_search_1/m_axi_gmem1 /hmss_0 HBM_MEM00"):
            result = self.tcl(body)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("invalid command name", result.stderr)

    def test_resolved_clock_and_two_endpoints_preserve_original_hmss_net(self):
        result = self.tcl("""
namespace eval ::hbm_memory_subsystem::util {}
proc ::hbm_memory_subsystem::util::find_associated_clock_pin {master} {return /bin_search_1/ap_clk}
proc ::hbm_memory_subsystem::spine_original_map {args} {}
proc get_bd_intf_nets {args} {return master_net}
proc get_bd_intf_pins {args} {
    if {[lindex $args 0] eq {-of_objects}} {return {/bin_search_1/m_axi_gmem0 /hmss_0/S02_AXI}}
    return [lindex $args 0]
}
proc get_bd_addr_segs {args} {return segment}
proc get_bd_addr_space {args} {return space}
proc get_bd_cells {args} {return /bin_search_1}
proc get_bd_pins {name} {return object:$name}
proc get_property {name object} {
    if {$name eq {CONFIG.ASSOCIATED_RESET}} {
        if {$object ne {object:/bin_search_1/ap_clk}} {error {raw clock name is not a BD pin object}}
        return ap_rst_n
    }
    if {$name eq {RANGE}} {return 0x10000000}
    if {$name eq {OFFSET}} {return 0}
    error unexpected_property
}
proc get_bd_nets {args} {return clock_or_reset_net}
foreach command {create_bd_cell set_property connect_bd_net disconnect_bd_intf_net} {
    proc $command {args} {}
}
proc connect_bd_intf_net {args} {
    if {[lindex $args 0] eq {-intf_net}} {
        if {$args ne {-intf_net master_net /g_metadata_1_0/M00_AXI /hmss_0/S02_AXI}} {
            error {retained HMSS net requires both explicit interface endpoints}
        }
        set ::retained_connection $args
    } elseif {$args ne {/bin_search_1/m_axi_gmem0 /g_metadata_1_0/S00_AXI}} {
        error {unexpected author-master connection}
    }
}
::spine_g_ports::map /bin_search_1/m_axi_gmem0 /hmss_0 HBM_MEM00
if {![info exists ::retained_connection]} {error missing_hmss_connection}
if {[dict get $::spine_g_ports::groups /g_metadata_1_0 members] ne {/bin_search_1/m_axi_gmem0}} {
    error missing_first_master
}
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_vendor_mapper_is_preserved_and_duplicate_mapping_rejected(self):
        body = """
namespace eval ::hbm_memory_subsystem {}
proc ::hbm_memory_subsystem::map_memory_resource {master hmss memory} {return vendor_called}
::spine_g_ports::install
::spine_g_ports::install
set first [::hbm_memory_subsystem::map_memory_resource /process_cache_1/m_axi_gmem0 /hmss_0 HBM_MEM00]
if {$first ne {vendor_called}} {error "original mapper not called"}
"""
        result = self.tcl(body)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.tcl(body + "::spine_g_ports::map /process_cache_1/m_axi_gmem0 /hmss_0 HBM_MEM00")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate memory mapping", result.stderr)

    def test_delayed_vendor_source_is_hooked_and_redefinition_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            vendor = Path(directory) / "vendor.tcl"
            vendor.write_text("namespace eval ::hbm_memory_subsystem {\n"
                              "proc map_memory_resource {m h b} {return vendor_called}\n}\n")
            result = self.tcl(f"source {{{vendor}}}\n"
                "if {!$::spine_g_ports::installed} {error missing_hook}\n")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = self.tcl(f"source {{{vendor}}}\nsource {{{vendor}}}\n")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("redefined", result.stderr)

    def test_proof_rejects_missing_duplicate_moved_or_claimed_data(self):
        for damage in (None, "missing", "duplicate", "bank", "master", "clock", "claim", "slave"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "proof.xml"
                root = proof(path)
                if damage == "missing": root.remove(root[-1])
                if damage == "duplicate": root[-1].set("name", root[0].get("name"))
                if damage == "bank": root[0].set("bank", "HBM_MEM01")
                if damage == "master": root[0][0].set("name", "/compacted")
                if damage == "clock": root[0].set("clock", "")
                if damage == "claim": root.set("routed", "true")
                if damage == "slave": root[-1].set("slave", root[0].get("slave"))
                ET.ElementTree(root).write(path)
                if damage is None:
                    self.assertEqual(probe.inspect_proof(path)["retained_masters"], 46)
                else:
                    with self.assertRaises(ValueError): probe.inspect_proof(path)

    def test_bad_parent_stops_before_environment_and_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(probe, "inputs", side_effect=ValueError("wrong parent")), \
                    patch.object(probe.environment, "capture") as capture, \
                    patch.object(probe, "run_link") as tool, self.assertRaises(ValueError):
                probe.run(root, root, root / "new", root, root, root, root)
            capture.assert_not_called()
            tool.assert_not_called()


if __name__ == "__main__":
    unittest.main()
