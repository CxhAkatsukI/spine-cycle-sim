"""Synthetic common-attribute discovery; not vendor/tool or board validation."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_original_grasu_physical_port import ASSETS


TOPOLOGY = r"""
namespace eval ::hbm_memory_subsystem::util {}
proc ::hbm_memory_subsystem::util::find_associated_clock_pin {master} {return ${master}_clk}
set ::members {}
for {set index 0} {$index < 4} {incr index} {lappend ::members /bin_search_1/m_axi_gmem$index}
set ::spine_g_ports::groups [dict create /g_metadata_1_0 [dict create \
    slave /hmss_0/S02_AXI members $::members clock clk reset rst range 0x1000 offset 0]]
set ::damage none
proc find_bd_objs {args} {
    if {[lindex $args end] ne {/hmss_0/S02_AXI}} {return {direct1 direct2}}
    if {$::damage eq {masters}} {return [lrange $::members 0 2]}
    return $::members
}
proc get_bd_intf_nets {args} {return net:[lindex $args end]}
proc get_bd_intf_pins {args} {
    if {[lindex $args 0] ne {-of_objects}} {return [lindex $args 0]}
    set net [lindex $args 1]
    if {$net eq {net:/g_metadata_1_0/M00_AXI}} {
        if {$::damage eq {output}} {return {/g_metadata_1_0/M00_AXI /hmss_0/S03_AXI}}
        return {/g_metadata_1_0/M00_AXI /hmss_0/S02_AXI}
    }
    regexp {gmem([0-3])$} $net -> index
    if {$::damage eq {lane} && $index == 2} {return {wrong lane}}
    return [list /bin_search_1/m_axi_gmem$index [format /g_metadata_1_0/S%02d_AXI $index]]
}
proc get_bd_pins {pin} {return $pin}
proc get_bd_cells {args} {return /bin_search_1}
proc get_bd_nets {args} {
    set pin [lindex $args end]
    if {[string match *rst* $pin] || [string match *reset* $pin]} {
        if {$::damage eq {reset} && $pin eq {/bin_search_1/ap_rst_n}} {return wrong_reset}
        return rst
    }
    if {$::damage eq {clock} && [string match *gmem2* $pin]} {return wrong_clock}
    if {$::damage eq {sc_clock} && $pin eq {/g_metadata_1_0/aclk}} {return wrong_sc_clock}
    return clk
}
proc get_bd_addr_space {args} {return [lindex $args end]}
proc get_bd_addr_segs {args} {return [lindex $args end]}
proc get_property {property object} {
    switch $property {
        CONFIG.ASSOCIATED_RESET {return ap_rst_n}
        CONFIG.SLR_ASSIGNMENT {
            if {$::damage eq {slr} && [string match *gmem2 $object]} {return SLR1}
            return SLR0
        }
        RANGE {return 0x1000}
        OFFSET {
            if {$::damage eq {address} && [string match *gmem2 $object]} {return 0x1000}
            return 0
        }
    }
    error unexpected_property
}
"""


def vendor_callback(name):
    lines = [f"proc {name} {{cell}} {{", "set si /hmss_0/S02_AXI",
             "set endpoint [find_bd_objs -thru_hier -relation addressing_master $si]",
             "if {[llength $endpoint] != 1} {send_msg_id VENDOR ERROR {not one master}}"]
    lines += [f"set preserved_{index} 1" for index in range(8)]
    return "\n".join([*lines, "return $endpoint", "}"])


class HmssDiscoveryTests(unittest.TestCase):
    def tcl(self, body, prelude=""):
        if not shutil.which("tclsh"):
            self.skipTest("tclsh unavailable")
        script = f"if {{[catch {{\n{prelude}\nsource {{{ASSETS / 'pre_link.tcl'}}}\n{body}\n}} message]}} {{puts stderr $message; exit 1}}"
        return subprocess.run(["tclsh"], input=script, text=True, capture_output=True, timeout=10)

    def test_preloaded_global_and_nested_callbacks(self):
        callbacks = "\n".join(vendor_callback(name) for name in
            ("set_slr_info_env", "set_clkrst_info_env"))
        for scope in ("::", "::platform::hmss::callbacks"):
            with self.subTest(scope=scope):
                result = self.tcl(TOPOLOGY + f"""
proc send_msg_id {{id severity message}} {{error $message}}
::spine_g_ports::check_discovery
::spine_g_ports::install_loaded_discovery
if {{[{scope}::set_slr_info_env /hmss_0] ne {{/bin_search_1/m_axi_gmem0}}}} {{error preloaded_discovery}}
""", prelude=f"namespace eval {scope} {{\n{callbacks}\n}}")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.count("SPINE_HMSS_COMMON_ATTRIBUTE_DISCOVERY"), 2)

    def test_preloaded_unsupported_callback_fails_at_hook_installation(self):
        result = self.tcl("error hook_should_not_finish", prelude=
            "namespace eval ::platform::hmss {proc set_slr_info_env {different} {return 1}}")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported HMSS discovery callback", result.stderr)
        self.assertNotIn("hook_should_not_finish", result.stderr)

    def test_checked_fanin_and_unchanged_direct_discovery(self):
        result = self.tcl(TOPOLOGY + """
if {[::spine_g_ports::common_master /hmss_0/S02_AXI] ne {/bin_search_1/m_axi_gmem0}} {error representative}
if {[::spine_g_ports::common_master /hmss_0/S03_AXI] ne {direct1 direct2}} {error direct_changed}
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_wiring_clock_reset_slr_and_address_fail(self):
        for damage in ("masters", "output", "lane", "clock", "reset", "sc_clock", "slr", "address"):
            with self.subTest(damage=damage):
                result = self.tcl(TOPOLOGY + f"\nset ::damage {damage}\n::spine_g_ports::common_master /hmss_0/S02_AXI")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("invalid command", result.stderr)

    def test_delayed_scoped_callbacks_preserve_stock_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            vendor = Path(directory) / "vendor.tcl"
            vendor.write_text("\n".join(vendor_callback(name) for name in
                ("set_slr_info_env", "set_clkrst_info_env")))
            body = TOPOLOGY + f"""
proc send_msg_id {{id severity message}} {{error $message}}
namespace eval ::mock_hmss {{source {{{vendor}}}}}
::spine_g_ports::check_discovery
::spine_g_ports::install_discovery ::mock_hmss
if {{[::mock_hmss::set_slr_info_env /hmss_0] ne {{/bin_search_1/m_axi_gmem0}}}} {{error bad_discovery}}
"""
            result = self.tcl(body)
            self.assertEqual(result.returncode, 0, result.stderr)
            # An unknown direct port still reaches the original cardinality error.
            result = self.tcl(body + "\nset patched [string map {/hmss_0/S02_AXI /hmss_0/S03_AXI} [info body ::mock_hmss::set_slr_info_env]]\n"
                "proc ::mock_hmss::set_slr_info_env {cell} $patched\n::mock_hmss::set_slr_info_env /hmss_0")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not one master", result.stderr)

    def test_missing_unknown_or_replaced_callbacks_rejected(self):
        bodies = ["::spine_g_ports::check_discovery",
            "namespace eval ::bad {proc set_slr_info_env {different} {return 1}}\n::spine_g_ports::install_discovery ::bad",
            vendor_callback("set_slr_info_env") + "\n::spine_g_ports::install_discovery ::\n"
            "proc ::set_slr_info_env {cell} {return 1}\n::spine_g_ports::install_discovery ::"]
        for body in bodies:
            with self.subTest(body=body):
                result = self.tcl(body)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("invalid command", result.stderr)


if __name__ == "__main__":
    unittest.main()
