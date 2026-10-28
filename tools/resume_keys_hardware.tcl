set ROOT [file normalize [file dirname [info script]]/..]
set OUT $ROOT/build/keys_20261018
set_param general.maxThreads 1
open_project $OUT/project/tt_gcs_keys.xpr
set f [open $OUT/low_memory.tcl w];puts $f {set_param general.maxThreads 1};close $f
foreach run [get_runs -filter {IS_SYNTHESIS == 1}] {
 set_property STEPS.SYNTH_DESIGN.TCL.PRE $OUT/low_memory.tcl $run
 puts "KEYS_RUN [get_property NAME $run] [get_property STATUS $run]"
 if {[get_property PROGRESS $run] ne "100%"} {reset_run $run}
}
reset_run impl_1
foreach step {OPT_DESIGN PLACE_DESIGN PHYS_OPT_DESIGN ROUTE_DESIGN WRITE_BITSTREAM} {
 set_property STEPS.${step}.TCL.PRE $OUT/low_memory.tcl [get_runs impl_1]
}
launch_runs impl_1 -to_step write_bitstream -jobs 1
wait_on_run impl_1
if {[get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {error "Implementation incomplete"}
open_run impl_1
report_timing_summary -report_unconstrained -file $OUT/timing.rpt
report_utilization -file $OUT/utilization.rpt
report_drc -file $OUT/drc.rpt
set wns [get_property STATS.WNS [get_runs impl_1]]
set whs [get_property STATS.WHS [get_runs impl_1]]
if {$wns eq "" || $whs eq "" || $wns<0 || $whs<0} {error "Timing failed; no export"}
if {[llength [get_drc_violations -filter {SEVERITY == Error}]]} {error "DRC errors"}
write_hw_platform -fixed -include_bit -file $OUT/tt_gcs_keys.xsa
set f [open $OUT/result.json w]
puts $f [format {{"result":"PASS","part":"%s","wns":%s,"whs":%s,"key5":"MIO26","key6":"AF12 to EMIO0 (GPIO78)","engine_abi":4}} [get_property PART [current_project]] $wns $whs]
close $f
puts "KEYS_HARDWARE_PASS $OUT"
exit
