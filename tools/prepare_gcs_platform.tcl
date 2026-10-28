# REFERENCE ONLY, NOT AN EXECUTION ENTRY. User creates/builds the platform in
# Vitis (explicit 2026-10-11 boundary); settings below document the candidate.
error "Platform creation/Build belongs to the user. See docs/gcs_20261011_user_acceptance_steps.md; do not run this reference recipe."
set ROOT [file normalize [file dirname [info script]]/..]
if {[llength $argv]!=1} {error "Exactly one NEW workspace argument required"}
set ws [file normalize [lindex $argv 0]]
if {[string first "$ROOT/build/host/" "$ws/"]!=0 || [file exists $ws]} {error "New build/host workspace only"}
set xsa $ROOT/build/vivado/tt_gcs_r1_abi4_zu5ev.xsa
if {![file exists $xsa]} {error "New complete-system XSA missing"}
file mkdir $ws
setws $ws
set plat gcs_r1_abi4_plat
set app gcs_r1_abi4_app
platform create -name $plat -hw $xsa -proc psu_cortexa53_0 -os standalone -out $ws
platform write
domain active standalone_domain
bsp setlib -name xilffs -ver 4.4
bsp setlib -name lwip211 -ver 1.3
bsp setdriver -ip psu_dp -driver dppsu -ver 1.3
bsp config stdin psu_uart_0
bsp config stdout psu_uart_0
bsp config use_lfn 1
bsp config api_mode RAW_API
bsp config lwip_dhcp false
bsp config phy_link_speed CONFIG_LINKSPEED1000
bsp config n_rx_descriptors 256
bsp config n_tx_descriptors 256
bsp config pbuf_pool_size 2048
bsp config mem_size 524288
bsp regenerate
# Generates ONLY platform libraries and its boot components, not the user App.
platform generate
app create -name $app -platform $plat -domain standalone_domain -template {Empty Application (C++)} -lang c++
app config -name $app build-config debug
app config -name $app -set compiler-optimization {Optimize more (-O2)}
app config -name $app -add compiler-misc {-std=c++14 -mcpu=cortex-a53 -ffp-contract=off -ffunction-sections -fdata-sections -Wall -Wextra -Werror}
app config -name $app -add libraries m
app config -name $app -add linker-misc {-Wl,--gc-sections -Wl,-Map=gcs_r1_abi4_app.map}
if {[llength [glob -nocomplain $ws/$app/Debug/*.elf $ws/$app/Release/*.elf]]} {error "Unexpected App Build; no source sync allowed"}
puts "GCS_PLATFORM_ONLY_PASS empty_app_not_built"
exit
