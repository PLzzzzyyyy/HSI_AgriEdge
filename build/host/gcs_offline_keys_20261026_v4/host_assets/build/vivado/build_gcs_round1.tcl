# Isolated full PS/PL system for first-round ABI4 functionality/measurement.
# Not overlap/P2 optimization. No user workspace, Vitis Build or devices.
set ROOT [file normalize [file dirname [info script]]/../..]
set PROJ tt_gcs_r1_abi4_zu5ev
set PART xazu5ev-sfvc784-1-i
set IPREPO $ROOT/build/hls/optimization_build/tt_engine_gcs_r1_abi4_ip
set PREFIX $ROOT/build/vivado/impl_gcs_r1_abi4
set XSA $ROOT/build/vivado/$PROJ.xsa
foreach p [list $ROOT/build/vivado/$PROJ $XSA ${PREFIX}_gate.json] {
    if {[file exists $p]} {error "Refusing existing full-system output $p"}
}
set saved {}
foreach v {PYTHONPATH PYTHONHOME} {if {[info exists ::env($v)]} {lappend saved $v $::env($v);unset ::env($v)}}
set failed [catch {exec D:/pytorch/python.exe -B $ROOT/tools/check_gcs_hardware.py --stage ip} msg]
foreach {v val} $saved {set ::env($v) $val}
if {$failed} {error "IP gate failed: $msg"}
puts $msg
create_project $PROJ $ROOT/build/vivado/$PROJ -part $PART
set_property ip_repo_paths $IPREPO [current_project]
update_ip_catalog
create_bd_design design_1
source $ROOT/build/vivado/psu_cfg_factory.tcl
set_property -dict [list CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ {200} \
    CONFIG.PSU__SAXIGP2__DATA_WIDTH {64} CONFIG.PSU__SAXIGP3__DATA_WIDTH {64} \
    CONFIG.PSU__GPIO_EMIO__PERIPHERAL__ENABLE {0} CONFIG.PSU__UART1__PERIPHERAL__ENABLE {0}] $zynq_ultra_ps_e_0
set ref [get_property CONFIG.PSU__PSS_REF_CLK__FREQMHZ $zynq_ultra_ps_e_0]
set actual [get_property CONFIG.PSU__CRL_APB__PL0_REF_CTRL__ACT_FREQMHZ $zynq_ultra_ps_e_0]
if {$ref != 33.333 || $actual != 199.998001} {error "PS clock configuration differs: ref=$ref actual=$actual"}
set fan_const [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 fan_const]
set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {1}] $fan_const
set fan [create_bd_port -dir O -from 0 -to 0 fan]
connect_bd_net [get_bd_pins fan_const/dout] $fan
create_bd_cell -type ip -vlnv tt_hsi:hls:tt_engine:4.0 tt_engine_0
set clk "/zynq_ultra_ps_e_0/pl_clk0 (200 MHz)"
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config [list Clk_master $clk Clk_slave {Auto} Clk_xbar {Auto} \
    Master {/zynq_ultra_ps_e_0/M_AXI_HPM0_LPD} Slave {/tt_engine_0/s_axi_CTRL} ddr_seg {Auto} intc_ip {New AXI Interconnect} master_apm {0}] [get_bd_intf_pins tt_engine_0/s_axi_CTRL]
foreach {port hp} {FM 0 WT 1} {
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config [list Clk_master {Auto} Clk_slave $clk Clk_xbar {Auto} \
        Master "/tt_engine_0/m_axi_$port" Slave "/zynq_ultra_ps_e_0/S_AXI_HP${hp}_FPD" ddr_seg {Auto} intc_ip {New AXI Interconnect} master_apm {0}] [get_bd_intf_pins zynq_ultra_ps_e_0/S_AXI_HP${hp}_FPD]
}
assign_bd_address
set seg [get_bd_addr_segs zynq_ultra_ps_e_0/Data/SEG_tt_engine_0_Reg]
if {[llength $seg]!=1 || [get_property OFFSET $seg]!=0x80000000} {error "CTRL register base differs from existing driver contract"}
validate_bd_design
save_bd_design
set wrappers [make_wrapper -files [get_files design_1.bd] -top]
if {[llength $wrappers]!=1} {error "Expected one generated system wrapper"}
add_files -norecurse $wrappers
set_property top design_1_wrapper [current_fileset]
add_files -fileset constrs_1 -norecurse $ROOT/build/vivado/zu5ev_pins.xdc
update_compile_order -fileset sources_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
if {[get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {error "Full-system implementation not complete"}
open_run impl_1
report_utilization -file ${PREFIX}_utilization.rpt
report_timing_summary -report_unconstrained -file ${PREFIX}_timing.rpt
report_route_status -file ${PREFIX}_route_status.rpt
report_drc -file ${PREFIX}_drc.rpt
report_clocks -file ${PREFIX}_clocks.rpt
check_timing -verbose -file ${PREFIX}_check_timing.rpt
set wns [get_property STATS.WNS [get_runs impl_1]]
set whs [get_property STATS.WHS [get_runs impl_1]]
if {$wns eq "" || $whs eq "" || $wns<0 || $whs<0} {error "Setup/hold timing failure; no XSA export"}
if {[llength [get_drc_violations -filter {SEVERITY == Error}]]} {error "Unresolved DRC errors; no XSA export"}
write_hw_platform -fixed -include_bit -file $XSA
set f [open ${PREFIX}_gate.json w]
puts $f [format {{"result":"PASS","wns":%s,"whs":%s,"ctrl_base":"0x80000000","ref_mhz":%s,"pl_actual_mhz":%s,"part":"xazu5ev-sfvc784-1-i","tool":"Vivado 2020.2"}} $wns $whs $ref $actual]
close $f
set saved {}
foreach v {PYTHONPATH PYTHONHOME} {if {[info exists ::env($v)]} {lappend saved $v $::env($v);unset ::env($v)}}
if {[catch {exec D:/pytorch/python.exe -B $ROOT/tools/fix_xsa_driver_makefile.py $XSA} msg]} {error "XSA driver Makefile preparation failed: $msg"}
foreach {v val} $saved {set ::env($v) $val}
puts $msg
puts "GCS_SYSTEM_PASS XSA=$XSA WNS=$wns WHS=$whs"
exit
