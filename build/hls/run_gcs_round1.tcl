# Separate serial K7/DB18 release candidate. No overlap/old P2 optimization.
set ROOT [file normalize [file dirname [info script]]/../..]
set NAME tt_engine_gcs_r1_abi4
set ORIGINAL $ROOT/build/hls/optimization_build/$NAME
set BUILD $ORIGINAL
set SNAP $ORIGINAL/snapshot
set stage $::env(GCS_HLS_STAGE)
if {$stage ni {synth cosim export}} {error "GCS_HLS_STAGE=synth|cosim|export required"}
if {$stage eq "export"} {
    set BUILD $ROOT/build/hls/optimization_build/tt_engine_gcs_r1_abi4_export
    if {![file exists $BUILD/export_clone.json]} {error "Export requires the new checked clone; never overwrite completed cosim"}
}
set flags "-DTT_K3=7 -DTT_DB=18 -DTT_M3_OVERLAP=0"
set ::env(TT_TB_LAYERS) 12
if {$stage eq "synth"} {
    if {[file exists $BUILD]} {error "Refusing existing candidate $BUILD"}
    file mkdir $SNAP/src/hls $SNAP/src/ps $SNAP/sim/hls_tb $SNAP/sim/golden
    foreach f {tt_engine.cpp tt_engine.h tt_engine_regs.h tt_types.h tt_attn.cpp tt_attn.h} {
        file copy $ROOT/src/hls/$f $SNAP/src/hls
    }
    file copy $ROOT/src/ps/tt_ref_int.h $SNAP/src/ps
    foreach f {tb_tt_engine_full.cpp tb_tt_engine_attention.cpp} {file copy $ROOT/sim/hls_tb/$f $SNAP/sim/hls_tb}
    file copy $ROOT/sim/golden/n6_engine $SNAP/sim/golden
    set f [open $SNAP/flags.txt w];puts $f "name=$NAME\nflags=$flags\npart=xazu5ev-sfvc784-1-i\nclock_ns=5\nabi=4";close $f
} elseif {![file exists $BUILD/synth.done]} {error "Synthesis prerequisite missing"}
if {$stage eq "export" && ![file exists $BUILD/cosim.done]} {error "Full RTL cosim required before export"}
if {[file exists $BUILD/${stage}.done]} {error "Stage already complete"}
cd [file dirname $BUILD]
open_project [file tail $BUILD]
set_top tt_engine
foreach f {tt_engine.cpp tt_attn.cpp} {add_files $SNAP/src/hls/$f -cflags $flags}
add_files -tb $SNAP/sim/hls_tb/tb_tt_engine_attention.cpp -cflags $flags
open_solution sol -flow_target vivado
set_part xazu5ev-sfvc784-1-i
create_clock -period 5 -name default
config_interface -m_axi_addr64=false -s_axilite_data64=false
if {$stage eq "synth"} {csim_design -clean;csynth_design}
if {$stage eq "cosim"} {cosim_design -rtl verilog -trace_level none}
if {$stage eq "export"} {export_design -rtl verilog -format ip_catalog -vendor tt_hsi -version 4.0 -display_name "GCS first round serial ABI4" -description "Serial K7 DB18 overlap=0; real attention and cycles ABI4"}
set f [open $BUILD/${stage}.done w];puts $f "GCS_HLS_PASS stage=$stage name=$NAME";close $f
puts "GCS_HLS_PASS stage=$stage name=$NAME"
exit
