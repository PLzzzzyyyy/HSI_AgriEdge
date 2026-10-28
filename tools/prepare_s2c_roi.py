#!/usr/bin/env python3
"""Prepare independent source bundle only. No Vitis Build/sync/device/network.
Does not revalidate old numeric/SD acceptance; copies unchanged proven modules.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = "src/ps/s2c_roi_app/"
SOURCES = [PRIVATE + n for n in ("main.cpp", "roi_protocol.h", "roi_protocol.cpp",
    "roi_runtime.h", "roi_runtime.cpp", "s1b_profile.h", "roi_canvas.h", "roi_canvas.cpp",
    "roi_display.h", "roi_display.cpp")]
SOURCES += ["src/ps/s2b_idle_app/" + n for n in ("boot_id.cpp", "boot_id.h")]
SOURCES += ["src/ps/" + n for n in ("tt_m3a.cpp", "tt_m3a.h", "tt_net.cpp", "tt_net.h", "tt_hw.h")]
SOURCES += ["src/ps/system/" + n for n in ("m3a_roi.cpp", "m3a_roi.h", "m3a_sd.cpp", "m3a_sd.h", "m3a_app.h", "s1b/legacy_traps.cpp")]
SOURCES += ["src/hls/tt_engine_regs.h"]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def prepare(out):
    out = out.resolve()
    build = (ROOT / "build/host").resolve()
    if build not in out.parents:
        raise ValueError("source bundle must be a new directory below build/host, never vitis")
    out.mkdir(parents=True, exist_ok=False)
    dst = out / "app_src"; dst.mkdir()
    manifest = dict(scope="SOURCE_ONLY_NOT_BUILT_NOT_DEPLOYED", base="da8d476", files=[],
                    old_baselines="NOT_RERUN", app="s2c_roi_app",
                    platform="s1b_m3a_plat/psu_cortexa53_0/standalone_domain")
    for rel in SOURCES:
        p = ROOT / rel
        if not rel.startswith(PRIVATE):
            # Raw tracked source may be CRLF locally. Git path comparison is
            # normalized by Git, unlike artifact SHA which hashes raw bytes.
            diff = subprocess.run(["git", "diff", "da8d476", "--", rel], cwd=ROOT,
                                  capture_output=True, check=True).stdout
            if diff:
                raise ValueError(f"Frozen source changed: {rel}")
        target = dst / p.name
        if target.exists(): raise ValueError("basename collision")
        shutil.copyfile(p, target)
        manifest["files"].append(dict(source=rel, destination="app_src/" + p.name,
                                     bytes=p.stat().st_size, sha256=sha(p)))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(out)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    prepare(parser.parse_args().out)
