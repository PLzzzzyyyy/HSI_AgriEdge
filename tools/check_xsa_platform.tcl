# 用命令行 XSCT 拿候选 XSA 建一个临时平台并 generate（走和 Vitis IDE 相同的 BSP/驱动 Makefile 流程），
# 验证 XSA 能被接受、HLS 驱动 Makefile 在 Windows make 下能过。不碰用户的 Vitis 工程。
# 用法：xsct D:/HSI_AgriEdge/tools/check_xsa_platform.tcl <xsa> <out_dir> [proc] [driver]
#   proc 默认 psu_cortexa53_0（ZU5EV）；7020 用 ps7_cortexa9_0
#   driver 默认 tucker_proj（v1.4，头文件 xtucker_proj*.h）；M2 用 tt_engine
set xsa [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
set proc [expr {[llength $argv] > 2 ? [lindex $argv 2] : "psu_cortexa53_0"}]
set drv [expr {[llength $argv] > 3 ? [lindex $argv 3] : "tucker_proj"}]
if {![file exists $xsa]} { error "XSA not found: $xsa" }
file delete -force $out
file mkdir $out
setws $out
puts "CHECK: creating platform from $xsa (proc $proc)"
platform create -name chk_plat -hw $xsa -proc $proc -os standalone -out $out
platform write
puts "CHECK: generating platform (BSP + drivers)"
platform generate
set inc [glob -nocomplain $out/chk_plat/export/chk_plat/sw/chk_plat/standalone_domain/bspinclude/include/x${drv}*.h]
set lib [glob -nocomplain $out/chk_plat/export/chk_plat/sw/chk_plat/standalone_domain/bsplib/lib/libxil.a]
puts "CHECK: driver headers = $inc"
puts "CHECK: libxil = $lib"
if {[llength $inc] < 2 || [llength $lib] != 1} { error "platform generated but $drv driver/libxil missing" }
puts "CHECK PASS: platform generated with $drv driver"
