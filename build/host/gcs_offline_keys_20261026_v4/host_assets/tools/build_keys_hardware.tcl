# New, isolated hardware: retain ABI4 serial inference RTL; add KEY6 -> EMIO0.
set ROOT [file normalize [file dirname [info script]]/..]
set OUT $ROOT/build/keys_20261018
if {[file exists $OUT]} {error "Choose a new output directory; existing build retained: $OUT"}
file mkdir $OUT
set LEGACY [file normalize $ROOT/../HSI_AgriEdge(1)/HSI_AgriEdge]
set IPREPO $OUT/tt_engine_ip
file copy $LEGACY/build/hls/optimization_build/tt_engine_gcs_r1_abi4_ip $IPREPO
set PART xazu5ev-sfvc784-1-i
if {![llength [get_parts -quiet $PART]]} {set PART xczu5ev-sfvc784-2-i}
if {![llength [get_parts -quiet $PART]]} {error "ZU5EV SFVC784 part unavailable"}
create_project tt_gcs_keys $OUT/project -part $PART
set_property ip_repo_paths $IPREPO [current_project]
update_ip_catalog
add_files -norecurse $ROOT/src/rtl/tt_key_sync.v
create_bd_design design_1
set psdef [lindex [get_ipdefs -all -filter {VLNV =~ xilinx.com:ip:zynq_ultra_ps_e:*}] end]
set zynq_ultra_ps_e_0 [create_bd_cell -type ip -vlnv [get_property VLNV $psdef] zynq_ultra_ps_e_0]
set f [open $LEGACY/build/vivado/psu_cfg_factory.tcl];set text [read $f];close $f
set start [string first {set_property -dict} $text]
set config_script [string range $text $start end]
# Vendor board configuration, with each property checked against this tool.
proc apply_factory {args} {
    set target [lindex $args end]
    set supported [list_property $target]
    set props [lindex $args 1]
    set filtered {}
    foreach {name value} $props {
        if {[lsearch -exact $supported $name]>=0} {lappend filtered $name $value} else {puts "KEYS_FACTORY_OBSOLETE $name"}
    }
    set_property -dict $filtered $target
}
eval [string map {{set_property -dict} {apply_factory -dict}} $config_script]
set_property -dict [list CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ {200} \
 CONFIG.PSU__SAXIGP2__DATA_WIDTH {64} CONFIG.PSU__SAXIGP3__DATA_WIDTH {64} \
 CONFIG.PSU__GPIO_EMIO__PERIPHERAL__ENABLE {1} CONFIG.PSU__GPIO_EMIO__PERIPHERAL__IO {1} \
 CONFIG.PSU__UART1__PERIPHERAL__ENABLE {0}] $zynq_ultra_ps_e_0
set fan_const [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 fan_const]
set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {1}] $fan_const
connect_bd_net [get_bd_pins fan_const/dout] [create_bd_port -dir O -from 0 -to 0 fan]
create_bd_cell -type module -reference tt_key_sync key6_sync
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] [get_bd_pins key6_sync/clk]
connect_bd_net [create_bd_port -dir I key6_n] [get_bd_pins key6_sync/key_n]
connect_bd_net [get_bd_pins key6_sync/stable_n] [get_bd_pins zynq_ultra_ps_e_0/emio_gpio_i]
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
if {[get_property OFFSET $seg]!=0x80000000} {error "Inference control ABI address changed"}
validate_bd_design
save_bd_design
add_files -norecurse [make_wrapper -files [get_files design_1.bd] -top]
set_property top design_1_wrapper [current_fileset]
set f [open $OUT/keys.xdc w]
puts $f {set_property PACKAGE_PIN AA11 [get_ports {fan[0]}]}
puts $f {set_property IOSTANDARD LVCMOS33 [get_ports {fan[0]}]}
puts $f {set_property PACKAGE_PIN AF12 [get_ports key6_n]}
puts $f {set_property IOSTANDARD LVCMOS33 [get_ports key6_n]}
puts $f {set_false_path -from [get_ports key6_n] -to [get_pins -hier -filter {NAME =~ */key6_sync/inst/meta_reg/D}]}
close $f
add_files -fileset constrs_1 -norecurse $OUT/keys.xdc
update_compile_order -fileset sources_1
launch_runs impl_1 -to_step write_bitstream -jobs 6
wait_on_run impl_1
if {[get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {error "Implementation incomplete"}
open_run impl_1
report_timing_summary -report_unconstrained -file $OUT/timing.rpt
report_utilization -file $OUT/utilization.rpt
report_drc -file $OUT/drc.rpt
set wns [get_property STATS.WNS [get_runs impl_1]]
set whs [get_property STATS.WHS [get_runs impl_1]]
if {$wns eq "" || $whs eq "" || $wns<0 || $whs<0} {error "Timing failure, retain candidate without export"}
if {[llength [get_drc_violations -filter {SEVERITY == Error}]]} {error "DRC failure"}
write_hw_platform -fixed -include_bit -file $OUT/tt_gcs_keys.xsa
set f [open $OUT/result.json w]
puts $f [format {{"result":"PASS","part":"%s","wns":%s,"whs":%s,"key5":"MIO26","key6":"AF12 to EMIO0 (GPIO78)","engine_abi":4}} $PART $wns $whs]
close $f
puts "KEYS_HARDWARE_PASS $OUT"
exit
