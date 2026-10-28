# Catalog metadata only: no synthesis, no App Build, no hardware connection.
set ROOT [file normalize [file dirname [info script]]/../..]
set IP $ROOT/build/hls/optimization_build/tt_engine_gcs_r1_abi4_ip
ipx::open_core $IP/component.xml
set core [ipx::current_core]
ipx::update_checksums $core
ipx::check_integrity $core
ipx::save_core $core
set archive [file dirname $IP]/tt_engine_gcs_r1_abi4_ip.zip
if {[file exists $archive]} {error "Do not overwrite finalized IP archive"}
ipx::archive_core $archive $core
puts "GCS_IP_FINALIZE_PASS original_cosim_rtl_restored"
exit
