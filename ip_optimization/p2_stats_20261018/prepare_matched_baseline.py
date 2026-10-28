"""Copy the recorded legacy sources without editing the protected checkout."""
import hashlib,json,shutil
from pathlib import Path

here=Path(__file__).resolve().parent
manifest=json.loads((here/'baseline_manifest.json').read_text(encoding='utf-8'))
old=Path(manifest['source_root'])
target=here.parent/'p2_baseline_20261018'
if target.exists():raise SystemExit('Preserve existing baseline; no overwrite')
records={}
for rel,want in manifest['sources'].items():
    src=old/rel
    if hashlib.sha256(src.read_bytes()).hexdigest()!=want:raise SystemExit(f'Legacy changed: {rel}')
    records[rel]=want
records['sim/hls_tb/tb_m3_s2.cpp']=hashlib.sha256((old/'sim/hls_tb/tb_m3_s2.cpp').read_bytes()).hexdigest()
target.mkdir()
for rel in records:
    dest=target/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old/rel,dest)
(target/'baseline_manifest.json').write_text(json.dumps(dict(source_root=str(old),sources=records),indent=2),encoding='utf-8')
script=(here/'run_hls_xc.tcl').read_text(encoding='utf-8-sig').replace('csim_design -argv full\n','')
(target/'run_hls_xc.tcl').write_text(script,encoding='utf-8')
print(target)
