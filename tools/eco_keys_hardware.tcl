# Minimal physical ECO: verified routed full system + one KEY6 input and 2 FFs.
# GPIO EMIO bank registers exist in PS regardless of BD port-export settings.
# No PS configuration or driver ABI change is needed for input-only GPIO78.
set ROOT [file normalize [file dirname [info script]]/..]
set LEGACY [file normalize $ROOT/../HSI_AgriEdge(1)/HSI_AgriEdge]
set OUT $ROOT/build/keys_eco_20261018_v4
if {[file exists $OUT]} {error "Retain previous candidate, choose new output"}
file mkdir $OUT
set_param general.maxThreads 1
open_checkpoint -part xczu5ev-sfvc784-2-i $LEGACY/build/vivado/tt_gcs_r1_abi4_zu5ev/tt_gcs_r1_abi4_zu5ev.runs/impl_1/design_1_wrapper_routed.dcp
set ps [get_cells -hier -filter {REF_NAME == PS8}]
if {[llength $ps]!=1} {error "Expected exactly one PS8"}
set gpio [get_pins ${ps}/EMIOGPIOI\[0\]]
if {[llength $gpio]!=1} {error "Missing EMIO0 PS hard-block input"}
set oldnet [get_nets -of_objects $gpio]
set driver [get_pins -of_objects $oldnet -filter {DIRECTION == OUT}]
if {[llength $driver]!=1 || [get_property REF_NAME [get_cells -of_objects $driver]] ne "GND"} {error "EMIO0 is not an unused tied-low input"}
set clk {}
foreach cell [get_cells -hier -filter {REF_NAME == FDRE}] {
 set pin [get_pins $cell/C]
 if {[lsearch -exact [get_clocks -of_objects $pin] clk_pl_0]>=0} {set clk [get_nets -of_objects $pin];break}
}
if {[llength $clk]!=1} {error "Cannot identify verified PL0 clock net"}
report_route_status -file $OUT/before_route.rpt
# Keep original placements and preserve routed nets. Do not lock the logical
# clock/GND networks, which must accept a new GPIO input and two clock loads.
set fixed [get_cells -hier -filter {IS_PRIMITIVE == 1 && LOC != ""}]
set_property IS_LOC_FIXED true $fixed
create_port -direction IN key6_n
set_property PACKAGE_PIN AF12 [get_ports key6_n]
set_property IOSTANDARD LVCMOS33 [get_ports key6_n]
create_cell -reference IBUF key6_ibuf
create_cell -reference FDRE key6_meta
create_cell -reference FDRE key6_sync
create_cell -reference VCC key6_vcc
create_cell -reference GND key6_gnd
foreach reg {key6_meta key6_sync} {
 set_property INIT 1'b1 [get_cells $reg]
 set_property ASYNC_REG TRUE [get_cells $reg]
 set_property DONT_TOUCH TRUE [get_cells $reg]
 connect_net -hier -net $clk -objects [get_pins $reg/C]
}
foreach {name pins} {
 key6_pad {key6_ibuf/I}
 key6_input {key6_ibuf/O key6_meta/D}
 key6_meta_q {key6_meta/Q key6_sync/D}
 key6_sync_q {key6_sync/Q}
 key6_one {key6_vcc/P key6_meta/CE key6_sync/CE}
 key6_zero {key6_gnd/G key6_meta/R key6_sync/R}
} {create_net $name;connect_net -hier -net [get_nets $name] -objects [get_pins $pins]}
connect_net -hier -net [get_nets key6_pad] -objects [get_ports key6_n]
disconnect_net -net $oldnet -objects $gpio
connect_net -hier -net [get_nets key6_sync_q] -objects $gpio
set_false_path -from [get_ports key6_n] -to [get_pins key6_meta/D]
# PS GPIO has no fabric timing endpoint; the PL synchronizer path remains timed.
write_checkpoint $OUT/keys_added.dcp
place_design -directive Quick
route_design -preserve
report_timing_summary -report_unconstrained -file $OUT/timing.rpt
report_utilization -file $OUT/utilization.rpt
report_route_status -file $OUT/route.rpt
report_drc -file $OUT/drc.rpt
if {[llength [get_drc_violations -filter {SEVERITY == Error}]]} {error "DRC failure"}
set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
if {$wns<0 || $whs<0} {error "Timing failure: setup=$wns hold=$whs"}
write_checkpoint $OUT/keys_routed.dcp
write_bitstream $OUT/tt_gcs_keys.bit
set f [open $OUT/result.json w]
puts $f [format {{"result":"PASS","wns":%s,"whs":%s,"key5":"MIO26","key6":"AF12 -> IBUF -> 2FF -> PS EMIOGPIOI0 (GPIO78)","key7":"unchanged hardware reset","method":"incremental physical ECO; original primitive placement fixed, routed nets preserved","part":"xczu5ev-sfvc784-2-i","ps_configuration":"unchanged"}} $wns $whs]
close $f
puts "KEYS_ECO_HARDWARE_PASS $OUT"
exit
