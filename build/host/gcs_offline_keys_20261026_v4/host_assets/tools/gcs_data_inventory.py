"""Verify local model/input files and describe their FUTURE SD destinations.

No SD enumeration/mount/write, bootgen, Vitis action, copy/sync or deployment.
Only an explicitly named NEW local JSON report is written. BOOT.BIN/standalone
identity and all board acceptance facts stay missing/pending, never inferred.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'gcs'))
import board_models as m
from scene_input import InputReader

SELECTION={'longkou':['v2','v1_board','hold3','v3_board','v3ft50_board'],'honghu':['v1'],'hanchuan':['v1']}

def inventory(data_root,selection=None):
    root=Path(data_root).resolve();selection=SELECTION if selection is None else selection
    if not isinstance(selection,dict) or not selection:raise ValueError('Explicit nonempty scene/model selection required')
    reader=InputReader(root);files=[];models=[];inputs=[];errors=[]
    for scene,tags in selection.items():
        spec=m.scene_spec(scene)
        if not isinstance(tags,list) or not tags or len(set(tags))!=len(tags):raise ValueError('Model tag list must be nonempty and unique')
        for tag in tags:m.valid_tag(tag)
        try:
            if not (root/scene/'cube_f32.bin').resolve().is_relative_to(root):raise ValueError('Cube outside selected local data root')
            path,stamp,dims,provenance=reader._manifest(scene)
            if tuple(dims)!=(*spec['shape'],3,270) or provenance['bytes']!=spec['cube_bytes'] or provenance['crc32']!=spec['cube_crc32']:
                raise ValueError('Verified local input differs from the board scene contract')
            if not path.resolve().is_relative_to(root):raise ValueError('Cube outside selected local data root')
            destination=f'scenes/{scene}/cube_f32.bin'
            entry=dict(source=str(path.resolve()),destination=destination,bytes=provenance['bytes'],sha256=provenance['sha256'],
                       crc32=provenance['crc32'],role='input_cube',scene=scene,scope='LOCAL_FILE_NOT_SD_READBACK')
            metadata_sha=hashlib.sha256(path.with_name('meta.txt').read_bytes()).hexdigest()
            if stamp!=(reader._stamp(path.with_name('meta.txt')),reader._stamp(path)):raise ValueError('Input changed while inventory was being recorded')
            files.append(entry);inputs.append(dict(scene=scene,contract=spec,provenance=provenance,metadata_sha256=metadata_sha))
        except (ValueError,OSError,KeyError,TypeError) as exc:errors.append(dict(scene=scene,role='input_cube',error=str(exc)))
        for tag in tags:
            try:
                candidate=m.load_candidate(root,scene,tag);parts=m.package_parts(root,scene,tag)
                for expected,raw in zip(candidate['parts'],parts):
                    if (len(raw),f'{zlib.crc32(raw):08x}',hashlib.sha256(raw).hexdigest())!=(expected['bytes'],expected['crc32'],expected['sha256']):
                        raise ValueError('Model changed between candidate and inventory reads')
                offset=0
                for name,size in [*m.part_files(scene),('weights_engine.bin',m.ENGINE_BYTES)]:
                    kind=int(name=='weights_engine.bin');raw=parts[1] if kind else parts[0][offset:offset+size]
                    if not kind:offset+=size
                    if len(raw)!=size:raise ValueError('Invalid split package length')
                    files.append(dict(source=str((root/scene/'weights'/tag/name).resolve()),destination=f'scenes/{scene}/weights/{tag}/{name}',
                        bytes=size,sha256=hashlib.sha256(raw).hexdigest(),crc32=f'{zlib.crc32(raw):08x}',role='model_kind'+str(kind),scene=scene,tag=tag,
                        scope='LOCAL_FILE_NOT_SD_READBACK'))
                models.append(candidate)
            except (ValueError,OSError,KeyError,TypeError) as exc:errors.append(dict(scene=scene,tag=tag,role='model_pair',error=str(exc)))
    destinations=[f['destination'] for f in files]
    if len(set(destinations))!=len(destinations):raise ValueError('Duplicate planned SD destination')
    return dict(schema=1,created=datetime.now().isoformat(),local_data_root=str(root),selection=selection,
        scope='READ_ONLY_LOCAL_DATA_INVENTORY_NOT_SD_CONTENTS_BOOT_IMAGE_DEPLOYMENT_OR_BOARD_ACCEPTANCE',
        local_data_verified=not errors,input_contracts=inputs,models=models,files=files,errors=errors,
        total_planned_bytes=sum(f['bytes'] for f in files),sd_present=None,sd_persisted=None,board_activated=None,
        boot_image_created=False,standalone_identity_ready=False,first_release_complete=False,
        pending=['Real SD journal reservation and standalone cold boot','Real PL attention and internal timing evidence',
                 'Final source/ELF/IP/XSA acceptance gate','User Build/download/SD-copy/cold-start actions',
                 'Actual board SD readback and power-cycle persistence','Full incremental task/DP/accuracy/timing acceptance'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-root',type=Path,default=ROOT/'data/scenes')
    p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    out=args.out.resolve()
    if not out.is_relative_to((ROOT/'build/host').resolve()):raise ValueError('Inventory report must be a new file under build/host')
    if out.exists():raise ValueError('Do not overwrite an earlier inventory receipt')
    result=inventory(args.data_root);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({k:result[k] for k in ('local_data_verified','total_planned_bytes','scope','errors')},ensure_ascii=False))
    return 0 if result['local_data_verified'] else 1

if __name__=='__main__':raise SystemExit(main())
