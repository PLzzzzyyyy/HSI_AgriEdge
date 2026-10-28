"""Prepare/sync/audit the scene+PROBE+S3 App, NEVER Build/download/reset.

prepare is workspace-only. sync requires a fresh explicit auto-Build-off flag,
checks all 24 old source hashes plus configuration, and backs up before writes.
audit is read-only after the USER's Vitis Build. No device or serial access.
"""
import argparse
from datetime import datetime
import hashlib,json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from prepare_s2c_roi import SOURCES

ROOT=Path(__file__).resolve().parents[1]
APP=Path('vitis/s2c_roi_app')
BASE_ARCHIVE=Path('report/gcs_roi/20261010_formal/user_dp_build.zip')
BASE_CONFIG=Path('report/gcs_roi/20261010_formal/app_sync_20261010_153817_247039.json')
APP_ID='scene_probe_s3_r1'
PROTECTED=('.project','.cproject','s2c_roi_app.prj','src/lscript.ld','src/README.txt')
ALLOWED={'main.cpp','roi_protocol.cpp','roi_protocol.h','roi_runtime.cpp','roi_runtime.h',
         'roi_display.cpp','roi_display.h','tt_m3a.cpp','tt_m3a.h'}
BIN=Path('D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin')

def digest(data):return hashlib.sha256(data).hexdigest()
def sha(path):return digest(path.read_bytes())
def old_config_hash(relative,archive):
    if relative in archive.namelist():return digest(archive.read(relative))
    # The user's Build ZIP did not include .prj; the preceding source-sync
    # receipt did hash/protect it. Do not invent an archive member or relax it.
    return json.loads((ROOT/BASE_CONFIG).read_text(encoding='utf-8'))['after'][relative]
def bounded_bundle(bundle):
    bundle=bundle.resolve()
    if (ROOT/'build/host').resolve() not in bundle.parents:raise ValueError('Bundle must be below build/host')
    return bundle

def prepare(bundle):
    bundle=bounded_bundle(bundle)
    records=[];protected={};changed=[]
    names={Path(p).name for p in SOURCES}
    if len(SOURCES)!=24 or len(names)!=24:raise ValueError('Unexpected source inventory')
    current={p.name for p in (ROOT/APP/'src').iterdir() if p.suffix in ('.h','.cpp','.c')}
    if current!=names:raise ValueError('Current App source set differs from the last 24-source App')
    with zipfile.ZipFile(ROOT/BASE_ARCHIVE) as z:
        for relative in SOURCES:
            name=Path(relative).name;destination=APP/'src'/name
            old=z.read(destination.as_posix())
            if sha(ROOT/destination)!=digest(old):raise ValueError('Deployed App source drift: '+name)
            new=(ROOT/relative).read_bytes()
            if new!=old:
                if name not in ALLOWED:raise ValueError('Unapproved baseline change: '+name)
                changed.append(name)
            records.append(dict(source=relative,destination='app_src/'+name,sha256=digest(new),
                                bytes=len(new),before_sha256=digest(old)))
        for name in PROTECTED:
            path=APP/name;protected[path.as_posix()]=sha(ROOT/path)
            if protected[path.as_posix()]!=old_config_hash(path.as_posix(),z):
                raise ValueError('Existing App config/linker drift: '+name)
    bundle.mkdir(parents=True,exist_ok=False);(bundle/'app_src').mkdir()
    for r in records:shutil.copyfile(ROOT/r['source'],bundle/r['destination'])
    manifest=dict(scope='PREPARED_NOT_BUILT_NOT_SYNCED',app_id=APP_ID,base='7cf479a',files=records,
        changed=sorted(changed),protected=protected,baseline_archive_sha256=sha(ROOT/BASE_ARCHIVE),baseline_config_sha256=sha(ROOT/BASE_CONFIG),
        old_elf_sha256=sha(ROOT/APP/'Debug/s2c_roi_app.elf'),platform='s1b_m3a_plat/psu_cortexa53_0/standalone_domain')
    (bundle/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest

def inspect(bundle,after_sync=False):
    bundle=bounded_bundle(bundle)
    m=json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
    if m['app_id']!=APP_ID or {r['source'] for r in m['files']}!=set(SOURCES) or len(m['files'])!=24:
        raise ValueError('Invalid manifest inventory/revision')
    if sha(ROOT/BASE_ARCHIVE)!=m['baseline_archive_sha256']:raise ValueError('Baseline archive changed')
    if sha(ROOT/BASE_CONFIG)!=m['baseline_config_sha256']:raise ValueError('Baseline config receipt changed')
    if {p.name for p in (ROOT/APP/'src').iterdir() if p.suffix in ('.h','.cpp','.c')}!={Path(p).name for p in SOURCES}:
        raise ValueError('Unexpected App source added/removed since preparation')
    if set(m['protected'])!={(APP/n).as_posix() for n in PROTECTED}:raise ValueError('Invalid config inventory')
    with zipfile.ZipFile(ROOT/BASE_ARCHIVE) as z:
        for relative,expected in m['protected'].items():
            if expected!=old_config_hash(relative,z):raise ValueError('Protected manifest hash does not match deployed evidence')
        for r in m['files']:
            name=Path(r['source']).name
            if r['destination']!='app_src/'+name:raise ValueError('Invalid bundle destination')
            if r['before_sha256']!=digest(z.read((APP/'src'/name).as_posix())):raise ValueError('Invalid old source hash')
            if any(sha(p)!=r['sha256'] for p in (ROOT/r['source'],bundle/r['destination'])):
                raise ValueError('Bundle/repo source drift: '+name)
            expected=r['sha256'] if after_sync else r['before_sha256']
            if sha(ROOT/APP/'src'/name)!=expected:raise ValueError('Existing App source drift: '+name)
    for relative,expected in m['protected'].items():
        current=(ROOT/relative).read_bytes()
        if digest(current)==expected:continue
        # Vitis asynchronously marks the existing Debug configuration dirty
        # after a source refresh. Only this boolean is volatile, ONLY during
        # post-sync/read-only audits. Compare every remaining byte to the
        # original hash; never normalize options/IDs/paths or rewrite the App.
        if after_sync and relative==(APP/'s2c_roi_app.prj').as_posix():
            normalized,count=re.subn(rb'(<configuration name="Debug" id="[^"]+") dirty="(?:true|false)"(>)',rb'\1\2',current)
            if count==1 and digest(normalized)==expected:continue
        raise ValueError('Protected config/linker changed: '+relative)
    if set(m['changed'])!={Path(r['source']).name for r in m['files'] if r['sha256']!=r['before_sha256']} or not set(m['changed'])<=ALLOWED:
        raise ValueError('Changed source list invalid')
    return m

def assert_no_build_process():
    p=subprocess.run(['powershell','-NoProfile','-Command',
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(aarch64.*|make|gmake)\\.exe$' } | Select-Object ProcessId,Name | ConvertTo-Json"],
        capture_output=True,check=True,timeout=15)
    if p.stdout.strip():raise ValueError('A Build process is active; do not sync')

def sync(bundle,auto_build_off=False):
    if auto_build_off is not True:raise ValueError('User must confirm automatic Build is OFF before any App write')
    bundle=bounded_bundle(bundle);m=inspect(bundle)
    assert_no_build_process()
    if sha(ROOT/APP/'Debug/s2c_roi_app.elf')!=m['old_elf_sha256']:raise ValueError('Existing ELF changed since preparation')
    out=ROOT/'report/gcs_roi/20261010_s3'/datetime.now().strftime('sync_%H%M%S_%f');out.mkdir(parents=True)
    backup=out/'app_before_s3.zip'
    preserve=set((ROOT/APP/'src').iterdir())|{ROOT/p for p in m['protected']}|{ROOT/APP/'Debug/s2c_roi_app.elf'}
    preserve.update((ROOT/APP/'Debug').glob('*.map'))
    with zipfile.ZipFile(backup,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(preserve):
            if p.is_file():z.write(p,p.relative_to(ROOT).as_posix())
    receipt=dict(result='FAIL',bundle=str(bundle),backup=str(backup),backup_sha256=sha(backup),
        auto_build_off_confirmed=True,copied=[],not_performed=['Build','download','device','UART','UDP'])
    try:
        # Recheck after backup, BEFORE the first write. Never roll back user data.
        inspect(bundle);assert_no_build_process()
        for name in m['changed']:
            shutil.copyfile(bundle/'app_src'/name,ROOT/APP/'src'/name);receipt['copied'].append(name)
        inspect(bundle,after_sync=True)
        if sha(ROOT/APP/'Debug/s2c_roi_app.elf')!=m['old_elf_sha256']:raise ValueError('Unexpected Build/ELF change during sync')
        receipt['result']='SYNC_ONLY_PASS_NOT_BUILT'
    finally:
        (out/'sync.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        print(out)
    return receipt

def syntax(bundle):
    bundle=bounded_bundle(bundle)
    m=json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
    out=bundle/'syntax';out.mkdir(exist_ok=False);commands=[]
    bsp=ROOT/'vitis/s1b_m3a_plat/export/s1b_m3a_plat/sw/s1b_m3a_plat/standalone_domain/bspinclude/include'
    try:
        for r in m['files']:
            if Path(r['source']).suffix!='.cpp':continue
            argv=list(map(str,[BIN/'aarch64-none-elf-g++.exe','-std=c++14','-O2','-ffp-contract=off',
                '-Wall','-Wextra','-Werror','-mcpu=cortex-a53','-I'+str(bsp),'-I'+str(bundle/'app_src'),
                '-fsyntax-only',bundle/r['destination']]))
            p=subprocess.run(argv,cwd=ROOT,capture_output=True,timeout=120)
            (out/(Path(r['source']).stem+'.log')).write_bytes(p.stdout+p.stderr)
            commands.append(dict(argv=argv,exit=p.returncode))
            if p.returncode:raise ValueError('Target syntax failed: '+r['source'])
    finally:
        (out/'checks.json').write_text(json.dumps(dict(scope='ALL_11_CPP_TARGET_SYNTAX_NOT_BUILD',commands=commands,
            result='PASS' if len(commands)==11 and all(c['exit']==0 for c in commands) else 'FAIL'),indent=2),encoding='utf-8')

def audit(bundle):
    bundle=bounded_bundle(bundle);m=inspect(bundle,after_sync=True)
    elf=ROOT/APP/'Debug/s2c_roi_app.elf'
    if sha(elf)==m['old_elf_sha256']:raise ValueError('ELF is still the OLD build; user must Build first')
    if APP_ID.encode() not in elf.read_bytes():raise ValueError('ELF does not contain the new App revision')
    import audit_s2c_build
    out=ROOT/'report/gcs_roi/20261010_s3'/datetime.now().strftime('user_build_%H%M%S_%f')
    audit_s2c_build.audit(elf,bundle,out)
    (out/'protected_metadata.json').write_text(json.dumps(dict(
        rule='Byte-exact baseline except optional Debug dirty=true/false in .prj; no config writes',
        baseline=m['protected'],current={p:sha(ROOT/p) for p in m['protected']}),indent=2),encoding='utf-8')
    symbols=(out/'symbols.txt').read_text(encoding='utf-8')
    for required in ('tt_m3a_set_wait_service(', 'NetPump::waiting(', 's2c::probe_once(', 's2c::step_scene('):
        if required not in symbols:raise ValueError('New ELF symbol missing: '+required)
    (out/'s3_audit.json').write_text(json.dumps(dict(result='NEW_ELF_READ_ONLY_PASS_NOT_BOARD_TEST',
        elf_sha256=sha(elf),app_id=APP_ID,bundle_manifest_sha256=sha(bundle/'manifest.json')),indent=2),encoding='utf-8')
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','sync','audit'])
    p.add_argument('--bundle',type=Path,default=ROOT/'build/host/gcs_scene_probe_s3_r1')
    p.add_argument('--auto-build-off',action='store_true');a=p.parse_args()
    if a.command=='prepare':
        m=prepare(a.bundle);syntax(a.bundle);print(json.dumps(dict(bundle=str(a.bundle),changed=m['changed'],status='READY_FOR_USER_SYNC_AND_BUILD_NOT_DEPLOYED'),indent=2))
    elif a.command=='sync':print(json.dumps(sync(a.bundle,a.auto_build_off),indent=2))
    else:print(audit(a.bundle))
if __name__=='__main__':main()
