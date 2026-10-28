"""Pin official three-scene Train100/Test100/GT labels; no inference or board I/O."""
import hashlib
import json
from pathlib import Path
import sys
import zlib
import numpy as np
from scipy.io import loadmat
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'model')]
import board_models as m
from board_metrics import validate_labels
import scenes

def main():
    for scene in m.SCENES:
        spec=m.scene_spec(scene);palette=json.loads((ROOT/f'gcs/scenes/{scene}/palette.json').read_text(encoding='utf-8'))
        names=palette['classes'][1:]
        if scene=='longkou':names=[c['name_zh'] for c in json.loads((ROOT/'gcs/web/longkou_v2_classes.json').read_text(encoding='utf-8'))['classes']]
        if (palette['height'],palette['width'],len(names))!=(*spec['shape'],spec['classes']):raise ValueError('Palette/scene contract mismatch')
        train,test=scenes.split_paths(scene,100);paths=dict(train=train,test=test,gt=ROOT/'data/scenes'/scene/'gt_u8.bin')
        arrays={};files={}
        for name,path in paths.items():
            path=path.resolve();raw=path.read_bytes();relative=path.relative_to(ROOT)
            if name=='gt':arrays[name]=np.frombuffer(raw,dtype='u1').reshape(spec['shape'])
            else:
                values=[v for k,v in loadmat(path).items() if not k.startswith('__')]
                if len(values)!=1:raise ValueError('Ambiguous MAT labels')
                arrays[name]=values[0]
            files[name]=dict(path=relative.as_posix(),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),crc32=f'{zlib.crc32(raw):08x}')
        validate_labels(arrays['gt'],arrays['train'],arrays['test'],len(names))
        counts=[int((arrays['train']==i).sum()) for i in range(1,len(names)+1)]
        if counts!=[100]*len(names):raise ValueError('Official Train100 per-class count mismatch')
        result=dict(schema=2,scene=scene,shape=spec['shape'],classes=names,bands=270,label_base=1,
                    split=f'WHU-Hi {scene} official Train100/Test100',scope='FIXED_LABELS_NOT_MODEL_OR_BOARD_SCORE',
                    files=files,train_counts=counts,test_pixels=int((arrays['test']>0).sum()))
        out=ROOT/f'gcs/eval_{scene}.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(out)

if __name__=='__main__':main()
