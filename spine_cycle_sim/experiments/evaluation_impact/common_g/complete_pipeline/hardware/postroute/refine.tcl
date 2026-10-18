if {[llength $argv] != 2} {error "checkpoint and fresh output directory required"}
set checkpoint [lindex $argv 0]
set output [lindex $argv 1]
set_param general.maxThreads 8
open_checkpoint $checkpoint

foreach {name period} {
    clk_kernel_00_unbuffered_net 6.667
    clk_kernel_01_unbuffered_net 2.000
    hbm_aclk 2.222
} {
    set clock [get_clocks -quiet $name]
    if {[llength $clock] != 1 || abs([get_property PERIOD $clock] - $period) > 0.001} {
        error "Original clock constraint differs: $name"
    }
}
report_clocks -file [file join $output clocks.rpt]
report_timing_summary -delay_type min_max -max_paths 10 -file [file join $output baseline.rpt]

# Retain every pass, including regressions; do not turn the best WNS into board admission.
foreach {label options} {
    clock_opt {-clock_opt}
    fanout {-directive AggressiveFanoutOpt}
    replication {-directive AlternateReplication}
} {
    phys_opt_design {*}$options
    report_timing_summary -delay_type min_max -max_paths 10 -file [file join $output ${label}.rpt]
}
report_route_status -file [file join $output final_route_status.rpt]
report_drc -file [file join $output final_drc.rpt]
write_checkpoint [file join $output refined.dcp]
puts "POSTROUTE_DIAGNOSTIC_FINISHED_NOT_BITSTREAM_OR_BOARD_ADMISSION"
