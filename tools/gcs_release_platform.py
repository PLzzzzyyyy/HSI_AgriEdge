"""Inspect the USER-created platform; optionally sync all 34 App sources.

Never create/generate/build a platform, boot component or App. Never change
project metadata. Source sync requires an explicit automatic-Build-off flag;
the user creates the new standalone platform and configures the empty App.
"""
from pathlib import Path
from datetime import datetime
import argparse,json,re,shutil,subprocess,sys,zipfile,xml.etree.ElementTree as ET
import gcs_release as r

def mss(path):
    result={}
    for kind,body in re.findall(r'BEGIN (\w+)\s+(.*?)\s*END',Path(path).read_text(),re.S):
        fields=dict(re.findall(r'PARAMETER\s+(\w+)\s*=\s*(.*?)\s*$',body,re.M))
        key=(kind,fields.get('HW_INSTANCE',fields.get('LIBRARY_NAME',fields.get('PROC_INSTANCE',''))))
        if key in result:raise ValueError('Duplicate BSP component')
        result[key]=fields
    return result

def compatible_mss(old,new):
    old=dict(old);new=dict(new)
    key=('DRIVER','tt_engine_0')
    if old.get(key,{}).get('DRIVER_VER')!='2.0' or new.get(key,{}).get('DRIVER_VER')!='4.0':raise ValueError('Wrong old/new engine BSP version')
    for table in (old,new):
        table[key]=dict(table[key]);table[key]['DRIVER_VER']='GENERATED_ABI4_MAP_CHECKED'
        # XSCT may materialize defaults that were omitted in the old .mss.
        lib=('LIBRARY','lwip211');table[lib]=dict(table[lib])
        table[lib].setdefault('api_mode','RAW_API');table[lib].setdefault('lwip_dhcp','false')
    if old!=new:
        keys=[str(k) for k in sorted(set(old)|set(new)) if old.get(k)!=new.get(k)]
        raise ValueError('Unexpected BSP profile/driver changes: '+', '.join(keys))

def check_platform(ws,manifest):
    ws=r.local_output(ws);plat=ws/r.PLATFORM_NAME
    bsp=plat/'psu_cortexa53_0/standalone_domain/bsp'
    compatible_mss(mss(r.BASE_BSP/'system.mss'),mss(bsp/'system.mss'))
    if r.sha(bsp/r.PHY_REL)!=r.sha(r.BASE_BSP/r.PHY_REL):raise ValueError('PHY implementation changed; no unapproved BSP substitution')
    for path in (plat/'hw',plat/'export'/r.PLATFORM_NAME/'hw'):
        xsas=list(path.glob('*.xsa'))
        if len(xsas)!=1 or r.sha(xsas[0])!=manifest['facts']['hardware_xsa_sha256']:raise ValueError('Platform uses wrong XSA')
    include=plat/'export'/r.PLATFORM_NAME/'sw'/r.PLATFORM_NAME/'standalone_domain/bspinclude/include'
    from check_gcs_hardware import IP
    generated=next(IP.glob('drivers/*/src/xtt_engine_hw.h'))
    if r.sha(include/'xtt_engine_hw.h')!=r.sha(generated):raise ValueError('BSP register map does not match finalized IP')
    for filename in ('ff.h','lwipopts.h','xdppsu.h','xdpdma.h','xparameters.h','xtt_engine.h'):
        if not (include/filename).is_file():raise ValueError('Missing required BSP header '+filename)
    lib=include.parents[1]/'bsplib/lib'
    for filename in ('libxil.a','libxilffs.a','liblwip4.a'):
        if not (lib/filename).is_file():raise ValueError('Missing platform library '+filename)
    # Snapshot generated inputs/boot components, never borrow old compiled libs.
    files=[]
    for path in sorted(plat.rglob('*')):
        if path.is_file() and (path.suffix in ('.a','.elf','.xsa','.mss','.xpfm','.h') or path.name in ('platform.spr','psu_init.c')):
            files.append(r.record(path,str(path.resolve())))
    return dict(result='NEW_PLATFORM_PROFILE_PASS_NOT_APP_OR_BOARD',files=files,include=str(include),workspace=str(ws))

def no_app_build(ws):
    app=ws/r.APP_NAME
    if any(app.rglob('*.elf')) or any(app.rglob('*.o')):raise ValueError('App was built unexpectedly; retain it and stop')

def build_outputs(ws):
    return [r.record(p,str(p.resolve())) for p in sorted((ws/r.APP_NAME).rglob('*'))
            if p.is_file() and p.suffix in ('.elf','.o')]

def target_syntax(ws,manifest,platform,out,previous_build=None):
    out.mkdir(exist_ok=False);checks=[]
    for row in manifest['files']:
        name=Path(row['source']).name
        if not name.endswith('.cpp'):continue
        command=[str(r.BIN/'aarch64-none-elf-g++.exe'),'-std=c++14','-O2','-ffp-contract=off','-mcpu=cortex-a53',
            '-Wall','-Wextra','-Werror','-fsyntax-only','-I'+platform['include'],'-I'+str(ws/r.APP_NAME/'src'),str(ws/r.APP_NAME/'src'/name)]
        result=subprocess.run(command,capture_output=True,timeout=90)
        log=out/(Path(name).stem+'.log');log.write_bytes(result.stdout+result.stderr)
        checks.append(dict(source=name,argv=command,exit=result.returncode,log=log.name,sha256=r.sha(log)))
        (out/'checks.json').write_text(json.dumps(dict(scope='FULL_BOUND_SOURCE_SET_NEW_BSP_SYNTAX_NOT_APP_BUILD',commands=checks),indent=2)+'\n',encoding='utf-8')
        if result.returncode:raise ValueError('New BSP/bound-source target syntax failed: '+name)
    if previous_build is None:no_app_build(ws)
    elif build_outputs(ws)!=previous_build:raise ValueError('Build artifacts changed during syntax-only inspection')
    return dict(result='BOUND_SOURCE_NEW_BSP_SYNTAX_PASS_NOT_BUILD',commands=len(checks),path=str(out/'checks.json'),sha256=r.sha(out/'checks.json'))

def check_empty_app(bundle,ws):
    app=ws/r.APP_NAME;src=app/'src';no_app_build(ws)
    project=ET.parse(app/(r.APP_NAME+'.prj')).getroot()
    if project.get('os')!='standalone' or project.get('cpuInstance')!='psu_cortexa53_0' or project.get('cpu')!='standalone_domain':
        raise ValueError('User App must target A53 standalone_domain, not another CPU/OS')
    actual=Path(project.get('platform','')).resolve()
    expected=ws/r.PLATFORM_NAME/'export'/r.PLATFORM_NAME/(r.PLATFORM_NAME+'.xpfm')
    if actual!=expected.resolve():raise ValueError('User App references a different platform')
    if not src.is_dir() or any(p.suffix in ('.cpp','.c','.h') for p in src.iterdir()):raise ValueError('User must provide a new empty App; do not overwrite sources')
    linker=bundle/'host_assets/vitis/s2c_roi_app/src/lscript.ld'
    if r.sha(src/'lscript.ld')!=r.sha(linker):raise ValueError('User linker differs from reviewed low-DDR linker; inspect before sync')
    return [r.record(p,str(p.resolve())) for p in (app/'.project',app/'.cproject',app/(r.APP_NAME+'.prj'),src/'lscript.ld')]

def assert_no_build_process():
    command=['powershell','-NoProfile','-Command',
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(aarch64.*|make|gmake|xsct)\\.exe$' } | Select-Object ProcessId,Name | ConvertTo-Json"]
    result=subprocess.run(command,capture_output=True,check=True,timeout=15)
    if result.stdout.strip():raise ValueError('Build/platform process active; no source writes')

def sync_sources(bundle,ws,manifest,platform,out,auto_build_off=False):
    if auto_build_off is not True:raise ValueError('User must confirm automatic Build OFF immediately before sync')
    app=ws/r.APP_NAME;src=app/'src';protected=check_empty_app(bundle,ws);assert_no_build_process()
    backup=out/'new_app_before_sync.zip'
    with zipfile.ZipFile(backup,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob('*')):
            if path.is_file():archive.write(path,path.relative_to(ws).as_posix())
    if protected!=check_empty_app(bundle,ws):raise ValueError('User App changed during backup; no source writes')
    assert_no_build_process()
    for row in manifest['files']:shutil.copyfile(bundle/row['destination'],src/Path(row['source']).name)
    for row in manifest['files']:
        if r.sha(src/Path(row['source']).name)!=row['sha256']:raise ValueError('Synced source mismatch')
    no_app_build(ws)
    for row in protected:
        if r.sha(row['path'])!=row['sha256']:raise ValueError('User metadata changed during source sync')
    from gcs_release_elf import normalized_prj
    import hashlib
    for row in protected:
        if row['path'].endswith('.prj'):row['normalized_sha256']=hashlib.sha256(normalized_prj(Path(row['path']).read_bytes())).hexdigest()
    return dict(result='SYNC_ALL_SOURCES_PASS_NOT_APP_BUILD_NOT_BOARD',release_id=manifest['release_id'],app_id=r.APP_ID,
        workspace=str(ws),app=str(app),files=manifest['files'],protected=protected,platform=platform,
        automatic_build_off_confirmed=True,user_build_required=True,existing_vitis_untouched=True,
        backup=dict(path=str(backup),sha256=r.sha(backup)))

def check_refresh(bundle,ws,manifest,previous):
    """Only rebind unchanged firmware after a bounded validator-only revision."""
    from gcs_release_elf import verify_sync,audit_identity,normalized_prj
    import hashlib
    previous=r.local_output(previous)
    if previous==r.local_output(bundle):raise ValueError('Keep the previous release bundle intact')
    old=json.loads((previous/'manifest.json').read_text(encoding='utf-8'))
    if (old['release_id']!=r.canonical(old['facts']) or old['app_id']!=r.APP_ID or
        old['facts']['source_set_sha256']!=r.canonical(old['sources']) or
        old['facts']['asset_set_sha256']!=r.canonical(old['assets'])):
        raise ValueError('Invalid previous release identity')
    for key in ('source_set_sha256','hardware_xsa_sha256','data_set_sha256'):
        if old['facts'][key]!=manifest['facts'][key]:raise ValueError('Refresh is not a firmware/hardware/data update: '+key)
    old_data=dict(old['data_inventory']);new_data=dict(manifest['data_inventory'])
    old_data.pop('created',None);new_data.pop('created',None)  # Observation time is not input data.
    if old['sources']!=manifest['sources'] or old_data!=new_data:
        raise ValueError('Previous/new firmware or data inventory differs')
    allowed={'tools/gcs_release.py','tools/gcs_release_platform.py','tools/gcs_release_elf.py'}
    a={x['path']:x for x in old['assets']};b={x['path']:x for x in manifest['assets']}
    changed={k for k in set(a)|set(b) if a.get(k)!=b.get(k)}
    if not changed or not changed<=allowed or old['release_id']==manifest['release_id']:
        raise ValueError('Not a bounded validator-only asset update')
    for row in old['assets']:
        f=previous/'host_assets'/r.safe_relative(row['path'])
        if r.sha(f)!=row['sha256'] or f.stat().st_size!=row['bytes']:raise ValueError('Previous frozen asset changed')
    old_files={x['source']:x for x in old['files']};new_files={x['source']:x for x in manifest['files']}
    changes=[Path(k).name for k in sorted(set(old_files)|set(new_files)) if old_files.get(k)!=new_files.get(k)]
    if changes!=['roi_release.h']:raise ValueError('Refresh must change only the bound release header')
    for row in old['files']:
        f=previous/r.safe_relative(row['destination'])
        if r.sha(f)!=row['sha256'] or f.stat().st_size!=row['bytes']:raise ValueError('Previous bundled source changed')
    old_sync,_=verify_sync(previous,old)
    if Path(old_sync['workspace']).resolve()!=ws.resolve():raise ValueError('Refresh workspace differs from previous sync')
    app=ws/r.APP_NAME;elf=app/'Debug'/(r.APP_NAME+'.elf')
    if not elf.is_file():
        raise ValueError('Retain the exact previous-release user ELF before refresh')
    audit_identity(elf.read_bytes(),old)
    protected=[r.record(Path(x['path']),x['path']) for x in old_sync['protected']]
    for row in protected:
        if row['path'].endswith('.prj'):row['normalized_sha256']=hashlib.sha256(normalized_prj(Path(row['path']).read_bytes())).hexdigest()
    return dict(protected=protected,retained_build_outputs=build_outputs(ws),previous_release_id=old['release_id'],
        previous_manifest=r.record(previous/'manifest.json',str(previous/'manifest.json')),
        previous_sync=r.record(previous/'sync.json',str(previous/'sync.json')),changed_assets=sorted(changed),changed_source_names=changes)

def refresh_sources(bundle,ws,manifest,platform,out,previous,auto_build_off=False):
    if auto_build_off is not True:raise ValueError('Current automatic-Build-off confirmation required before refresh')
    before=check_refresh(bundle,ws,manifest,previous);assert_no_build_process()
    app=ws/r.APP_NAME;backup=out/'app_before_validator_refresh.zip'
    with zipfile.ZipFile(backup,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob('*')):
            if path.is_file():archive.write(path,path.relative_to(ws).as_posix())
    if check_refresh(bundle,ws,manifest,previous)!=before:raise ValueError('App changed during refresh backup; no source writes')
    assert_no_build_process()
    for row in manifest['files']:shutil.copyfile(bundle/row['destination'],app/'src'/Path(row['source']).name)
    for row in manifest['files']:
        if r.sha(app/'src'/Path(row['source']).name)!=row['sha256']:raise ValueError('Refreshed source mismatch')
    from gcs_release_elf import normalized_prj
    import hashlib
    for row in before['protected']:
        f=Path(row['path'])
        if r.sha(f)!=row['sha256']:
            if f.suffix!='.prj' or hashlib.sha256(normalized_prj(f.read_bytes())).hexdigest()!=row['normalized_sha256']:
                raise ValueError('Project configuration changed during refresh')
    if build_outputs(ws)!=before['retained_build_outputs']:raise ValueError('Unexpected Build during source refresh')
    return dict(result='SYNC_ALL_SOURCES_PASS_NOT_APP_BUILD_NOT_BOARD',release_id=manifest['release_id'],app_id=r.APP_ID,
        workspace=str(ws),app=str(app),files=manifest['files'],platform=platform,**before,
        automatic_build_off_confirmed=True,user_build_required=True,prior_elf_retained_not_current=True,
        existing_vitis_untouched=True,backup=dict(path=str(backup),sha256=r.sha(backup)))

def inspect_user_platform(bundle,ws,out,platform_log,sync=False,auto_build_off=False,refresh_from=None):
    bundle=r.local_output(bundle);ws=r.local_output(ws);out=r.local_output(out)
    if not ws.is_dir() or out.exists():raise ValueError('User-created workspace and NEW receipt directory required')
    if sync and auto_build_off is not True:raise ValueError('Explicit user automatic-Build-off confirmation required; no App writes')
    if refresh_from is not None and not sync:raise ValueError('Refresh requires explicit source synchronization mode')
    platform_log=Path(platform_log).resolve()
    if not platform_log.is_file() or not platform_log.stat().st_size:raise ValueError('Preserve the user platform Build log first')
    manifest=r.inspect(bundle);out.mkdir(parents=True,exist_ok=False)
    receipt=dict(result='RUNNING',started=datetime.now().isoformat(),workspace=str(ws),not_performed=['Platform create/generate/Build','FSBL/PMUFW Build','App create/Build','device','UART','UDP','service replacement'])
    def save():(out/'run.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        text=platform_log.read_text(encoding='utf-8',errors='replace')
        if re.search(r'(?im)^\s*(error:|fatal:)',text):raise ValueError('User platform Build log contains errors; do not sync')
        platform=check_platform(ws,manifest);platform['build_log']=r.record(platform_log,str(platform_log))
        receipt['platform']=platform
        if sync:
            if (bundle/'sync.json').exists():raise ValueError('Existing synchronization receipt; no overwrite or repeated sync')
            r.inspect(bundle)
            if refresh_from is None:
                no_app_build(ws);result=sync_sources(bundle,ws,manifest,platform,out,auto_build_off)
            else:result=refresh_sources(bundle,ws,manifest,platform,out,refresh_from,auto_build_off)
            result['syntax']=target_syntax(ws,manifest,platform,out/'target_syntax',result.get('retained_build_outputs'))
            (bundle/'sync.json').open('x',encoding='utf-8').write(json.dumps(result,indent=2)+'\n')
            (out/'sync.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
            receipt['result']=result['result']
        else:receipt['result']='USER_PLATFORM_READ_ONLY_PASS_NOT_SYNCED_OR_APP_BUILD'
    except Exception as exc:receipt.update(result='FAIL',error=str(exc));raise
    finally:receipt['finished']=datetime.now().isoformat();save()
    return receipt
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',type=Path,default=r.BUNDLE);p.add_argument('--workspace',type=Path,default=r.WORKSPACE);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--platform-log',type=Path,required=True);p.add_argument('--sync',action='store_true');p.add_argument('--auto-build-off',action='store_true')
    p.add_argument('--refresh-from',type=Path,help='Previous frozen ABI4 bundle; only validator changes and the bound header may differ')
    a=p.parse_args();print(json.dumps(inspect_user_platform(a.bundle,a.workspace,a.out,a.platform_log,a.sync,a.auto_build_off,a.refresh_from),indent=2))
