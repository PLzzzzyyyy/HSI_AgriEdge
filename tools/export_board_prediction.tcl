# In Vitis XSCT, execute ONE line:
#   source D:/HSI_AgriEdge/tools/export_board_prediction.tcl
# This default address belongs to the last 7020 application build. Before a later
# build, override it with: set tt_bmp_address <address printed by the board>
# Reads the completed image only. No reset, ELF download, or inference start.
# 7020 version: target filter "*A9*#0" and a 512x512 BMP; on ZU5EV use "*A53*#0".
if {![info exists tt_bmp_address]} { set tt_bmp_address 0x0070b860 }

proc tt_export_board_prediction {address} {
    set output D:/HSI_AgriEdge/board/board_prediction.bmp
    set expected 786486
    puts "BMP EXPORT BEGIN: [format 0x%08x $address] -> $output"
    flush stdout
    if {[catch {targets}]} { connect -url tcp:127.0.0.1:3121 }
    targets -set -nocase -filter {name =~ "*A9*#0"}
    set target_state [targets -filter {name =~ "*A9*#0"}]
    puts $target_state
    set resume [string match -nocase *running* $target_state]
    set fp ""
    set status [catch {
        if {$resume} { stop }
        set header [mrd -bin -size b $address 54]
        if {[string length $header] != 54 || [string range $header 0 1] ne "BM"} {
            error "No BMP header at this address. Use the address from the current BMP READY output."
        }
        binary scan [string range $header 2 5] i declared
        binary scan [string range $header 10 13] i offset
        binary scan [string range $header 18 21] i width
        binary scan [string range $header 22 25] i height
        binary scan [string range $header 26 27] s planes
        binary scan [string range $header 28 29] s bits
        binary scan [string range $header 30 33] i compression
        if {$declared != $expected || $offset != 54 || $width != 512 || $height != 512 ||
            $planes != 1 || $bits != 24 || $compression != 0} {
            error "Unexpected BMP layout: bytes=$declared width=$width height=$height bpp=$bits"
        }
        file mkdir [file dirname $output]
        set partial ${output}.part
        set fp [open $partial wb]
        fconfigure $fp -translation binary -encoding binary
        set done 0
        while {$done < $expected} {
            set count [expr {min(65536, $expected - $done)}]
            set words [expr {$count / 4}]
            set chunk [mrd -bin -size w [expr {$address + $done}] $words]
            set tail [expr {$count % 4}]
            if {$tail} {
                append chunk [mrd -bin -size b [expr {$address + $done + 4 * $words}] $tail]
            }
            if {[string length $chunk] != $count} { error "Short DDR read at offset $done" }
            puts -nonewline $fp $chunk
            flush $fp
            incr done $count
            puts "BMP READ: $done/$expected bytes"
            flush stdout
        }
        close $fp
        set fp ""
        if {[file size $partial] != $expected} { error "Saved file length is incorrect" }
        file rename -force $partial $output
        puts "BMP SAVED: [file normalize $output]"
        puts "FILE SIZE: [file size $output] bytes"
        flush stdout
    } result options]
    if {$fp ne ""} { catch {close $fp} }
    if {$resume} {
        if {[catch {con} restore_error]} { puts "Resume manually with con: $restore_error" }
    } else {
        puts "CPU was already stopped; use con to resume when ready."
    }
    if {$status} { return -options $options $result }
    return $output
}

tt_export_board_prediction $tt_bmp_address
