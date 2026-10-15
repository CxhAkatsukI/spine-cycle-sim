set_param general.maxThreads 2
set part xcu55c-fsvh2892-2L-e
create_project -in_memory -part $part
read_verilog [lindex $argv 0]
synth_design -top resource_probe -part $part
set output [open uram_capacity.csv w]
puts $output "region,uram_sites"
foreach slr [lsort [get_slrs]] {
    set sites [get_sites -of_objects $slr -filter {SITE_TYPE =~ URAM*}]
    puts $output "$slr,[llength $sites]"
}
puts $output "device,[llength [get_sites -filter {SITE_TYPE =~ URAM*}]]"
close $output
report_utilization -file device_utilization.rpt
exit
