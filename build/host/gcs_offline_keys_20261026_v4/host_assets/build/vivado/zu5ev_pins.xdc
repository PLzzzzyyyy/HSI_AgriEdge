# AXU5EV-E / AXU5EVB-E 引脚（docs/BOARD_AXU5EV_E.md §3，出厂工程 system.xdc 同）
# 风扇：AA11，BANK43 3.3 V。AXU5EV-E 高电平转，AXU5EVB-E 低电平转，电平由 build_zu5ev.tcl 的 FAN_LEVEL 决定。
set_property PACKAGE_PIN AA11 [get_ports {fan[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {fan[0]}]
