#include "m3a_app.h"
int tt_m3a_app_once(TTM3aAppSession &s, const TTM3aSdProfile &p,
                   const TTM3aSdStorage &b, const TTM3aRoiRequest &r) {
    if (s.attempted) return TT_M3A_ROI_HALTED;
    s.attempted=true;
    // The ROI must use exactly the verified profile, not a different caller cube.
    if (r.cube!=b.files[0].data || r.cls_token!=b.files[1].data || r.pos_embed!=b.files[2].data ||
        r.width!=p.width || r.height!=p.height || r.row_pixels!=p.width+6u || !r.max_polls ||
        r.cube_bytes!=p.files[0].bytes || r.cls_count!=2646 || r.pos_count!=15876)
        return TT_M3A_SD_ARGUMENT;
    int rc=tt_m3a_sd_load(s.sd,p,b);
    if (rc) return rc; // no init/LOAD_W after any partial/unverified SD load
    s.driver_status=tt_m3a_init(0);
    if (!s.driver_status)
        s.driver_status=tt_m3a_load_weights(b.files[3].data,p.files[3].bytes,r.max_polls);
    if (s.driver_status) {
        s.roi.halted=true; // also locks LOAD_W; keep weight DMA allocation alive
        return TT_M3A_ROI_DRIVER;
    }
    rc=tt_m3a_roi_run(s.roi,r); // S1a remains sole batch/commit implementation
    s.driver_status=s.roi.driver_status;
    return rc;
}
