"""Prepare a LOCAL standalone boot/data bundle AFTER the user's new App Build.

Does not build App/platform, run bootgen, write a card or access a device.
Old ELF/XSA and missing provenance fail closed. New journal files are installed
only for a NEW card installation; never copy initial journals over a used card.
"""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,shutil,struct,zipfile
from check_gcs_hardware import system_ready
import gcs_release
ROOT=Path(__file__).resolve().parents[1]
APP_ID='gcs_r1_abi4'
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        while b:=f.read(1<<20):h.update(b)
    return h.hexdigest()
def elf_machine(p,expected):
    b=Path(p).read_bytes()
    if b[:4]!=b'\x7fELF' or b[5]!=1 or struct.unpack_from('<H',b,18)[0]!=expected:raise ValueError('Wrong ELF architecture: '+str(p))
def relative(path):
    p=PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts or not p.parts or ':' in path or '\\' in path:raise ValueError('Unsafe SD destination')
    return p
def prepare(a):
    out=a.out.resolve()
    if not out.is_relative_to((ROOT/'build/host').resolve()) or out.exists():raise ValueError('New local build/host directory only, never a card')
    hw=system_ready();audit=json.loads(a.elf_audit.read_text(encoding='utf-8'))
    current=json.loads(gcs_release.audited_elf().read_text(encoding='utf-8'))
    if audit!=current:raise ValueError('Boot bundle requires the registered current complete release audit')
    if audit.get('result')!='ELF_CANDIDATE_PASS' or audit.get('app_id')!=APP_ID or audit.get('hardware_xsa_sha256')!=hw['xsa']['sha256']:
        raise ValueError('Current App ELF audit/hardware binding required; old audit is not valid')
    app=Path(audit['elf']['path'])
    if sha(app)!=audit['elf']['sha256'] or ('app='+APP_ID).encode() not in app.read_bytes():raise ValueError('App ELF changed/old revision')
    if sha(a.platform_xsa)!=hw['xsa']['sha256']:raise ValueError('FSBL/PMU platform XSA differs from new system')
    if not a.platform_build_log.is_file() or not a.platform_build_log.stat().st_size:raise ValueError('Preserve user platform Build log')
    sync=json.loads((gcs_release.BUNDLE/'sync.json').read_text(encoding='utf-8'));platform=sync['platform']
    if sha(a.platform_build_log)!=platform['build_log']['sha256']:raise ValueError('Wrong platform generation log')
    for role,path in (('fsbl',a.fsbl),('pmufw',a.pmufw)):
        expected={row['sha256'] for row in platform['files'] if Path(row['path']).suffix=='.elf' and role in Path(row['path']).name.lower()}
        if sha(path) not in expected:raise ValueError('Boot component was not generated on the new checked platform: '+role)
    elf_machine(app,183);elf_machine(a.fsbl,183);elf_machine(a.pmufw,189)
    data=json.loads(a.data_inventory.read_text(encoding='utf-8'))
    if not data.get('local_data_verified') or data.get('errors') or not data.get('files'):raise ValueError('Missing verified local input/model inventory')
    provision=json.loads((a.provision/'provision.json').read_text(encoding='utf-8'))
    if provision.get('format')!='gcs-boot-journal-v1' or provision.get('app_abi')!=4:raise ValueError('Missing new installation journal')
    files=[];destinations=set()
    for item in data['files']:
        rel=relative(item['destination'])
        if rel.parts[0]!='scenes' or str(rel) in destinations:raise ValueError('Invalid data destination')
        p=Path(item['source']);destinations.add(str(rel))
        if p.stat().st_size!=item['bytes'] or sha(p)!=item['sha256']:raise ValueError('Data inventory drift: '+str(p))
        files.append((p,Path('sd_card')/str(rel)))
    for item in provision['files']:
        rel=relative(item['destination']);p=a.provision/str(rel)
        if str(rel) not in ('boot/jrn0.bin','boot/jrn1.bin') or sha(p)!=item['sha256'] or p.stat().st_size!=64:raise ValueError('Journal provision drift')
        files.append((p,Path('sd_card')/str(rel)))
    if {str(relative(x['destination'])) for x in provision['files']}!={'boot/jrn0.bin','boot/jrn1.bin'}:raise ValueError('Both boot slots required')
    out.mkdir(parents=True,exist_ok=False);components=out/'components';components.mkdir()
    for p,name in ((app,'app.elf'),(a.fsbl,'fsbl.elf'),(a.pmufw,'pmufw.elf')):shutil.copyfile(p,components/name)
    with zipfile.ZipFile(ROOT/hw['xsa']['path']) as z:(components/'design.bit').write_bytes(z.read(hw['xsa']['bit_member']))
    shutil.copyfile(ROOT/'board/boot/gcs_round1.bif.in',components/'boot.bif')
    for source,destination in files:
        dst=out/destination;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dst)
        if sha(dst)!=sha(source):raise ValueError('Local copy verification failed')
    manifest=dict(scope='LOCAL_FILES_ONLY_USER_BOOTGEN_SD_COPY_AND_COLD_BOOT_REQUIRED',app_id=APP_ID,hardware=hw['xsa'],
        user_elf_audit_sha256=sha(a.elf_audit),platform_build_log=dict(path=str(a.platform_build_log.resolve()),sha256=sha(a.platform_build_log)),
        provision=provision,files=[dict(path=p.relative_to(out).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(out.rglob('*')) if p.is_file()],
        boot_image_created=False,sd_written=False,hardware_acceptance=False)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    command='& D:/xilinx/Vitis/2020.2/bin/bootgen.bat -arch zynqmp -image boot.bif -o ../sd_card/BOOT.BIN\n'
    (out/'user_bootgen.txt').write_text('Run ONLY after reviewing all hashes, from components/. No overwrite of an existing BOOT.BIN.\n'+command+
        'Preserve bootgen stdout/stderr and SHA256 of BOOT.BIN. Copy sd_card contents only after confirming the correct physical media.\n'+
        'WARNING: initial boot/jrn*.bin are for a NEW installation only. Never overwrite used journals or clone/restore the card.\n',encoding='utf-8')
    return manifest
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('elf-audit','fsbl','pmufw','platform-xsa','platform-build-log','data-inventory','provision','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=prepare(a);print(json.dumps(dict(scope=r['scope'],files=len(r['files']),out=str(a.out)),indent=2))
