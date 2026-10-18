# Keep every author AXI master; share only same-bank metadata outside the CUs.
namespace eval ::spine_g_ports {
    variable groups [dict create]
    variable calls [dict create]
    variable installed 0

    proc one {objects description} {
        if {[llength $objects] != 1} {error "Expected one $description, got: $objects"}
        return [lindex $objects 0]
    }

    proc classify {master memory} {
        if {[regexp {^/bin_search_([1-4])/m_axi_gmem([0-7])$} $master -> cu port]} {
            set bank [format HBM_MEM%02d [expr {$cu - 1}]]
            if {$memory ne [list $bank]} {error "Metadata bank changed for $master"}
            return [list [format /g_metadata_%d_%d $cu [expr {$port / 4}]] [expr {$port % 4}]]
        }
        return {}
    }

    proc map {master hmss memory} {
        variable groups
        variable calls
        set master [one $master master]
        if {[dict exists $calls $master]} {error "Duplicate memory mapping: $master"}
        dict set calls $master $memory
        set group [classify $master $memory]
        if {$group eq {}} {
            return [::hbm_memory_subsystem::spine_original_map $master $hmss $memory]
        }
        lassign $group name index
        if {![dict exists $groups $name]} {
            if {$index != 0} {error "Metadata group must start with lane zero: $master"}
            ::hbm_memory_subsystem::spine_original_map $master $hmss $memory
            set net [one [get_bd_intf_nets -of_objects $master] "original master net"]
            set endpoints [get_bd_intf_pins -of_objects $net]
            set slaves [lsearch -all -inline -glob $endpoints $hmss/S*_AXI]
            set slave [one $slaves "HMSS slave"]
            set segment [one [get_bd_addr_segs -of_objects $slave] "HBM segment"]
            set space [one [get_bd_addr_space -of_objects $master] "master address space"]
            set assigned [one [get_bd_addr_segs -of_objects $space] "assigned HBM segment"]
            set range [get_property RANGE $assigned]
            set offset [get_property OFFSET $assigned]
            set clock_name [one [::hbm_memory_subsystem::util::find_associated_clock_pin $master] "master clock name"]
            set clock [one [get_bd_pins $clock_name] "master clock object"]
            set reset_name [get_property CONFIG.ASSOCIATED_RESET $clock]
            set cell [one [get_bd_cells -of_objects $master] "master cell"]
            set reset [one [get_bd_pins $cell/$reset_name] "master reset"]
            set clock_net [one [get_bd_nets -of_objects $clock] "clock net"]
            set reset_net [one [get_bd_nets -of_objects $reset] "reset net"]
            create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 $name
            set_property -dict [list CONFIG.NUM_SI 4 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 1] [get_bd_cells $name]
            connect_bd_net -net $clock_net [get_bd_pins $name/aclk]
            connect_bd_net -net $reset_net [get_bd_pins $name/aresetn]
            disconnect_bd_intf_net $net [get_bd_intf_pins $master]
            set upstream [one [get_bd_intf_pins $name/M00_AXI] "SmartConnect master"]
            set downstream [one [get_bd_intf_pins $slave] "retained HMSS slave"]
            connect_bd_intf_net -intf_net $net $upstream $downstream
            dict set groups $name [dict create slave $slave segment $segment range $range offset $offset \
                bank $memory clock $clock_net reset $reset_net members {}]
        }
        set state [dict get $groups $name]
        if {[dict get $state bank] ne $memory || [llength [dict get $state members]] != $index} {
            error "Metadata group bank/order changed: $master"
        }
        connect_bd_intf_net [get_bd_intf_pins $master] [get_bd_intf_pins [format %s/S%02d_AXI $name $index]]
        if {$index != 0} {
            set space [one [get_bd_addr_space -of_objects $master] "new master address space"]
            if {[llength [get_bd_addr_segs -of_objects $space]]} {error "Already mapped metadata master: $master"}
            create_bd_addr_seg -range [dict get $state range] -offset [dict get $state offset] \
                $space [dict get $state segment] [lindex $memory 0]
        }
        dict lappend state members $master
        dict set groups $name $state
    }

    proc install {} {
        variable installed
        set target ::hbm_memory_subsystem::map_memory_resource
        if {![llength [info procs $target]]} {return}
        if {[info body $target] eq {::spine_g_ports::map $master_interface $hmss_cell $memory_dict}} {return}
        if {$installed} {error "Vendor memory mapper was redefined after hook installation"}
        rename $target ::hbm_memory_subsystem::spine_original_map
        proc ::hbm_memory_subsystem::map_memory_resource {master_interface hmss_cell memory_dict} {::spine_g_ports::map $master_interface $hmss_cell $memory_dict}
        set installed 1
    }

    proc after_source {command code result operation} {
        if {$code == 0} {install}
    }
}

::spine_g_ports::install
# The vendor loads its mapper while creating HMSS, after the pre-syslink hook.
trace add execution ::source leave ::spine_g_ports::after_source
