# 用 XSCT 在 tools/check_xsa_platform.tcl 生成的平台（<ws>/chk_plat，psu_cortexa53_0 standalone）上建 A53 裸机应用，
# 编译串口基准程序（src/ps，模式 1/2/3/5），产出 ELF。走的是 Vitis IDE 同一套 app/lscript/Makefile 流程，
# 板子没到之前用它把接口错误提前抓出来；用户在 Vitis IDE 里建应用时用同一组源码与编译选项。
# 用法：xsct D:/HSI_AgriEdge/tools/build_zu5ev_app.tcl <ws> [app_name] [variant]
#   ws：check_xsa_platform.tcl 的 out_dir（内含 chk_plat）。产物：<ws>/<app>/Release/<app>.elf，复制到 board/<m1|m2>/。
#   variant：m1（默认，PL 后端 tt_hw_xil.cpp，v1.4）；m2（PL 后端 tt_hw_engine.cpp + src/hls/tt_engine_regs.h，tt_engine PROJ 模式）；
#            m2chk（m2 + -DTT_ENG_SELFCHECK：每次投影后用纯 PS 逐位重算比对，只作板上逐层检查，计时无意义）
# 编译选项：-O2、-mcpu=cortex-a53、-ffp-contract=off（float32 内核保持乘加两次舍入，与主机 sim/golden 一致）、
#   -DTT_HW_RUNTIME_SWITCH（串口 1/2/3 运行时切 PL / 纯 PS）、链接 libm。
set ROOT [file normalize [file dirname [info script]]/..]
set ws [file normalize [lindex $argv 0]]
set app [expr {[llength $argv] > 1 ? [lindex $argv 1] : "tt_bench_zu5ev"}]
set variant [expr {[llength $argv] > 2 ? [lindex $argv 2] : "m1"}]
if {$variant ni {m1 m2 m2chk}} { error "variant must be m1, m2 or m2chk" }
if {![file isdirectory $ws/chk_plat]} { error "platform chk_plat not found in $ws; run tools/check_xsa_platform.tcl first" }
setws $ws

# 只带板上需要的源码：不含 src/ps/reference/（lwIP、QSPI 参考件）与主机 stub
set srcs {main_benchmark.cpp tt_net.cpp tt_net.h tt_hw.h tt_hw_sim.cpp tt_hw_xil.cpp tt_hw_switch.cpp tt_hw_switch.h
          tt_ref_int.h tt_data.c tt_data.h tt_block_app.cpp tt_block_app.h tt_block_data.c tt_block_data.h
          tt_block_render.cpp tt_block_render.h}
set stage $ws/${app}_src
file delete -force $stage
file mkdir $stage
if {$variant ne "m1"} {
    set srcs [lsearch -all -inline -not -exact $srcs tt_hw_xil.cpp]
    lappend srcs tt_hw_engine.cpp tt_hw_engine.h
}
foreach f $srcs { file copy -force $ROOT/src/ps/$f $stage/$f }
if {$variant ne "m1"} { file copy -force $ROOT/src/hls/tt_engine_regs.h $stage/tt_engine_regs.h }

if {[file isdirectory $ws/$app]} { app remove $app }
puts "BUILD: creating app $app on chk_plat"
app create -name $app -platform chk_plat -domain standalone_domain -template {Empty Application (C++)} -lang c++
importsources -name $app -path $stage
app config -name $app build-config release
app config -name $app -set compiler-optimization {Optimize more (-O2)}
app config -name $app -add define-compiler-symbols TT_HW_RUNTIME_SWITCH
if {$variant eq "m2chk"} { app config -name $app -add define-compiler-symbols TT_ENG_SELFCHECK }
app config -name $app -add compiler-misc {-mcpu=cortex-a53 -ffp-contract=off}
app config -name $app -add libraries m
puts "BUILD: compiling"
set buildlog [app build -name $app]
puts $buildlog
set elf [glob -nocomplain $ws/$app/Release/*.elf]
if {[llength $elf] != 1} { error "BUILD FAIL: no ELF produced, see compiler output above" }
set bdir $ROOT/board/[expr {$variant eq "m1" ? "m1" : "m2"}]
file mkdir $bdir
file copy -force $elf $bdir/
puts "BUILD PASS: $elf -> $bdir/"
