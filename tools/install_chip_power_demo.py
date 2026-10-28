"""Install the already built matching local demo, retaining the old firmware set."""
import json
import argparse
from pathlib import Path
import shutil
import gcs_release as r
from gcs_release_elf import audit_identity

def main():
    root=r.ROOT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,default=root/'build/host/gcs_chip_power_20261021_v1')
    parser.add_argument('--elf',type=Path,default=Path('D:/FPGA.GAME/dpfix/gcs_chip_power_20261021/build/gcs_chip_power_20261021.elf'))
    parser.add_argument('--backup',type=Path,default=root/'firmware/keys_20261018_before_chip_power_20261021')
    parser.add_argument('--installed-elf',type=Path,default=root/'firmware/gcs_chip_power_20261021.elf')
    parser.add_argument('--report-dir',type=Path,default=root/'report/chip_power_20261021')
    parser.add_argument('--scope',default='Temperature-conditioned Vivado chip power estimate and board wall-time estimated energy; not measured board power. Stable inference bitstream unchanged.')
    args=parser.parse_args()
    bundle=args.bundle.resolve();elf=args.elf.resolve();backup=args.backup.resolve()
    deployed=args.installed_elf.resolve();report=args.report_dir.resolve()
    for path in (bundle,backup,deployed,report):
        if not path.is_relative_to(root):raise ValueError('Output must remain in project')
    manifest=json.loads((bundle/'manifest.json').read_text())
    if r.runtime_assets()!=manifest['assets'] or r.source_records()!=manifest['sources']:raise ValueError('Candidate drift')
    identity=audit_identity(elf.read_bytes(),manifest)
    keydir=root/'firmware/keys_20261018'
    old=json.loads((keydir/'deployment.json').read_text())
    for name,digest in old['files'].items():
        if r.sha(keydir/name)!=digest:raise ValueError('Existing firmware drift '+name)
    profile=json.loads((root/'gcs/chip_power_profile.json').read_text())
    if profile['hardware_xsa_sha256']!=r.sha(keydir/'tt_gcs_keys.xsa') or profile['bit_sha256']!=r.sha(keydir/'tt_gcs_keys.bit'):raise ValueError('Power model hardware mismatch')
    if backup.exists():raise ValueError('Do not overwrite firmware backup')
    if deployed.exists():raise ValueError('Do not overwrite an installed ELF archive')
    shutil.copytree(keydir,backup)
    shutil.copy2(elf,deployed)
    manifest['scope']=args.scope
    manifest['local_demo_elf']=r.record(deployed)
    (bundle/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    shutil.copy2(deployed,keydir/'gcs_keys.elf')
    new=dict(old,release_id=manifest['release_id'],bundle=bundle.relative_to(root).as_posix(),
             backup=backup.relative_to(root).as_posix(),state='INSTALLED_PENDING_BOARD_VERIFICATION',
             verification=(report/'live_verification.json').relative_to(root).as_posix(),
             power_model_id=profile['model_id'])
    new['files']={name:r.sha(keydir/name) for name in old['files']}
    for key in ('boot','previous_boot','start_verification'):new.pop(key,None)
    (keydir/'deployment.json').write_text(json.dumps(new,indent=2)+'\n',encoding='utf-8')
    evidence=dict(release_id=manifest['release_id'],model_id=profile['model_id'],elf=manifest['local_demo_elf'],
                  identity=identity,backup=str(backup),inference_bitstream_unchanged=True)
    report.mkdir(parents=True,exist_ok=True)
    (report/'install.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(evidence,indent=2))

if __name__=='__main__':main()
