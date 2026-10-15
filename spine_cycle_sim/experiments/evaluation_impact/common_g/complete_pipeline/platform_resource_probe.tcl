set_param general.maxThreads 2
open_checkpoint [lindex $argv 0]
if {[llength [get_pblocks -quiet pblock_dynamic_SLR0]] == 0} {
    read_xdc [lindex $argv 1]
}
set output [open platform_uram_capacity.csv w]
puts $output "region,uram_sites"
foreach slr {SLR0 SLR1 SLR2} {
    set pblock [get_pblocks pblock_dynamic_$slr]
    if {[llength $pblock] != 1 || [get_property IS_SOFT $pblock]} {
        error "missing hard platform SLR pblock"
    }
    set sites [get_sites -of_objects $pblock -filter {SITE_TYPE =~ URAM*}]
    puts $output "$slr,[llength $sites]"
}
puts $output "device,[llength [get_sites -of_objects [get_pblocks pblock_dynamic_region] -filter {SITE_TYPE =~ URAM*}]]"
close $output
report_utilization -file platform_utilization.rpt
exit
