#!/usr/bin/env python3
"""Add only manifest sources to the new App AFTER user confirms auto-Build off.
No configuration edits, deletions, Vitis commands, Build or device operations.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "vitis/s2c_roi_app"


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def sync(bundle, confirmed):
    if not confirmed: raise ValueError("explicit user confirmation of automatic Build off is required")
    bundle = bundle.resolve()
    if (ROOT / "build/host").resolve() not in bundle.parents:
        raise ValueError("bundle must be inside workspace build/host")
    project = ET.parse(APP / "s2c_roi_app.prj").getroot()
    expected = dict(name="s2c_roi_app", cpuInstance="psu_cortexa53_0", os="standalone", language="CPP")
    if any(project.get(k) != v for k,v in expected.items()): raise ValueError("unexpected App configuration")
    if not project.get("platform", "").endswith("/s1b_m3a_plat/export/s1b_m3a_plat/s1b_m3a_plat.xpfm"):
        raise ValueError("unexpected platform")
    manifest = json.loads((bundle / "manifest.json").read_text())
    protected = [APP/p for p in (".project", ".cproject", "s2c_roi_app.prj", "src/lscript.ld", "src/README.txt")]
    before = {p.relative_to(ROOT).as_posix():sha(p) for p in protected}
    files = []
    for r in manifest["files"]:
        source = (bundle / r["destination"]).resolve()
        if source.parent != bundle / "app_src": raise ValueError("invalid manifest destination")
        origin = (ROOT / r["source"]).resolve()
        if ROOT.resolve() not in origin.parents: raise ValueError("invalid source path")
        dest = APP / "src" / source.name
        if source.suffix not in (".cpp", ".h") or sha(source) != r["sha256"] or sha(origin) != r["sha256"]:
            raise ValueError("bundle/source drift: " + source.name)
        if dest.exists() and sha(dest) != r["sha256"]: raise ValueError("refusing overwrite: " + str(dest))
        files.append((source,dest,r))
    allowed = {d.name for _,d,_ in files} | {"lscript.ld", "README.txt"}
    if any(p.name not in allowed for p in (APP/"src").iterdir()): raise ValueError("unexpected App src files")
    # Read-only build-process guard, not a replacement for the user's confirmation.
    proc = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(aarch64.*|make|gmake)\\.exe$' } | Select-Object ProcessId,Name | ConvertTo-Json"],
        capture_output=True, check=True)
    if proc.stdout.strip(): raise ValueError("build process present; do not sync")
    for source,dest,_ in files:
        if not dest.exists():
            with dest.open("xb") as f: f.write(source.read_bytes())
    after = {p.relative_to(ROOT).as_posix():sha(p) for p in protected}
    if before != after: raise ValueError("configuration changed concurrently; stop before Build")
    records = [dict(destination=d.relative_to(ROOT).as_posix(), sha256=sha(d), source=r["source"])
               for _,d,r in files]
    if any(r["sha256"] != sha(d) for _,d,r in files): raise ValueError("post-copy mismatch")
    receipt = dict(result="SOURCE_SYNC_ONLY", user_auto_build_off_confirmed=True,
        bundle=str(bundle), before=before, after=after, files=records,
        build="NOT_RUN", device="NOT_ACCESSED")
    out = ROOT / "build/host" / datetime.now().strftime("s2c_sync_%Y%m%d_%H%M%S_%f.json")
    out.write_text(json.dumps(receipt,indent=2)+"\n")
    print(out)


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle",required=True,type=Path)
    p.add_argument("--auto-build-off",action="store_true")
    a=p.parse_args(); sync(a.bundle,a.auto_build_off)
