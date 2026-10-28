# 用命令行 XSCT 从 build/vivado/tt_zu5ev.xsa 建 C3 外设测试平台（psu_cortexa53_0 standalone），在 BSP 上加：
#   xilffs（SD1 = 盘符 1:，长文件名 use_lfn 1）、lwip211（RAW API，静态 IP，链路定死 1000 Mbps，收发描述符与 pbuf 加大）、
#   psu_dp 的驱动从默认的 avbuf 换成 dppsu（DP 例程要 xdppsu.h，avbuf 与 video_common 作为依赖自动带上）。
# 链路定死 1000 Mbps 的原因：板上 PHY 是 KSZ9031（ID 0x0022），2020.2 的 lwip211 只认 Marvell / TI / Realtek，
#   自动协商分支会按 Marvell 的寄存器读速率、读错；定死 1000 走通用 IEEE 寄存器（厂商给 2020.1 打的补丁是另加 KSZ9031 分支）。
# 用法：xsct D:/HSI_AgriEdge/tools/build_periph_platform.tcl [ws]
#   ws 默认 build/board/periph_ws（不入库）；平台名 periph_plat。随后用 tools/build_periph_app.tcl 编应用。
#   Vitis IDE 里做同样的事：平台 BSP Settings 勾 xilffs、lwip211，按下面 bsp config 改参数，Drivers 页把 psu_dp 改成 dppsu。
set ROOT [file normalize [file dirname [info script]]/..]
set ws [expr {[llength $argv] > 0 ? [file normalize [lindex $argv 0]] : "$ROOT/build/board/periph_ws"}]
set xsa $ROOT/build/vivado/tt_zu5ev.xsa
if {![file exists $xsa]} { error "XSA not found: $xsa" }
if {[file exists $ws]} { error "Refusing to overwrite existing workspace: $ws; choose a new path" }
file mkdir $ws
setws $ws
puts "PLAT: creating periph_plat from $xsa"
platform create -name periph_plat -hw $xsa -proc psu_cortexa53_0 -os standalone -out $ws
platform write
domain active standalone_domain
bsp setlib -name xilffs
bsp setlib -name lwip211
bsp setdriver -ip psu_dp -driver dppsu -ver 1.3
bsp config use_lfn 1
bsp config api_mode RAW_API
bsp config lwip_dhcp false
bsp config phy_link_speed CONFIG_LINKSPEED1000
bsp config n_rx_descriptors 256
bsp config n_tx_descriptors 256
bsp config pbuf_pool_size 2048
bsp config mem_size 524288
bsp regenerate
puts "PLAT: generating (FSBL, PMUFW, BSP)"
platform generate
set bsp $ws/periph_plat/export/periph_plat/sw/periph_plat/standalone_domain
set need {bspinclude/include/ff.h bspinclude/include/lwipopts.h bspinclude/include/xdppsu.h
          bsplib/lib/libxil.a bsplib/lib/libxilffs.a bsplib/lib/liblwip4.a}
foreach f $need {
    if {![file exists $bsp/$f]} { error "PLAT FAIL: $bsp/$f missing" }
}
puts "PLAT PASS: $bsp"
