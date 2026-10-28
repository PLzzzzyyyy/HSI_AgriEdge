"""Export a paired kind0/int16 TTE2 candidate from an existing checkpoint.

Uses the existing exporters/numerical contract verbatim. No inference, training,
cube preprocessing, SD/device write, deployment or board activation is done.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'model')]
import board_models as m

def export_candidate(scene,checkpoint,tag,data_root=None):
    spec=m.scene_spec(scene);tag=m.valid_tag(tag);checkpoint=Path(checkpoint).resolve(strict=True)
    data_root=Path(data_root or ROOT/'data/scenes').resolve();parent=(data_root/scene/'weights').resolve()
    if not parent.is_relative_to(data_root):raise ValueError('Model output escapes data root')
    target=(parent/tag).resolve()
    if not target.is_relative_to(parent):raise ValueError('Model tag escapes weights directory')
    before=checkpoint.stat();digest=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    if target.exists():
        # Reproduction is idempotent only for a verified existing export from
        # the same checkpoint. Never fill in/overwrite a legacy user directory.
        old=m.load_candidate(data_root,scene,tag)
        if old['provenance'].get('checkpoint_sha256')!=digest:raise ValueError('Existing immutable model tag has another/missing provenance')
        return old
    parent.mkdir(parents=True,exist_ok=True)
    stage=(parent/('.stage_'+tag+'_'+uuid.uuid4().hex)).resolve()
    if not stage.is_relative_to(parent):raise ValueError('Staging path escapes model output directory')
    stage.mkdir()
    from engine_ref import Engine
    from export_scene import write_weights,write_engine
    engine=Engine(str(checkpoint),spec['classes'],num=16)
    write_weights(engine.net,stage);write_engine(engine,stage,'weights_engine.bin')
    names=[*(name for name,_ in m.part_files(scene)),'weights_engine.bin']
    files={name:(stage/name).read_bytes() for name in names}
    companion=b''.join(files[name] for name,_ in m.part_files(scene));m.validate_pair(scene,companion,files['weights_engine.bin'])
    after=checkpoint.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or hashlib.sha256(checkpoint.read_bytes()).hexdigest()!=digest:
        raise ValueError('Checkpoint changed during export; staging retained, not registered')
    manifest=dict(schema=1,scene=scene,tag=tag,checkpoint_sha256=digest,checkpoint=str(checkpoint),input_contract=spec,
                  files={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()},
                  source_scope='EXISTING_CHECKPOINT_PAIRED_EXPORT_ONLY_NOT_TRAINING_EVALUATION_OR_BOARD_ACCEPTANCE',
                  exporter_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                    ('model/export_board_candidate.py','model/export_scene.py','model/engine_ref.py','model/fixed_point_sim.py','model/quant.py','gcs/board_models.py')})
    (stage/'board_model.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for path in [*(stage/name for name in names),stage/'board_model.json']:
        with path.open('r+b') as f:f.flush();os.fsync(f.fileno())
    # Both absolute directory targets have been resolved/checked above. No
    # recursive delete or shell composition; rename cannot replace an existing
    # model folder on Windows. Aborted hidden stages remain for diagnosis.
    if target.exists():raise ValueError('Model tag appeared during export; do not overwrite')
    stage.rename(target)
    return m.load_candidate(data_root,scene,tag)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scene',required=True,choices=m.SCENES)
    p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--tag',required=True);p.add_argument('--report',type=Path)
    args=p.parse_args();result=export_candidate(args.scene,args.checkpoint,args.tag);text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(text+'\n',encoding='utf-8')
    print(text)

if __name__=='__main__':main()
