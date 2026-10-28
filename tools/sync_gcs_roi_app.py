"""Update exactly seven private App files after user auto-Build-off confirmation.
Back up existing App sources/config/ELF, preserve config/lscript, no Build/device.
"""
import argparse
from datetime import datetime
import hashlib,json
from pathlib import Path
import shutil,subprocess,zipfile
ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'vitis/s2c_roi_app'
CHANGED={'main.cpp','roi_runtime.cpp','roi_runtime.h'}
ADDED={'roi_canvas.cpp','roi_canvas.h','roi_display.cpp','roi_display.h'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--bundle',type=Path,required=True)
    ap.add_argument('--auto-build-off',action='store_true');a=ap.parse_args()
    if not a.auto_build_off:raise ValueError('User must explicitly confirm auto-Build off')
    bundle=a.bundle.resolve()
    if (ROOT/'build/host').resolve() not in bundle.parents:raise ValueError('Bundle outside build/host')
    old=json.loads((ROOT/'report/system_s2c/20261010_minimal_roi/source_sync.json').read_text())
    # Entire current App source set must still be the last verified S2c build source set.
    for r in old['files']:
        if sha(ROOT/r['destination'])!=r['sha256']:raise ValueError('Existing App drift: '+r['destination'])
    for name in ADDED:
        if (APP/'src'/name).exists():raise ValueError('New file already exists; do not overwrite: '+name)
    proc=subprocess.run(['powershell','-NoProfile','-Command',
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(aarch64.*|make|gmake)\\.exe$' } | Select-Object ProcessId,Name | ConvertTo-Json"],capture_output=True,check=True)
    if proc.stdout.strip():raise ValueError('Build process active')
    manifest=json.loads((bundle/'manifest.json').read_text())
    records={Path(r['source']).name:r for r in manifest['files']}
    for name,r in records.items():
        for p in (bundle/'app_src'/name,ROOT/r['source']):
            if sha(p)!=r['sha256']:raise ValueError('Bundle/source drift: '+name)
        if name not in CHANGED|ADDED and sha(APP/'src'/name)!=r['sha256']:raise ValueError('Unexpected source change: '+name)
    protected=[APP/p for p in ('.project','.cproject','s2c_roi_app.prj','src/lscript.ld','src/README.txt')]
    before={p.relative_to(ROOT).as_posix():sha(p) for p in protected}
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    out=ROOT/'report/gcs_roi/20261010_formal';out.mkdir(parents=True,exist_ok=True)
    backup=out/f'app_before_dp_{stamp}.zip'
    preserved=list((APP/'src').glob('*'))+protected+[APP/'Debug/s2c_roi_app.elf']
    preserved+=list((APP/'Debug').glob('*.map'))
    with zipfile.ZipFile(backup,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(set(preserved)):
            if p.is_file():z.write(p,p.relative_to(ROOT).as_posix())
    for name in sorted(CHANGED|ADDED):
        shutil.copyfile(bundle/'app_src'/name,APP/'src'/name)
    after={p.relative_to(ROOT).as_posix():sha(p) for p in protected}
    if before!=after:raise ValueError('Configuration changed; stop before Build')
    for name,r in records.items():
        if sha(APP/'src'/name)!=r['sha256']:raise ValueError('Post-sync mismatch: '+name)
    receipt=dict(result='SOURCE_SYNC_ONLY_NOT_BUILT',confirmed_auto_build_off=True,
                 user_confirmation='2026-10-10 用户回复 欧克（回应关闭自动Build及七文件同步确认）',
                 backup=backup.name,backup_sha256=sha(backup),bundle=str(bundle),
                 changed=sorted(CHANGED),added=sorted(ADDED),before=before,after=after,
                 matched_files=len(records),files=list(records.values()),device='NOT_ACCESSED')
    dest=out/f'app_sync_{stamp}.json';dest.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(dest);print('24/24 source SHA matched; config/lscript unchanged; no Build/device')
if __name__=='__main__':main()
