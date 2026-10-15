if {$argc != 2} { error "checkpoint and fresh output directory required" }
lassign $argv checkpoint output
set_param general.maxThreads 2
open_checkpoint $checkpoint

proc write_row {handle values} {
    foreach value $values {
        if {[regexp {[\t\r\n]} $value]} { error "unsafe TSV field" }
    }
    puts $handle [join $values "\t"]
}

set handle [open [file join $output design.tsv] w]
write_row $handle {tool_version design part}
write_row $handle [list [version -short] [get_property NAME [current_design]] [get_property PART [current_design]]]
close $handle
set handle [open [file join $output clocks.tsv] w]
write_row $handle {name period_ns waveform generated}
foreach clock [lsort [get_clocks -quiet]] {
    write_row $handle [list $clock [get_property PERIOD $clock] [get_property WAVEFORM $clock] [get_property IS_GENERATED $clock]]
}
close $handle
report_clocks -file [file join $output clocks.rpt]
report_route_status -file [file join $output route_status.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -max_paths 10 -file [file join $output timing.rpt]
close_design
exit
