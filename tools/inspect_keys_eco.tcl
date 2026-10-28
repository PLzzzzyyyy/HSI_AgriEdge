set ROOT [file normalize [file dirname [info script]]/..]
set LEGACY [file normalize $ROOT/../HSI_AgriEdge(1)/HSI_AgriEdge]
set_param general.maxThreads 1
open_checkpoint -part xczu5ev-sfvc784-2-i $LEGACY/build/vivado/tt_gcs_r1_abi4_zu5ev/tt_gcs_r1_abi4_zu5ev.runs/impl_1/design_1_wrapper_routed.dcp
set ps [get_cells -hier -filter {REF_NAME == PS8}]
puts "KEYS_ECO_PS $ps"
puts "KEYS_ECO_PINS [get_pins -of_objects $ps -filter {REF_PIN_NAME =~ *GPIO*I*}]"
puts "KEYS_ECO_CLK [get_pins -of_objects $ps -filter {REF_PIN_NAME =~ *PLCLK*}]"
puts "KEYS_ECO_CLOCKS [get_clocks]"
puts "KEYS_ECO_DONE"
exit
