# 在 tools/build_periph_platform.tcl 生成的 periph_plat 上建 A53 裸机应用，编 C3 外设测试程序（src/ps/periph），产出 ELF。
# 走 Vitis IDE 同一套 app / lscript / Makefile 流程；用户在 Vitis IDE 里建应用时用同一组源码与选项（board/CHECKLIST.md C3 节）。
# 用法：xsct D:/HSI_AgriEdge/tools/build_periph_app.tcl [ws]
#   ws 默认 build/board/periph_ws。产物 <ws>/periph_zu5ev/Release/periph_zu5ev.elf，不自动覆盖 board/periph/。
# 编译选项：-O2、-mcpu=cortex-a53、-Wall（模板自带）-Wextra -Werror；BSP 库告警在平台阶段单独记录。
# xsct.bat 的退出码恒为 0，调用方以输出里的 "BUILD PASS" 为准。
set ROOT [file normalize [file dirname [info script]]/..]
set ws [expr {[llength $argv] > 0 ? [file normalize [lindex $argv 0]] : "$ROOT/build/board/periph_ws"}]
set app periph_zu5ev
if {![file isdirectory $ws/periph_plat]} { error "platform periph_plat not found in $ws; run tools/build_periph_platform.tcl first" }
setws $ws
set stage $ws/${app}_src
file delete -force $stage
file mkdir $stage
foreach f [glob $ROOT/src/ps/periph/*.cpp $ROOT/src/ps/periph/*.h] { file copy -force $f $stage/ }
if {[file isdirectory $ws/$app]} { app remove $app }
puts "BUILD: creating app $app on periph_plat"
app create -name $app -platform periph_plat -domain standalone_domain -template {Empty Application (C++)} -lang c++
importsources -name $app -path $stage
app config -name $app build-config release
app config -name $app -set compiler-optimization {Optimize more (-O2)}
app config -name $app -add compiler-misc {-mcpu=cortex-a53 -Wextra -Werror}
puts "BUILD: compiling through XSCT"
app build -name $app
# Vitis 2020.2 app build returns nothing. Capture a full rebuild of its generated Makefile.
set make $::env(XILINX_VITIS)/gnuwin/bin/make.exe
puts "BUILD: verifying generated Release Makefile (-B all)"
set failed [catch {exec $make -C $ws/$app/Release -B all 2>@1} buildlog]
set logpath $ws/$app/application_build.log
set logfile [open $logpath w]
fconfigure $logfile -encoding utf-8 -translation lf
puts $logfile $buildlog
close $logfile
puts $buildlog
if {$failed} { error "BUILD FAIL: generated Makefile rebuild failed; see $logpath" }
set nwarn [regexp -all -nocase {warning:} $buildlog]
set elf [glob -nocomplain $ws/$app/Release/*.elf]
if {[llength $elf] != 1} { error "BUILD FAIL: no ELF produced, see compiler output above" }
if {$nwarn > 0} { error "BUILD FAIL: $nwarn warning(s) in application sources, see $logpath" }
puts "BUILD PASS: 0 application warnings, [lindex $elf 0]; log $logpath"
