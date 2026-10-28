# Read-only analysis of the checkpoint that produced the deployed KEY bitstream.
# No implementation, bitstream generation, device access or configuration writes.
set ROOT [file normalize [file dirname [info script]]/..]
set OUT $ROOT/report/chip_power_20261021
file mkdir $OUT
set_param general.maxThreads 2
open_checkpoint $ROOT/build/keys_eco_20261018_v4/keys_routed.dcp
foreach temperature {-40 0 25 40 55 70 85 100 125} {
    set_operating_conditions -junction_temp $temperature
    report_power -file $OUT/junction_${temperature}.rpt
}
close_design
exit
