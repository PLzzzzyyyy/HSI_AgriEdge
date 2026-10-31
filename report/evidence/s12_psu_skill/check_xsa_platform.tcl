# 用命令行 XSCT 拿 XSA 建一个临时裸机平台并 generate（走和 Vitis IDE 相同的 BSP / 驱动 Makefile 流程），
# 确认 XSA 能被接受、BSP 与自定义 IP 驱动能编过。不碰用户的 Vitis 工程。
# 用法：xsct check_xsa_platform.tcl <xsa> <out_dir> [proc] [驱动头文件 glob ...]
#   proc 默认 psu_cortexa53_0（ZU+）；Zynq-7000 用 ps7_cortexa9_0
#   驱动头文件 glob 例：xtucker_proj*.h；每个 glob 至少匹配到一个文件才算 PASS
# 判定只看输出里有没有 "CHECK PASS" 行：xsct.bat 在 platform generate 失败或脚本 error 时退出码仍是 0。
set xsa [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
set proc [expr {[llength $argv] > 2 ? [lindex $argv 2] : "psu_cortexa53_0"}]
set drivers [lrange $argv 3 end]
if {![file exists $xsa]} { error "XSA not found: $xsa" }
file delete -force $out
file mkdir $out
setws $out
puts "CHECK: creating platform from $xsa (proc $proc)"
platform create -name chk_plat -hw $xsa -proc $proc -os standalone -out $out
platform write
puts "CHECK: generating platform (BSP + drivers)"
platform generate
set dom [glob -nocomplain -type d $out/chk_plat/export/chk_plat/sw/chk_plat/*]
set lib [glob -nocomplain $out/chk_plat/export/chk_plat/sw/chk_plat/*/bsplib/lib/libxil.a]
puts "CHECK: libxil = $lib"
if {[llength $lib] != 1} { error "CHECK FAIL: libxil.a not built (domains: $dom)" }
foreach pat $drivers {
    set hit [glob -nocomplain $out/chk_plat/export/chk_plat/sw/chk_plat/*/bspinclude/include/$pat]
    puts "CHECK: $pat = $hit"
    if {[llength $hit] == 0} { error "CHECK FAIL: no driver header matching $pat" }
}
puts "CHECK PASS: platform generated ([llength $drivers] driver pattern(s) found)"
