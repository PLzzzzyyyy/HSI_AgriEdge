# Query installed Vivado device metadata only; no project or synthesis.
foreach pattern {xczu5ev-*-e xc7z020clg400-2} {
    set matches [get_parts -quiet $pattern]
    if {[llength $matches] == 0} { set matches [get_parts -quiet xczu5ev*] }
    set device [lindex $matches 0]
    puts "DEVICE: $device"
    foreach property [lsort [list_property $device]] {
        if {[regexp -nocase {lut|flip|dsp|ram|cell|family|device} $property]} {
            puts "$property = [get_property $property $device]"
        }
    }
}
exit
