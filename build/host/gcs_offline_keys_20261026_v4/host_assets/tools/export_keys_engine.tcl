# Read the verified serial engine checkpoint; do not re-synthesize old floating IP.
set ROOT [file normalize [file dirname [info script]]/..]
set LEGACY [file normalize $ROOT/../HSI_AgriEdge(1)/HSI_AgriEdge]
set OUT $ROOT/build/keys_20261018
set_param general.maxThreads 1
open_checkpoint -part xczu5ev-sfvc784-2-i $LEGACY/build/vivado/tt_gcs_r1_abi4_zu5ev/tt_gcs_r1_abi4_zu5ev.runs/design_1_tt_engine_0_0_synth_1/design_1_tt_engine_0_0.dcp
write_checkpoint $OUT/verified_engine.dcp
write_verilog -mode synth_stub $OUT/verified_engine_stub.v
report_utilization -file $OUT/verified_engine_utilization.rpt
puts "KEYS_ENGINE_NETLIST_EXPORTED"
exit
