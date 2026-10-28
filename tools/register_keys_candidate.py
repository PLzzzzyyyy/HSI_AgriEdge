"""Register a built local key candidate; prepare an atomic firmware set, not deployment."""
import json
import shutil
import sys
from pathlib import Path
import gcs_release as release
import gcs_release_elf as elf_audit
ROOT=release.ROOT
BUNDLE=ROOT/'build/host/gcs_keys_20261018_v1'
ELF=Path('D:/FPGA.GAME/dpfix/gcs_keys_20261018/build/gcs_keys_20261018.elf')
HARDWARE=ROOT/'build/keys_eco_20261018_v4'
def main():
    path=BUNDLE/'manifest.json';manifest=json.loads(path.read_text())
    if release.runtime_assets()!=manifest['assets'] or release.source_records()!=manifest['sources']:
        raise ValueError('Candidate source/asset drift')
    audit=elf_audit.audit_identity(ELF.read_bytes(),manifest)
    (BUNDLE/'elf_identity_audit.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf-8')
    target=ROOT/'firmware/keys_20261018'
    if target.exists():raise ValueError('Retain previous firmware set')
    target.mkdir()
    pairs={'tt_gcs_keys.bit':HARDWARE/'tt_gcs_keys.bit','tt_gcs_keys.xsa':HARDWARE/'tt_gcs_keys.xsa',
           'fsbl_a53.elf':ROOT/'firmware/fsbl_a53.elf','gcs_keys.elf':ELF}
    for name,source in pairs.items():shutil.copy2(source,target/name)
    manifest['local_demo_elf']=release.record(target/'gcs_keys.elf')
    path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    prepared=dict(release_id=manifest['release_id'],bundle=BUNDLE.relative_to(ROOT).as_posix(),
                  files={name:release.sha(target/name) for name in pairs},state='PREPARED_NOT_DEPLOYMENT')
    (target/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(prepared,indent=2))
if __name__=='__main__':main()
