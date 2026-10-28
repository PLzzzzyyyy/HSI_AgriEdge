# Integrate the verified engine netlist instead of regenerating its old
# encrypted floating-point IP with a different vendor version.
set ROOT [file normalize [file dirname [info script]]/..]
set OUT $ROOT/build/keys_20261018
set_param general.maxThreads 1
open_project $OUT/project/tt_gcs_keys.xpr
set xci [get_files -all -filter {NAME =~ */design_1_tt_engine_0_0.xci}]
if {[llength $xci]!=1} {error "Expected one engine XCI, got $xci"}
set_property USED_IN_SYNTHESIS false $xci
set_property USED_IN_IMPLEMENTATION false $xci
add_files -norecurse $OUT/verified_engine_stub.v
set_property USED_IN {synthesis} [get_files $OUT/verified_engine_stub.v]
set_property FILE_TYPE Verilog [get_files $OUT/verified_engine_stub.v]
set_property LIBRARY xil_defaultlib [get_files $OUT/verified_engine_stub.v]
set_property GENERATE_SYNTH_CHECKPOINT false [get_files design_1.bd]
update_compile_order -fileset sources_1
reset_run synth_1
set f [open $OUT/link_pre.tcl w]
puts $f {set_param general.maxThreads 1}
puts $f [list read_verilog -library xil_defaultlib $OUT/verified_engine_stub.v]
close $f
set_property STEPS.SYNTH_DESIGN.TCL.PRE $OUT/link_pre.tcl [get_runs synth_1]
launch_runs synth_1 -jobs 1
wait_on_run synth_1
open_run synth_1
set cells [get_cells -hier -filter {REF_NAME == design_1_tt_engine_0_0 && IS_BLACKBOX == 1}]
if {[llength $cells]!=1} {error "Engine must be exactly one black box before verified netlist import: $cells"}
read_checkpoint -cell $cells $OUT/verified_engine.dcp
if {[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]} {error "Unresolved black boxes after engine import"}
write_checkpoint $OUT/keys_linked.dcp
opt_design
place_design
phys_opt_design
route_design
report_timing_summary -report_unconstrained -file $OUT/timing.rpt
report_utilization -file $OUT/utilization.rpt
report_drc -file $OUT/drc.rpt
report_route_status -file $OUT/route.rpt
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
set wns [get_property SLACK $setup];set whs [get_property SLACK $hold]
if {$wns<0 || $whs<0} {error "Timing failed: setup=$wns hold=$whs"}
if {[llength [get_drc_violations -filter {SEVERITY == Error}]]} {error "DRC failure"}
write_checkpoint $OUT/keys_routed.dcp
write_bitstream $OUT/tt_gcs_keys.bit
write_hw_platform -fixed -include_bit -file $OUT/tt_gcs_keys.xsa
set f [open $OUT/result.json w]
puts $f [format {{"result":"PASS","part":"%s","wns":%s,"whs":%s,"key5":"MIO26","key6":"AF12 to EMIO0 (GPIO78)","engine_abi":4,"engine_source":"verified 2020.2 OOC checkpoint; retargeted netlist, no algorithm change"}} [get_property PART [current_project]] $wns $whs]
close $f
puts "KEYS_HARDWARE_PASS $OUT"
exit
