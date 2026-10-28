"""Explicit LOCAL initial SD journal files, not a card writer or runtime repair."""
from pathlib import Path
import argparse,hashlib,json,secrets,struct,zlib
ROOT=Path(__file__).resolve().parents[1]
def record(slot,base,generation,nonce):
    if slot not in (0,1) or not 0<base<2**32 or not 0<=generation<2**32 or base+generation>=2**32 or not 0<nonce<2**64:
        raise ValueError('Invalid boot provision fields')
    fields=[0x34444942,1,base,generation,base+generation,slot,nonce&0xffffffff,nonce>>32,4,0,0,0,0,0]
    raw=struct.pack('<14I',*fields);crc=zlib.crc32(raw)
    return raw+struct.pack('<II',crc,crc^0xffffffff)
def provision(out):
    out=Path(out).resolve()
    if not out.is_relative_to((ROOT/'build/host').resolve()):raise ValueError('Only a NEW directory below build/host; never removable media')
    out.mkdir(parents=True,exist_ok=False)
    base=secrets.randbelow(0x7ffffffe)+1;nonce=secrets.randbits(64)
    if not nonce:raise ValueError('Zero nonce; no fallback')
    (out/'boot').mkdir();files=[]
    for slot in (0,1):
        rel=f'boot/jrn{slot}.bin';raw=record(slot,base,0,nonce);(out/rel).write_bytes(raw)
        files.append(dict(destination=rel,bytes=64,sha256=hashlib.sha256(raw).hexdigest()))
    value=dict(format='gcs-boot-journal-v1',app_abi=4,base=f'{base:08x}',nonce=f'{nonce:016x}',files=files,
        scope='LOCAL_PROVISION_ONLY_NOT_SD_OR_COLD_BOOT_EVIDENCE',warning='Install once; never restore these initial journals over used media. Cloning/rollback is not protected by FAT. New installation and preserve old evidence required for replacement.')
    (out/'provision.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');return value
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--new-installation',action='store_true',required=True)
    a=p.parse_args();print(json.dumps(provision(a.out),indent=2))
