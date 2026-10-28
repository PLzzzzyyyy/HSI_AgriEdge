
# ASCII messages are safe across Windows console code pages.

if {[catch {
proc posix {p} { return [string map {\\ /} $p] }

set here  [file dirname [file normalize [info script]]]
set root  [file normalize [file join $here .. ..]]
set fw    [file join $root firmware]

proc pick {root fw tails} {
    foreach rel $tails {
        set p [file join $fw $rel]
        if {[file exists $p]} { return $p }
    }
    foreach rel $tails {
        set p [file join $root build $rel]
        if {[file exists $p]} { return $p }
    }
    return ""
}

set bit [pick $root $fw {tt_gcs_r1_abi4_zu5ev.bit host/gcs_r1_abi4_vitis/gcs_r1_abi4_app/_ide/bitstream/tt_gcs_r1_abi4_zu5ev.bit vivado/tt_gcs_r1_abi4_zu5ev.bit}]
set xsa [pick $root $fw {tt_gcs_r1_abi4_zu5ev.xsa vivado/tt_gcs_r1_abi4_zu5ev.xsa}]
set fsbl [pick $root $fw {fsbl_a53.elf host/gcs_r1_abi4_vitis/gcs_r1_abi4_plat/zynqmp_fsbl/fsbl_a53.elf}]
set app [pick $root $fw {gcs_r1_abi4_app_parcel_temp_mirror3.elf gcs_r1_abi4_app_parcel_temp_mirror2.elf gcs_r1_abi4_app_parcel_temp_mirror.elf gcs_r1_abi4_app_dashboard_final.elf gcs_r1_abi4_app_dashboard.elf gcs_r1_abi4_app_point2.elf gcs_r1_abi4_app_point.elf gcs_r1_abi4_app_linked.elf gcs_r1_abi4_app_dpfix.elf gcs_r1_abi4_app.elf board/abi4_ws_20261017/gcs_r1_abi4_app/build/gcs_r1_abi4_app/Debug/gcs_r1_abi4_app.elf}]
set keydir ""
if {[info exists ::env(HSI_FIRMWARE_SET)]} {
    set keydir [file normalize $::env(HSI_FIRMWARE_SET)]
} elseif {[file exists $fw/keys_20261018/deployment.json]} {
    set keydir [file normalize $fw/keys_20261018]
}
if {$keydir ne ""} {
    if {$keydir ne [file normalize $fw/keys_20261018]} {error "Unexpected firmware set directory"}
    foreach {name tail} {bit tt_gcs_keys.bit xsa tt_gcs_keys.xsa fsbl fsbl_a53.elf app gcs_keys.elf} {
        set path [file join $keydir $tail]
        if {![file exists $path]} {error "Incomplete firmware set: $tail"}
        set $name $path
    }
}

foreach {name val} [list bit $bit xsa $xsa fsbl $fsbl app $app] {
    if {$val eq ""} {
        error "Missing firmware input: $name. Check firmware directory."
    }
}

puts "ROOT   : $root"
puts "PL     : [file tail $bit]"
puts "APP    : [file tail $app]"

connect
proc find_util {} {
    if {[info exists ::env(HSI_VITIS)]} {
        set p [file join $::env(HSI_VITIS) scripts vitis util zynqmp_utils.tcl]
        if {[file exists $p]} { return $p }
    }
    set dir [file dirname [info nameofexecutable]]
    for {set i 0} {$i < 6} {incr i} {
        set p [file join $dir scripts vitis util zynqmp_utils.tcl]
        if {[file exists $p]} { return $p }
        set up [file dirname $dir]
        if {$up eq $dir} { break }
        set dir $up
    }
    foreach base {D:/AMD C:/Xilinx/Vitis} {
        if {[file isdirectory $base]} {
            foreach sub [glob -nocomplain -types d [file join $base *]] {
                set p [file join $sub scripts vitis util zynqmp_utils.tcl]
                if {[file exists $p]} { return $p }
                set p [file join $sub Vitis scripts vitis util zynqmp_utils.tcl]
                if {[file exists $p]} { return $p }
            }
        }
    }
    return ""
}
set util [find_util]
if {$util eq ""} {
    error "Missing zynqmp_utils.tcl; set HSI_VITIS to the Vitis directory."
}
puts "Vitis  : $util"
source [posix $util]

puts {== [1/4] System reset ==}
targets -set -nocase -filter {name =~"APU*"}
rst -system
after 3000

puts {== [2/4] Program PL ==}
targets -set -nocase -filter {name =~ "PL"}
fpga -file [posix $bit]

puts {== [3/4] Run FSBL / initialize PS and DDR ==}
targets -set -nocase -filter {name =~"APU*"}
loadhw -hw [posix $xsa] -regs -mem-ranges [list {0x80000000 0xbfffffff} \
    {0x400000000 0x5ffffffff} {0x1000000000 0x7fffffffff}]
configparams force-mem-access 1
targets -set -nocase -filter {name =~ "*A53*#0"}
rst -processor
dow [posix $fsbl]
set bpx [bpadd -addr &XFsbl_Exit]
con -block -timeout 60
bpremove $bpx

puts {== [4/4] Download application ==}
targets -set -nocase -filter {name =~ "*A53*#0"}
rst -processor
dow [posix $app]
configparams force-mem-access 0
targets -set -nocase -filter {name =~ "*A53*#0"}
con
puts "== Firmware download complete; monitor output still requires verification =="
if {[info exists ::env(HSI_DOWNLOAD_RESULT)]} {
    set receipt [open $::env(HSI_DOWNLOAD_RESULT) w]
    puts $receipt "DOWNLOAD_OK"
    close $receipt
}
} failure options]} {
    puts stderr "ERROR: $failure"
    exit 1
}
exit 0
