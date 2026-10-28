# Independent successor. The deployed ABI4 hardware and old P2 evidence are read-only.
set ROOT [file normalize [file dirname [info script]]]
set BUILD $ROOT/hls_2026_xc
if {[file exists $BUILD]} {error "Preserve prior HLS run; use a new candidate"}
set flags "-std=c++14 -ffp-contract=off -I$ROOT/src/hls/m3_s2 -DS2_NATIVE=0 -DS2_NUM=8 -DS2_P=2 -DS2_PACK=1"
open_project $BUILD
set_top s2_engine
foreach f {s2_engine.cpp s2_projection.cpp s2_exp.cpp} {add_files $ROOT/src/hls/m3_s2/$f -cflags $flags}
add_files $ROOT/src/hls/m3_math/s2_math.cpp -cflags $flags
add_files -tb $ROOT/sim/hls_tb/tb_m3_s2.cpp -cflags $flags
open_solution sol -flow_target vivado
set_part xczu5ev-sfvc784-2-i
create_clock -period 5 -name default
set_clock_uncertainty 1.35
csynth_design
set f [open $ROOT/hls_tool_completed.txt w]
puts $f "Tool stages completed; resource/II/timing gates require separate assessment. Not board performance."
close $f
exit

