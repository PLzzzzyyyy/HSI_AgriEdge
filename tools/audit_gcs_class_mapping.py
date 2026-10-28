"""Verified LongKou/v2 class order; no model or data inference at import."""
import hashlib,json,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EN=['Corn','Cotton','Sesame','Broad-leaf soybean','Narrow-leaf soybean','Rice','Water','Roads and houses','Mixed weed']
ZH=['玉米','棉花','芝麻','阔叶大豆','窄叶大豆','水稻','水体','道路与房屋','混合杂草']

def main():
    meta=dict(line.split('=',1) for line in (ROOT/'data/scenes/longkou/meta.txt').read_text(encoding='utf-8').splitlines() if '=' in line)
    ckpt=ROOT/'data/ckpt/longkou_unoverlapping_s0.pth';weights=ROOT/'data/scenes/longkou/weights/v2/weights_engine.bin'
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha(ckpt)==meta['ckpt_sha256']
    assert sha(weights)==meta['sha256:weights/v2/weights_engine.bin']
    assert zlib.crc32(weights.read_bytes())==0x27231983
    palette=json.loads((ROOT/'gcs/scenes/longkou/palette.json').read_text())
    assert palette['classes'][1:]==EN
    mapping=dict(scene='longkou',model='v2',wcrc='27231983',checkpoint_sha256=sha(ckpt),
        weights_sha256=sha(weights),source='model/scenes.py + train_scene.py(gt-1) + export_scene.py(classifier row order) + meta.txt hashes',
        scope='Model predicted classes, not verified ground truth or OA',
        classes=[dict(id=i,name_en=en,name_zh=zh,color=palette['colors'][i+1]) for i,(en,zh) in enumerate(zip(EN,ZH))])
    (ROOT/'gcs/web/longkou_v2_classes.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf-8')
    records={str(p.relative_to(ROOT)):sha(p) for p in [ckpt,weights,ROOT/'model/scenes.py',ROOT/'model/train_scene.py',ROOT/'model/export_scene.py',ROOT/'model/engine_ref.py',ROOT/'data/scenes/longkou/meta.txt']}
    (ROOT/'report/gcs_roi/20261010_formal/class_mapping_audit.json').write_text(json.dumps(dict(result='PASS',files=records,mapping=mapping),ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: LongKou/v2 CRC27231983 class order 0..8 verified, no inference')
if __name__=='__main__':main()
