# =============================================================================
# xsct 自动化脚本 —— 无 SD 卡运行加速器
#
#   JTAG --dow -data--> DDR (权重 11.28MB + 输入 0.99MB)
#                ↓  加速器推理
#   JTAG <--mrd -bin--  结果读回 PC
#
# 用法：
#   xsct.bat tools\jtag_run.tcl <mode> [out_prefix]
#
#   mode = full   首次运行：bit + elf + 权重 + 输入，全量
#          quick  日常迭代：只传输入并重跑，复用 DDR 里已有的权重 ★
#          weight 只更新权重
#
# 例：
#   xsct.bat tools\jtag_run.tcl full  results\run001
#   xsct.bat tools\jtag_run.tcl quick results\run002
#
# ★ quick 模式原理：不执行 rst -system 时 DDR 内容保留，
#   11.28MB 权重只需传一次，后续迭代只传 0.99MB 输入。
#
# 前置检查（都是硬件层面，软件查不出来）：
#   □ JTAG 下载器接好，板子已上电（12V）
#   □ 拨码开关 = JTAG 模式
#   □ 跳帽 P5 = PS 模式（接 3&1、4&2）—— 跳错则串口无任何输出
#   □ 串口线接好，波特率 115200
# =============================================================================

set MODE       [lindex $argv 0]
set OUT_PREFIX [lindex $argv 1]
set VARIANT    [lindex $argv 2]
if { $MODE eq "" }       { set MODE "full" }
if { $OUT_PREFIX eq "" } { set OUT_PREFIX "results/run" }
if { $VARIANT eq "" }    { set VARIANT "2019" }

set PROJ_ROOT  [file normalize [file dirname [info script]]/..]

# ⚠⚠ 变体选择 —— 选错会得到全错的结果，且不会报任何错 ⚠⚠
#
#   2019 = 上游 2019.2 IP + 原版单口 BD（在 Vivado 2020.2 里重新实现）
#          ★ 这是唯一验证通过的配置：探针 32/32 通道全对，整网 corr 0.9995
#          ★ 应用工程编译宏必须带 -DXCONV_API_2019
#
#   2020 = 我们自己用 HLS 2020.2 综合的 IP
#          ⚠ 已知缺陷：每次卷积只写 4/32 个输出通道，结果全错但 ap_done 正常
#          ⚠ 已排除 21 项假设仍未定位根因，见 .claude/progress.md
#          仅用于继续排查那个悬案，不要拿来跑正常推理
#
if { $VARIANT eq "2019" } {
    set BITSTREAM "$PROJ_ROOT/vivado/conv_soc_2019/conv_soc_2019.runs/impl_1/design_1_wrapper.bit"
    set XSA       "$PROJ_ROOT/vivado/conv_soc_2019.xsa"
} elseif { $VARIANT eq "2020" } {
    set BITSTREAM "$PROJ_ROOT/vivado/conv_soc/conv_soc.runs/impl_1/design_1_wrapper.bit"
    set XSA       "$PROJ_ROOT/vivado/conv_soc.xsa"
} else {
    error "未知变体 '$VARIANT'，只能是 2019 或 2020"
}

set WEIGHT_BIN "$PROJ_ROOT/weights/weights_q.bin"
# 第 4 通道显式补零，比 input_q.bin 更确定（见 .claude/progress.md 排除清单 #7）
set INPUT_BIN  "$PROJ_ROOT/data/input_q_pad4.bin"

# ELF 路径：优先用 GUI 工程的产物，其次用命令行构建的
set ELF ""
foreach cand [list "$PROJ_ROOT/vitis/app/Debug/app.elf" \
                   "$PROJ_ROOT/vitis/app/Release/app.elf" \
                   "$PROJ_ROOT/vitis/build/pose6d.elf"] {
    if { [file exists $cand] } { set ELF $cand; break }
}
if { $ELF eq "" } { error "找不到 elf，请先在 Vitis 里 Build" }
puts "使用 ELF: $ELF"

# ---- 地址：必须与 vitis/src/mem_map.h 完全一致 ----
set ADDR_INPUT       0x10000000
set ADDR_OUT0        0x20000000
set ADDR_OUT1        0x21000000
set ADDR_DONE_FLAG   0x21F00000
set ADDR_META        0x21F00010
set ADDR_WEIGHT      0x30000000
set DONE_MAGIC       "DEADBEEF"

# ---- 输出尺寸（YOLOv4-tiny, OUT_CH=75）----
set OUT_CH     75
set N_OUT0     [expr {$OUT_CH * 13 * 13}]   ;# 12675
set N_OUT1     [expr {$OUT_CH * 26 * 26}]   ;# 50700

# ★★ mrd 的长度单位是 32-bit WORD，既不是字节也不是元素个数 ★★
proc elems_to_words {n} { return [expr {($n + 1) / 2}] }

proc timeit {label body} {
    set t0 [clock milliseconds]
    uplevel 1 $body
    set dt [expr {[clock milliseconds] - $t0}]
    puts [format "  \[耗时\] %-12s %.2f s" $label [expr {$dt/1000.0}]]
    return $dt
}

# ---------------- 前置文件检查 ----------------
foreach {f desc} [list $ELF "应用 ELF" $INPUT_BIN "输入数据"] {
    if { ![file exists $f] } { error "缺少$desc: $f" }
}
if { $MODE eq "full" && ![file exists $BITSTREAM] } {
    error "缺少 bitstream: $BITSTREAM"
}

# ---------------- 连接 ----------------
puts "\n########## 连接目标板 (mode=$MODE) ##########"
connect
puts [targets]
targets -set -filter {name =~ "ARM*#0"}

if { $MODE eq "full" } {
    # ⚠ 顺序很重要：必须先复位 APU，再下 bit，再 loadhw + ps7_init。
    #   跳过 ps7_init 会导致 DDR 控制器仍在复位，
    #   dow -data 报 "Cannot access DDR: the controller is held in reset"
    targets -set -nocase -filter {name =~ "APU*"}
    rst -system
    after 3000

    puts "\n########## 下载 bitstream ##########"
    targets -set -filter {name =~ "ARM*#0"}
    timeit "bitstream" { fpga -file $BITSTREAM }

    puts "\n########## 初始化 PS（配置 DDR 控制器）##########"
    # -regs 必须加，否则 ps7_init / ps7_post_config 这两个过程不会被注册，
    # 后面调用会报 invalid command name "ps7_init"
    loadhw -hw $XSA -mem-ranges [list {0x40000000 0xbfffffff}] -regs
    configparams force-mem-access 1
    targets -set -filter {name =~ "ARM*#0"}
    ps7_init
    ps7_post_config
    configparams force-mem-access 0
}

# ---------------- 权重 ----------------
if { $MODE eq "full" || $MODE eq "weight" } {
    puts "\n########## 写入权重 ##########"
    set sz [file size $WEIGHT_BIN]
    puts "  $WEIGHT_BIN"
    puts "  -> [format 0x%08x $ADDR_WEIGHT]   [format %.2f [expr {$sz/1048576.0}]] MB"
    # 阶段 0 待测项：这一步的实际耗时决定权重是否值得走 JTAG
    set dt [timeit "权重传输" { dow -data $WEIGHT_BIN $ADDR_WEIGHT }]
    if { $dt > 0 } {
        puts [format "  实测带宽: %.2f MB/s" [expr {$sz/1048576.0/($dt/1000.0)}]]
    }
    puts "  校验 @[format 0x%08x $ADDR_WEIGHT]: [mrd -value $ADDR_WEIGHT 4]"
}

# ---------------- 输入 ----------------
puts "\n########## 写入输入数据 ##########"
set sz [file size $INPUT_BIN]
puts "  $INPUT_BIN"
puts "  -> [format 0x%08x $ADDR_INPUT]   [format %.2f [expr {$sz/1024.0}]] KB"
timeit "输入传输" { dow -data $INPUT_BIN $ADDR_INPUT }
puts "  校验 @[format 0x%08x $ADDR_INPUT]: [mrd -value $ADDR_INPUT 4]"

# ---------------- 下载程序并运行 ----------------
puts "\n########## 下载 ELF 并运行 ##########"
dow $ELF

# 清完成标志
mwr $ADDR_DONE_FLAG 0

con

# ---- 轮询完成标志，而不是盲等固定时间 ----
puts "  等待推理完成（轮询 DONE_MAGIC）..."
set t_start [clock milliseconds]
set deadline [expr {$t_start + 60000}]
set done 0
while { [clock milliseconds] < $deadline } {
    set v [lindex [mrd -value $ADDR_DONE_FLAG 1] 0]
    if { [string toupper $v] eq $DONE_MAGIC } { set done 1; break }
    after 200
}
set wall [expr {([clock milliseconds] - $t_start)/1000.0}]
stop

if { !$done } {
    puts "  !! 超时未见完成标志。可能原因："
    puts "     - 程序卡住（看串口输出）"
    puts "     - 数据没写进去（检查上面的校验值是否全 0）"
    puts "     - bitstream 与 elf 不匹配"
} else {
    puts [format "  完成（墙钟 %.2f s，含轮询开销）" $wall]
}

# ---- 读取板上自测的延迟 ----
set meta [mrd -value $ADDR_META 4]
set lat_us [expr {0x[lindex $meta 0]}]
puts "\n########## 板上实测 ##########"
puts [format "  总推理延迟: %d us = %.2f ms  ->  %.2f FPS" \
        $lat_us [expr {$lat_us/1000.0}] [expr {1000000.0/$lat_us}]]
puts "  教程基准  : 427893 us = 427.89 ms  ->  2.34 FPS  @100MHz"
puts [format "  比值      : %.3f x" [expr {$lat_us/427893.0}]]

# ---------------- 读结果 ----------------
puts "\n########## 读回结果 ##########"
file mkdir [file dirname $OUT_PREFIX]

set w0 [elems_to_words $N_OUT0]
set w1 [elems_to_words $N_OUT1]

puts "  out0 @[format 0x%08x $ADDR_OUT0]  $N_OUT0 elems = $w0 words"
timeit "读 out0" { mrd -bin -file "${OUT_PREFIX}_out0.bin" $ADDR_OUT0 $w0 }

puts "  out1 @[format 0x%08x $ADDR_OUT1]  $N_OUT1 elems = $w1 words"
timeit "读 out1" { mrd -bin -file "${OUT_PREFIX}_out1.bin" $ADDR_OUT1 $w1 }

puts "\n=========================================="
puts " 完成"
puts "   ${OUT_PREFIX}_out0.bin   ($N_OUT0 x int16)"
puts "   ${OUT_PREFIX}_out1.bin   ($N_OUT1 x int16)"
puts ""
puts " PC 端查看："
puts "   python tools/q69.py info ${OUT_PREFIX}_out0.bin"
puts "   python tools/compare.py ${OUT_PREFIX}_out0.bin --shape $OUT_CH 13 13"
puts "=========================================="

disconnect
exit
