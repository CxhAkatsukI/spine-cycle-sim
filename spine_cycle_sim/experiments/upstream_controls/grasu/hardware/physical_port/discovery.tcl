# HMSS's stock callbacks assume one addressing master, even across SmartConnect.
namespace eval ::spine_g_ports {
    variable discovery_callbacks [dict create]

    proc same_net {left right description} {
        set actual [lsort [get_bd_intf_pins -of_objects [one \
            [get_bd_intf_nets -of_objects [get_bd_intf_pins $left]] "$description net"]]]
        if {$actual ne [lsort [list $left $right]]} {error "Changed $description: $actual"}
    }

    proc common_master {slave} {
        variable groups
        set endpoints [find_bd_objs -thru_hier -relation addressing_master $slave]
        dict for {name state} $groups {
            if {[dict get $state slave] ne $slave} {continue}
            set members [dict get $state members]
            if {[llength $members] != 4 || [lsort $endpoints] ne [lsort $members]} {
                error "Unexpected addressing masters behind $name: $endpoints"
            }
            same_net $name/M00_AXI $slave "SmartConnect output"
            foreach pin {aclk aresetn} key {clock reset} {
                if {[one [get_bd_nets -of_objects [get_bd_pins $name/$pin]] "$name $pin net"] \
                        ne [dict get $state $key]} {error "Changed SmartConnect $pin: $name"}
            }
            set slrs {}
            set index 0
            foreach master $members {
                same_net $master [format %s/S%02d_AXI $name $index] "metadata lane"
                set clock_name [one [::hbm_memory_subsystem::util::find_associated_clock_pin $master] "member clock"]
                set clock [one [get_bd_pins $clock_name] "member clock object"]
                set cell [one [get_bd_cells -of_objects $master] "member cell"]
                set reset_name [get_property CONFIG.ASSOCIATED_RESET $clock]
                set reset [one [get_bd_pins $cell/$reset_name] "member reset"]
                foreach object [list $clock $reset] key {clock reset} {
                    if {[one [get_bd_nets -of_objects $object] "member $key net"] ne [dict get $state $key]} {
                        error "Metadata members do not share $key: $name"
                    }
                }
                set space [one [get_bd_addr_space -of_objects $master] "member address space"]
                set segment [one [get_bd_addr_segs -of_objects $space] "member address segment"]
                foreach property {RANGE OFFSET} key {range offset} {
                    if {[get_property $property $segment] ne [dict get $state $key]} {
                        error "Metadata address changed: $master"
                    }
                }
                lappend slrs [get_property CONFIG.SLR_ASSIGNMENT [get_bd_intf_pins $master]]
                incr index
            }
            if {[llength [lsort -unique $slrs]] != 1} {error "Metadata SLR assignments differ: $name"}
            # Every physical lane has the same attributes; keep the stock checks.
            return [lindex $members 0]
        }
        return $endpoints
    }

    proc install_discovery {scope} {
        variable discovery_callbacks
        set prefix [expr {$scope eq {::} ? {} : $scope}]
        set needle {[find_bd_objs -thru_hier -relation addressing_master $si]}
        foreach name {set_slr_info_env set_clkrst_info_env} {
            set target ${prefix}::$name
            if {![llength [info procs $target]]} {continue}
            set body [info body $target]
            if {[dict exists $discovery_callbacks $target]} {
                if {$body ne [dict get $discovery_callbacks $target patched]} {
                    error "HMSS discovery callback redefined: $target"
                }
                continue
            }
            if {[info args $target] ne {cell} || [llength [split $body \n]] < 10 \
                    || [string first $needle $body] < 0 \
                    || [string first $needle $body [expr {[string first $needle $body] + 1}]] >= 0 \
                    || [string first send_msg_id $body] < 0} {
                error "Unsupported HMSS discovery callback: $target"
            }
            set patched [string map [list $needle {[::spine_g_ports::common_master $si]}] $body]
            dict set discovery_callbacks $target [dict create original_crc [format %08x [zlib crc32 $body]] patched $patched]
            proc $target {cell} $patched
            puts "SPINE_HMSS_COMMON_ATTRIBUTE_DISCOVERY $target original_crc=[dict get $discovery_callbacks $target original_crc]"
        }
    }

    proc check_discovery {} {
        variable discovery_callbacks
        if {[dict size $discovery_callbacks] != 2} {error "Exactly two adapted HMSS discovery callbacks required"}
        dict for {target state} $discovery_callbacks {
            if {[info body $target] ne [dict get $state patched]} {error "Changed HMSS callback: $target"}
        }
        foreach key {HMSS_RA_PORT_LIST HMSS_PORTLOC_PORT_DICT} {
            if {[info exists ::env($key)] && $::env($key) ne {}} {
                error "Additional per-master HMSS constraints need a separate fan-in contract: $key"
            }
        }
    }
}
