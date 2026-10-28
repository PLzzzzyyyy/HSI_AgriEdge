"""Board model/input contracts, NOT a PC inference source.

Local verified files only establish an upload candidate. INFO, WCOMMIT and
actual task receipts establish different, explicitly separate board facts.
Wire layouts are the existing protocol.md v1 (not the legacy v0 source).
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

import numpy as np

SCENES = ('longkou', 'honghu', 'hanchuan')
_SHAPES = ((550,400,9), (940,475,22), (1217,303,16))
_CUBE_CRCS = ('bf3b60c5','857ba1a6','66ed4ccc') # same pinned input identities as private roi_models.cpp
ENGINE_BYTES = 480576
MAX_ENTRIES = 48
WCHUNK, WBEGIN, WCOMMIT, WACT = 0x10, 0x11, 0x12, 0x13
CHUNK_BYTES = 1384
BEGIN = struct.Struct('<BBHII16s')
CHUNK = struct.Struct('<BBHIII')
ACT = struct.Struct('<BBHI')
TAG = re.compile(r'[a-z0-9][a-z0-9_-]{0,14}\Z')


def scene_spec(scene):
    if type(scene) is int and 0 <= scene < len(SCENES):scene = SCENES[scene]
    if type(scene) is not str or scene not in SCENES:raise ValueError('Unknown board scene')
    h,w,n = _SHAPES[SCENES.index(scene)]
    return dict(scene=scene, id=SCENES.index(scene), shape=[h,w], classes=n,
                bands=270, pad=3, band_drop=[270,271,272,273] if scene=='hanchuan' else [],
                cube_bytes=(h+6)*(w+6)*270*4, cube_crc32=_CUBE_CRCS[SCENES.index(scene)],class_base=0, confidence_frac=16)


def valid_tag(tag):
    if type(tag) is not str or not TAG.fullmatch(tag):raise ValueError('Invalid model tag/path')
    return tag


def task_identity(value):
    """Validate a persisted task identity, not a claim of local/board presence."""
    if not isinstance(value,dict):raise ValueError('Missing task model identity')
    spec=scene_spec(value.get('scene'));tag=valid_tag(value.get('model'))
    crc=value.get('wcrc')
    if type(crc) is not str or not re.fullmatch('[0-9a-f]{8}',crc) or int(crc,16)==0:
        raise ValueError('Invalid task model CRC')
    if value.get('shape')!=spec['shape'] or type(value.get('classes')) is not int or value['classes']!=spec['classes'] or type(value.get('kind')) is not int or value['kind']!=1:
        raise ValueError('Task scene/model shape/classes contract differs')
    return dict(scene=spec['scene'],model=tag,wcrc=crc,shape=spec['shape'],classes=spec['classes'],kind=1)


def candidate_identity(candidate):
    if not isinstance(candidate,dict):raise ValueError('Missing candidate identity')
    spec=scene_spec(candidate['scene'])
    parts=candidate.get('parts')
    if not isinstance(parts,list) or len(parts)!=2:raise ValueError('Candidate paired descriptors missing')
    for kind,part in enumerate(parts):
        size=ENGINE_BYTES if kind else sum(n for _,n in part_files(spec['scene']))
        if not isinstance(part,dict) or type(part.get('kind')) is not int or part['kind']!=kind or type(part.get('bytes')) is not int or part['bytes']!=size:
            raise ValueError('Candidate part identity/size mismatch')
        crc,sha=part.get('crc32'),part.get('sha256')
        if type(crc) is not str or not re.fullmatch('[0-9a-f]{8}',crc) or not int(crc,16) or type(sha) is not str or not re.fullmatch('[0-9a-f]{64}',sha):
            raise ValueError('Invalid candidate part CRC/SHA256')
    if candidate.get('wcrc')!=parts[1]['crc32']:raise ValueError('Candidate activation CRC differs from engine part')
    return task_identity(dict(scene=candidate['scene'],model=candidate['tag'],wcrc=candidate['wcrc'],
                              shape=spec['shape'],classes=spec['classes'],kind=1))


def decode_tag(raw):
    """v1 tag is a NUL-terminated 15-byte identifier, with all tail bytes zero."""
    if len(raw)!=16 or b'\0' not in raw:raise ValueError('Invalid model tag padding')
    head,tail=raw.split(b'\0',1)
    if any(tail):raise ValueError('Invalid model tag padding')
    return valid_tag(head.decode('ascii'))


def part_files(scene):
    n=scene_spec(scene)['classes']
    return (('weights_all.bin',289344),('cls_token.bin',10584),('pos_embed.bin',63504),
            ('classifier_w.bin',n*2646*4),('classifier_b.bin',n*4))


def validate_package(scene, kind, raw):
    n=scene_spec(scene)['classes']
    if type(kind) is not int or kind not in (0,1):raise ValueError('Only kind0 / int16 kind1 are supported')
    expected=sum(size for _,size in part_files(scene)) if kind==0 else ENGINE_BYTES
    if len(raw)!=expected:raise ValueError('Package byte size differs from scene/kind')
    if kind==0:
        if not np.all(np.isfinite(np.frombuffer(raw,dtype='<f4',offset=289344))):
            raise ValueError('Nonfinite companion float')
        return
    if struct.unpack_from('<4I',raw)!=(0x32455454,2,n,16):raise ValueError('TTE2 magic/version/classes/bit width')
    spans=[(16,32),(32+n,64),(63568,63616),(63616+n*4,63744)]
    spans.extend((63744+c*5312+(5292 if c<n else 0),63744+(c+1)*5312) for c in range(24))
    if any(any(raw[a:b]) for a,b in spans):raise ValueError('TTE2 reserved/unused/padding bytes')


def validate_pair(scene, companion, engine):
    validate_package(scene,0,companion);validate_package(scene,1,engine)
    if companion[:289344]!=engine[191232:]:raise ValueError('Paired projection factors differ')
    cls=np.frombuffer(companion,dtype='<f4',count=2646,offset=289344).astype(np.float64)
    pos=np.frombuffer(companion,dtype='<f4',count=15876,offset=299928).astype(np.float64).reshape(2646,6).copy()
    pos[:,0]+=cls
    emb=np.floor(pos*2**24+0.5)
    if np.any(emb < -2**31) or np.any(emb >= 2**31) or not np.array_equal(
            emb.astype('<i4').ravel(),np.frombuffer(engine,dtype='<i4',count=15876,offset=64)):
        raise ValueError('Paired cls/pos embedding differs')


def _read_parts(root, scene, tag):
    spec=scene_spec(scene);tag=valid_tag(tag);root=Path(root).resolve()
    folder=(root/scene/'weights'/tag).resolve()
    if not folder.is_relative_to(root):raise ValueError('Model path escapes local data root')
    manifest=folder/'board_model.json'
    if manifest.exists():
        m=json.loads(manifest.read_text(encoding='utf-8'))
        if (m.get('schema'),m.get('scene'),m.get('tag'))!=(1,scene,tag) or not re.fullmatch('[0-9a-f]{64}',str(m.get('checkpoint_sha256',''))):
            raise ValueError('Invalid candidate export provenance')
        hashes=m['files'];source=dict(path=str(manifest),sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                                      checkpoint_sha256=m['checkpoint_sha256'])
    else:
        path=root/scene/'meta.txt'
        kv=dict(line.split('=',1) for line in path.read_text(encoding='utf-8-sig').splitlines() if '=' in line)
        if [int(kv[k]) for k in ('H','W','classes','bands','pad')]!=[*spec['shape'],spec['classes'],270,3]:
            raise ValueError('Local input/classes contract differs')
        hashes={name:kv.get(f'sha256:weights/{tag}/{name}') for name in [*(n for n,_ in part_files(scene)),'weights_engine.bin']}
        source=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    files={}
    for name in [*(n for n,_ in part_files(scene)),'weights_engine.bin']:
        path=(folder/name).resolve()
        if not path.is_relative_to(folder):raise ValueError('Model file escapes version folder')
        before=path.stat();raw=path.read_bytes();after=path.stat()
        if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise ValueError('Model changed during verification')
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=hashes.get(name):raise ValueError('Unregistered/mismatched model SHA256: '+name)
        files[name]=raw
    parts=(b''.join(files[n] for n,_ in part_files(scene)),files['weights_engine.bin'])
    validate_pair(scene,*parts)
    return spec,source,parts


def load_candidate(root, scene, tag):
    spec,source,parts=_read_parts(root,scene,tag)
    descriptors=[dict(kind=k,bytes=len(p),crc32=f'{zlib.crc32(p):08x}',sha256=hashlib.sha256(p).hexdigest()) for k,p in enumerate(parts)]
    if any(p['crc32']=='00000000' for p in descriptors):raise ValueError('Zero CRC cannot identify a v1 model')
    return dict(scene=scene,tag=tag,wcrc=descriptors[1]['crc32'],input_contract=spec,parts=descriptors,
                provenance=source,board_registered=False,board_persisted=None,board_activated=None,
                scope='LOCAL_VERIFIED_UPLOAD_CANDIDATE_NOT_BOARD_REGISTRATION_OR_ACCEPTANCE')


def package_parts(root, scene, tag):
    return _read_parts(root,scene,tag)[2]


def registered(candidate, entries):
    """Both kinds must be uniquely observed under the exact scene/tag/CRC."""
    scene=scene_spec(candidate['scene'])['id'];tag=candidate['tag']
    for part in candidate['parts']:
        matches=[e for e in entries if e['scene']==scene and e['kind']==part['kind'] and e['wcrc']==part['crc32']]
        if len(matches)!=1 or matches[0]['tag']!=tag or matches[0]['bytes']!=part['bytes']:return False
    return True


def registry_summary(root, versions):
    """Unavailable versions remain visible with a reason; no automatic export."""
    result=[]
    for scene in SCENES:
        for version in versions.get(scene,[]):
            tag=version.get('pkg') or version['id']
            try:
                item=load_candidate(root,scene,tag)
                item.update(version=version['id'],available=True,error=None)
            except (OSError,KeyError,TypeError,ValueError) as exc:
                item=dict(scene=scene,version=version['id'],tag=tag,available=False,error=str(exc),
                          board_registered=False,board_persisted=None,board_activated=None)
            result.append(item)
    return result
