# Independent one-shot ROI business App

> 2026-10-10 checkpoint: repository sources now contain unfinished full-scene/PROBE work,
> NOT the user-built 24-file fixed-ROI App. Do not sync/build blindly. The current host runtime
> suite has unresolved new probe dependencies. See [handoff](../../../docs/gcs_20261010_next_handoff.md).
> The description below is the historical fixed-ROI baseline.


See [build/run and evidence workflow](../../../docs/s2c_roi_build_run.md).
Fixed LongKou/v2, 5x3 ROI, frozen serial M3a. Existing numerical code, BSP,
driver, S2b r1 identity provider and public interfaces are reused unchanged.
Private START/ACK/ROW plus PING/PONG/STATUS only; NOT complete v1 or a ground station.

Prepare with tools/prepare_s2c_roi.py; all unchanged dependencies are copied
with hashes. Never copy this directory alone into an old App. New App only,
automatic Build off; user builds, downloads, cold-starts and enters boot_id.
Real UDP testing waits for explicit confirmation that the new App is running.
