"""ABI4 full source/asset/hardware/data release gates. Never Build an App.

The legacy 24-source bundle is not a release input. New workspaces/bundles only;
existing Vitis projects, old ELF/XSA, running services and devices stay intact.
"""
from pathlib import Path,PurePosixPath
from datetime import datetime
import argparse,hashlib,json,os,re,shutil,struct,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'gcs'))
from board_release import APP_ID,ENGINE_ABI
# Candidate default only: existing bundles and running services stay intact.
BUNDLE=ROOT/'build/host/gcs_r1_abi4_release_v6'
WORKSPACE=ROOT/'build/host/gcs_r1_abi4_vitis'
APP_NAME='gcs_r1_abi4_app';PLATFORM_NAME='gcs_r1_abi4_plat'
PRIVATE=('main.cpp','roi_protocol.h','roi_protocol.cpp','roi_runtime.h','roi_runtime.cpp','s1b_profile.h',
    'roi_canvas.h','roi_canvas.cpp','roi_display.h','roi_display.cpp','roi_labels.h','roi_results.h',
    'roi_models.h','roi_models.cpp','roi_model_sd.h','roi_model_sd.cpp','roi_timing.h',
    'roi_boot_id.h','roi_boot_id.cpp','roi_boot_sd.cpp','roi_release.h','roi_board_log.h','roi_keys.h',
    'roi_power.h','roi_power_profile.h')
SOURCES=tuple('src/ps/s2c_roi_app/'+n for n in PRIVATE)+tuple('src/ps/'+n for n in
    ('tt_m3a.cpp','tt_m3a.h','tt_net.cpp','tt_net.h','tt_hw.h','tt_measure.h'))+tuple('src/ps/system/'+n for n in
    ('m3a_roi.cpp','m3a_roi.h','m3a_sd.cpp','m3a_sd.h','m3a_app.h','s1b/legacy_traps.cpp'))+('src/hls/tt_engine_regs.h',)
TOOLS=('gcs_release.py','gcs_release_platform.py','gcs_release_elf.py','prepare_gcs_platform.tcl',
    'check_gcs_hardware.py','install_gcs_cycle_counter.py','finalize_gcs_ip.py','run_gcs_hardware.py',
    'gcs_task_verify.py','gcs_model_verify.py','gcs_probe_verify.py','gcs_scene_verify.py','gcs_data_inventory.py',
    'gcs_boot_bundle.py','gcs_boot_provision.py','gcs_sd_boot_verify.py','gcs_roi.py','s2c_roi_client.py')
BIN=Path('D:/xilinx/Vitis/2020.2/gnu/aarch64/nt/aarch64-none/bin')
BASE_PLATFORM=ROOT/'vitis/s1b_m3a_plat'
BASE_BSP=BASE_PLATFORM/'psu_cortexa53_0/standalone_domain/bsp'
PHY_REL='psu_cortexa53_0/libsrc/lwip211_v1_3/src/contrib/ports/xilinx/netif/xemacpsif_physpeed.c'
REFERENCES=(ROOT/'vitis/s2c_roi_app/src/lscript.ld',BASE_BSP/'system.mss',BASE_BSP/PHY_REL)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while block:=f.read(1<<20):h.update(block)
    return h.hexdigest()
def canonical(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def safe_relative(value):
    p=PurePosixPath(value)
    if p.is_absolute() or not p.parts or '..' in p.parts or ':' in value or '\\' in value:raise ValueError('Unsafe release relative path')
    return Path(*p.parts)
def local_output(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT/'build/host') or path==ROOT/'build/host':raise ValueError('Isolated build/host path required')
    return path
def record(path,relative=None):
    path=Path(path);return dict(path=relative or path.relative_to(ROOT).as_posix(),bytes=path.stat().st_size,sha256=sha(path))
def asset_paths():
    paths={ROOT/'tools'/n for n in TOOLS}
    paths.update(REFERENCES)
    paths.update(ROOT/p for p in ('build/hls/run_gcs_round1.tcl','build/vivado/build_gcs_round1.tcl',
        'build/vivado/finalize_gcs_ip.tcl','build/vivado/psu_cfg_factory.tcl','build/vivado/zu5ev_pins.xdc',
        'src/rtl/tt_gcs_cycle_counter.v','board/boot/gcs_round1.bif.in'))
    paths.update(ROOT/p for p in ('src/rtl/tt_key_sync.v','tools/build_keys_hardware.tcl',
        'tools/export_keys_engine.tcl','tools/link_keys_hardware.tcl'))
    paths.update(ROOT/p for p in ('tools/eco_keys_hardware.tcl','tools/package_keys_hardware.py'))
    paths.update(ROOT/p for p in ('tools/launcher/start_demo.py','tools/launcher/dl_gcs_demo.tcl'))
    paths.update(p for p in (ROOT/'gcs').glob('*') if p.suffix in ('.py','.json'))
    paths.update(p for p in (ROOT/'gcs/web').rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.update((ROOT/'model').glob('*.py'))
    paths.update((ROOT/'src/hls').glob('*.h'));paths.update((ROOT/'src/hls').glob('*.cpp'))
    return sorted(paths)
def runtime_assets():return [record(p) for p in asset_paths()]
def source_records():
    if len({Path(p).name.lower() for p in SOURCES})!=len(SOURCES):raise ValueError('Flat App basename collision')
    records=[record(ROOT/p,p) for p in SOURCES]
    private={p.name for p in (ROOT/'src/ps/s2c_roi_app').iterdir() if p.suffix in ('.h','.cpp','.c')}
    if private!=set(PRIVATE):raise ValueError('Unlisted private App source/header')
    known={Path(p).name for p in SOURCES}
    local_headers={p.name for base in ('src/ps','src/ps/system','src/hls') for p in (ROOT/base).glob('*.h')}|private
    for row in records:
        includes=set(re.findall(r'^\s*#include\s+"([^"]+)"',(ROOT/row['path']).read_text(encoding='utf-8'),re.M))
        missing=(includes&local_headers)-known
        if missing:raise ValueError('Missing transitive App headers: '+str(sorted(missing)))
    return records
def render_header(text,facts,release_id):
    substitutions={'#define S2C_RELEASE_BOUND 0':'#define S2C_RELEASE_BOUND 1',
        'UNBOUND_RELEASE':release_id,'UNBOUND_SOURCES':facts['source_set_sha256'],'UNBOUND_XSA':facts['hardware_xsa_sha256']}
    if f'#define S2C_APP_ID "{APP_ID}"' not in text:raise ValueError('App marker mismatch')
    for before,after in substitutions.items():
        if text.count(before)!=1:raise ValueError('Unexpected release header template')
        text=text.replace(before,after)
    return text.encode('utf-8')
def hardware():
    from check_gcs_hardware import system_ready
    return system_ready()
def verify_data(data):
    if not data.get('local_data_verified') or data.get('errors') or not data.get('files'):raise ValueError('Verified complete local data inventory required')
    destinations=[]
    for row in data['files']:
        dest=safe_relative(row['destination']);destinations.append(dest.as_posix())
        if dest.parts[0]!='scenes' or sha(row['source'])!=row['sha256'] or Path(row['source']).stat().st_size!=row['bytes']:
            raise ValueError('Local data drift/invalid destination')
    if len(destinations)!=len(set(destinations)):raise ValueError('Duplicate data destination')

def prepare(bundle):
    bundle=local_output(bundle)
    if bundle.exists():raise ValueError('Refuse existing release bundle')
    hw=hardware();sources=source_records();assets=runtime_assets()
    from gcs_data_inventory import inventory
    data=inventory(ROOT/'data/scenes');verify_data(data)
    facts=dict(schema=1,app_id=APP_ID,engine_abi=ENGINE_ABI,source_set_sha256=canonical(sources),
        asset_set_sha256=canonical(assets),hardware_xsa_sha256=hw['xsa']['sha256'],data_set_sha256=canonical(data['files']))
    rid=canonical(facts);bundle.mkdir(parents=True,exist_ok=False);(bundle/'app_src').mkdir()
    m=dict(result='PREPARED_NOT_SYNCED_NOT_BUILT_NOT_BOARD',created=datetime.now().isoformat(),facts=facts,release_id=rid,
        app_id=APP_ID,sources=sources,assets=assets,files=[],hardware=hw,data_inventory=data)
    for row in sources:
        name=Path(row['path']).name;dst=bundle/'app_src'/name;raw=(ROOT/row['path']).read_bytes()
        if name=='roi_release.h':raw=render_header(raw.decode('utf-8'),facts,rid)
        dst.write_bytes(raw);m['files'].append(dict(source=row['path'],destination='app_src/'+name,bytes=len(raw),sha256=sha(dst)))
    for row in assets:
        dst=bundle/'host_assets'/row['path'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/row['path'],dst)
    (bundle/'hardware').mkdir();shutil.copyfile(ROOT/hw['xsa']['path'],bundle/'hardware'/Path(hw['xsa']['path']).name)
    (bundle/'data_inventory.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    (bundle/'manifest.json').write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8')
    inspect(bundle)
    return m

def inspect(bundle=BUNDLE,check_data=True):
    bundle=local_output(bundle);m=json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
    sources=source_records();assets=runtime_assets();facts=m['facts']
    if m.get('app_id')!=APP_ID or facts.get('engine_abi')!=ENGINE_ABI or m['release_id']!=canonical(facts):raise ValueError('Wrong/tampered release identity')
    if sources!=m['sources'] or assets!=m['assets'] or canonical(sources)!=facts['source_set_sha256'] or canonical(assets)!=facts['asset_set_sha256']:
        raise ValueError('Release source/host asset drift; no old service or partial resync')
    if {r['source'] for r in m['files']}!=set(SOURCES) or len(m['files'])!=len(SOURCES):raise ValueError('Incomplete App source set')
    if {p.name for p in (bundle/'app_src').iterdir()}!={Path(p).name for p in SOURCES}:raise ValueError('Unexpected bundled source')
    for row in m['files']:
        if row['destination']!='app_src/'+Path(row['source']).name:raise ValueError('Unexpected source destination')
        path=bundle/safe_relative(row['destination']);raw=(ROOT/row['source']).read_bytes()
        if path.name=='roi_release.h':raw=render_header(raw.decode('utf-8'),facts,m['release_id'])
        if path.read_bytes()!=raw or sha(path)!=row['sha256'] or path.stat().st_size!=row['bytes']:raise ValueError('Bundled source drift: '+path.name)
    for row in assets:
        if sha(bundle/'host_assets'/safe_relative(row['path']))!=row['sha256']:raise ValueError('Bundled host asset drift')
    hw=hardware()
    if hw['xsa']!=m['hardware']['xsa'] or hw['xsa']['sha256']!=facts['hardware_xsa_sha256'] or hw['ip_tree_sha256']!=m['hardware']['ip_tree_sha256']:
        raise ValueError('Release IP/XSA mismatch')
    if sha(bundle/'hardware'/Path(hw['xsa']['path']).name)!=hw['xsa']['sha256']:raise ValueError('Bundled XSA drift')
    if canonical(m['data_inventory']['files'])!=facts['data_set_sha256']:raise ValueError('Data inventory identity mismatch')
    if json.loads((bundle/'data_inventory.json').read_text(encoding='utf-8'))!=m['data_inventory']:raise ValueError('Separate data inventory drift')
    if check_data:verify_data(m['data_inventory'])
    return m

DEMO_ENV='GCS_LOCAL_DEMO'

def demo_mode():
    """本地演示开关：只跳过「GUI 建平台 + 人工审查 ELF」这道发布门禁，其余身份仍然对齐。

    启用方式：set GCS_LOCAL_DEMO=1
    仍然要求：bundle manifest 的 release_id / source_set / xsa 与板上 INFO 回报的一致。
    不做的事：不校验 approved_elf.json、不校验平台 BSP 同步回执。
    因此**不能**把这条路径的产物写进验收/发布证据；只在本地演示与 UI 联调时用。
    """
    return os.environ.get(DEMO_ENV,'')=='1'

def demo_receipt(bundle=BUNDLE,loaded_assets=None):
    bundle=Path(os.environ.get('GCS_LOCAL_DEMO_BUNDLE') or bundle).resolve()
    local_output(bundle)
    man=json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
    facts=dict(man['facts'])
    if man.get('app_id')!=APP_ID or man.get('release_id')!=canonical(facts):
        raise ValueError('Invalid local demo manifest identity')
    candidate=man.get('local_demo_elf')
    is_candidate=bool(os.environ.get('GCS_LOCAL_DEMO_BUNDLE')) or man.get('result')=='LOCAL_DEMO_CANDIDATE_NOT_RELEASE_AUDIT'
    if is_candidate and not candidate:
        raise ValueError('Local demo candidate has not registered a built firmware')
    if candidate:
        if canonical(man['sources'])!=facts['source_set_sha256'] or canonical(man['assets'])!=facts['asset_set_sha256']:
            raise ValueError('Local demo candidate source/asset identity mismatch')
        current_assets=runtime_assets() if loaded_assets is None else loaded_assets
        if current_assets!=man['assets']:
            raise ValueError('Local demo assets changed; restart the console with this candidate')
        elf=ROOT/safe_relative(candidate['path'])
        if sha(elf)!=candidate['sha256']:
            raise ValueError('Local demo firmware differs from manifest')
    receipt=dict(result='LOCAL_DEMO_UNREVIEWED',demo=True,app_id=man['app_id'],
        release_id=man['release_id'],source_set_sha256=facts['source_set_sha256'],
        hardware_xsa_sha256=facts['hardware_xsa_sha256'],facts=facts,
        sources=man['sources'],assets=man['assets'],
        warning='本地演示模式（GCS_LOCAL_DEMO=1）：未做发布审查，不得作为验收/发布证据')
    path=bundle/'local_demo_receipt.json'
    path.write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('!! 本地演示模式：跳过发布审查，release_id=%s' % man['release_id'][:16])
    return path
def audited_elf(bundle=BUNDLE,loaded_assets=None):
    """Passive validation of the USER-built ELF before any serial/UDP open."""
    if demo_mode():
        return demo_receipt(bundle,loaded_assets)
    m=inspect(bundle)
    if loaded_assets is not None and loaded_assets!=m['assets']:raise ValueError('Python service did not load this candidate; explicit deployment window required')
    path=local_output(bundle)/'approved_elf.json';a=json.loads(path.read_text(encoding='utf-8'))
    if a.get('result')!='ELF_CANDIDATE_PASS' or a.get('app_id')!=APP_ID or a.get('release_id')!=m['release_id']:
        raise ValueError('Current reviewed user ELF required; never use legacy 24-source audit')
    if a['source_set_sha256']!=m['facts']['source_set_sha256'] or a['hardware_xsa_sha256']!=m['facts']['hardware_xsa_sha256'] or sha(a['elf']['path'])!=a['elf']['sha256']:
        raise ValueError('ELF/hardware changed after review')
    from gcs_release_elf import verify_sync,audit_identity
    sync,protected=verify_sync(local_output(bundle),m)
    if Path(a['elf']['path']).resolve()!=Path(sync['app'])/'Debug'/(APP_NAME+'.elf') or a['sync_sha256']!=sha(local_output(bundle)/'sync.json'):
        raise ValueError('Audit refers to another App/synchronization')
    data=Path(a['elf']['path']).read_bytes()
    audit_identity(data,m)
    protected.extend((record(Path(a['build_log']['path']),a['build_log']['path']),record(local_output(bundle)/'sync.json',str(local_output(bundle)/'sync.json'))))
    if protected!=a['protected_files']:raise ValueError('Audit protected-file coverage changed/incomplete')
    for row in a['protected_files']:
        if sha(row['path'])!=row['sha256']:raise ValueError('Reviewed App/platform/input changed: '+row['path'])
    return path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('inventory','prepare','inspect','audit-current'))
    p.add_argument('--bundle',type=Path,default=BUNDLE);a=p.parse_args()
    if a.command=='inventory':print(json.dumps(dict(app_id=APP_ID,sources=source_records(),assets=runtime_assets()),indent=2));return
    if a.command=='audit-current':print(audited_elf(a.bundle));return
    m=prepare(a.bundle) if a.command=='prepare' else inspect(a.bundle)
    print(json.dumps(dict(app_id=m['app_id'],release_id=m['release_id'],source_files=len(m['sources']),host_assets=len(m['assets']),result=m['result']),indent=2))
if __name__=='__main__':main()
