trace remove execution ::source leave ::spine_g_ports::after_source
if {!$::spine_g_ports::installed} {error "Metadata fan-in hook was never installed"}
::spine_g_ports::check_discovery
set expected [dict create]
for {set cu 1} {$cu <= 4} {incr cu} {
    set bank [list [format HBM_MEM%02d [expr {$cu - 1}]]]
    dict set expected /bin_search_$cu/m_axi_gmem_edges $bank
    for {set port 0} {$port < 8} {incr port} {dict set expected /bin_search_$cu/m_axi_gmem$port $bank}
}
foreach {cu bank} {1 HBM_MEM00 2 HBM_MEM02} {dict set expected /process_cache_$cu/m_axi_gmem0 [list $bank]}
foreach {cu bank} {1 HBM_MEM01 2 HBM_MEM03} {
    for {set port 0} {$port < 4} {incr port} {dict set expected /process_ddr_$cu/m_axi_gmem$port [list $bank]}
}
if {[lsort [dict keys $expected]] ne [lsort [dict keys $::spine_g_ports::calls]]} {
    error "Author master set changed"
}
dict for {master bank} $expected {
    if {[dict get $::spine_g_ports::calls $master] ne $bank} {error "Bank changed: $master"}
}
if {[dict size $::spine_g_ports::groups] != 8 || [get_property CONFIG.NUM_SI [get_bd_cells /hmss_0]] != 23} {
    error "Expected eight 4:1 metadata groups and 22 kernel + one host HMSS ingress"
}
set proof [open [file join [file dirname [info script]] physical_port.xml] w]
puts $proof {<physical_port profile="original_g_external_metadata_4to1_common_attributes_v2" masters="46" kernel_ingress="22" host_ingress="1" source_modified="false" routed="false" board_measured="false">}
dict for {name state} $::spine_g_ports::groups {
    if {[llength [dict get $state members]] != 4} {error "Incomplete metadata group: $name"}
    if {[::spine_g_ports::common_master [dict get $state slave]] ne [lindex [dict get $state members] 0]} {
        error "Unverified HMSS fan-in group: $name"
    }
    puts $proof [format {  <group name="%s" bank="%s" slave="%s" clock="%s" reset="%s">} \
        $name [dict get $state bank] [dict get $state slave] [dict get $state clock] [dict get $state reset]]
    foreach master [dict get $state members] {
        set space [::spine_g_ports::one [get_bd_addr_space -of_objects $master] "checked address space"]
        set segment [::spine_g_ports::one [get_bd_addr_segs -of_objects $space] "checked address segment"]
        foreach property {RANGE OFFSET} key {range offset} {
            if {[get_property $property $segment] ne [dict get $state $key]} {error "Address changed: $master"}
        }
        puts $proof [format {    <master name="%s"/>} $master]
    }
    puts $proof {  </group>}
}
puts $proof {</physical_port>}
close $proof
puts {SPINE_ORIGINAL_G_PHYSICAL_PORT_BD_ONLY_NOT_ROUTING_OR_BOARD_ADMISSION}
