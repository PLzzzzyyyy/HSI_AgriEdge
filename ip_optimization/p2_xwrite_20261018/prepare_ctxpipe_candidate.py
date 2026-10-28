"""Pipeline only the concrete CONTEXT multiply found on the critical path."""
import hashlib,json,shutil
from pathlib import Path
here=Path(__file__).resolve().parent;target=here.parent/'p2_ctxpipe_20261018'
if target.exists():raise SystemExit('Preserve prior candidate')
engine=here/'src/hls/m3_s2/s2_engine.cpp';text=engine.read_text(encoding='utf-8')
old='''            j.acc[n][h]=(j.c==0?(INT64_C(1)<<23):j.acc[n][h])+int64_t(s.attn[n][j.c])*vb[(h+rh)&3];'''
new='''            S2_ASSERT(s.attn[n][j.c]<=(1u<<24));
            const State<26> attention=State<26>(s.attn[n][j.c]);
            int64_t product=int64_t(attention)*vb[(h+rh)&3];
#pragma HLS BIND_OP variable=product op=mul impl=dsp latency=2
            j.acc[n][h]=(j.c==0?(INT64_C(1)<<23):j.acc[n][h])+product;'''
assert text.count(old)==1
target.mkdir()
for d in ('src','sim','tests'):shutil.copytree(here/d,target/d)
(target/'src/hls/m3_s2/s2_engine.cpp').write_text(text.replace(old,new),encoding='utf-8')
shutil.copy2(here/'run_hls_xc.tcl',target/'run_hls_xc.tcl')
runner=(here/'run_native_regressions.py').read_text(encoding='utf-8').replace('p2_xwrite_final','p2_ctxpipe_final')
(target/'run_native_regressions.py').write_text(runner,encoding='utf-8')
sources={str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ('src','sim','tests') for p in (target/d).rglob('*') if p.is_file()}
(target/'candidate_manifest.json').write_text(json.dumps(dict(parent=str(here),parent_engine_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),sources=sources),indent=2),encoding='utf-8')
print(target)
