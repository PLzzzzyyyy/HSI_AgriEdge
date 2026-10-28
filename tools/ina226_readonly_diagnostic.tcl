# JTAG observation only: no CPU halt/reset, FPGA download, GPIO drive or I2C write.
if {[catch {
    connect
    puts "INA226_DIAG TARGETS_BEGIN"
    puts [targets]
    puts "INA226_DIAG TARGETS_END"
    targets -set -filter {name == "PSU"}
    foreach {name base count} {
        MIO24_25 0xff180060 2
        I2C0_CTRL_STATUS 0xff020000 2
        I2C1_CTRL_STATUS 0xff030000 2
        GPIO_EMIO_DATA_RO_3 0xff0a006c 1
    } {
        puts "INA226_DIAG $name"
        puts [mrd $base $count]
    }
    puts "INA226_DIAG READONLY_DONE"
    disconnect
} message]} {
    puts stderr "INA226_DIAG ERROR: $message"
    exit 1
}
exit 0
