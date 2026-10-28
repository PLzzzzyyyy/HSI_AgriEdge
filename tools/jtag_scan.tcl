# JTAG link scan: check hw_server, cable and target visibility
#
# Run:  D:\AMD\2026.1\Vitis\bin\xsdb.bat D:/HSI_AgriEdge/tools/jtag_scan.tcl
#
# How to read the output:
#   connect failed   -> hw_server cannot start / port busy: kill leftover hw_server.exe
#   no targets       -> cable / ribbon / board power problem (script lists the 5 checks)
#   APU/SYSTEM etc.  -> link OK, go back and run the download script

puts "== [1/3] connect to hw_server =="
if {[catch {connect} err]} {
    puts "connect FAILED: $err"
    puts ""
    puts "-> kill all hw_server.exe processes, re-plug the downloader USB, run again."
    exit 1
}
puts "connect OK (hw_server is up)"

puts ""
puts "== [2/3] enumerate JTAG targets =="
if {[catch {set tlist [targets -nocase]} err2]} {
    puts "targets FAILED: $err2"
    exit 1
}

puts ""
puts "== [3/3] result =="
if {[llength $tlist] == 0} {
    puts "NO JTAG TARGET FOUND (available targets: none). Check in this order:"
    puts "  1) is the board powered?  (core board PWR LED on; JTAG needs target power)"
    puts "  2) is the downloader USB plugged in?  does Device Manager show"
    puts "     'Digilent USB Device' or 'Xilinx USB Cable'?  (driver comes with Vivado)"
    puts "  3) is the 10-pin ribbon seated on both ends?  pin 1 (red stripe / triangle)"
    puts "     must match pin 1 on the board header"
    puts "  4) cable voltage / VREF: header VREF is 3.3V; some downloaders need VREF wired"
    puts "  5) kill leftover hw_server.exe and retry; if still empty, cross-check with"
    puts "     Vivado Hardware Manager: Open Hardware Manager -> Open Target -> Auto Connect"
    exit 0
} else {
    puts "FOUND [llength $tlist] target(s):"
    foreach t $tlist {
        if {[catch {puts "  target $t : [targets -nocase $t -filter {name =~\"*\"}]"} e]} {
            puts "  target $t  (name query failed: $e)"
        }
    }
    puts ""
    puts "-> link OK. Next: D:\\AMD\\2026.1\\Vitis\\bin\\xsdb.bat D:/HSI_AgriEdge/build/host/dl_m1_2026.tcl"
}
exit 0
