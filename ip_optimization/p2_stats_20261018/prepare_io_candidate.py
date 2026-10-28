"""Follow the concrete HLS input-load dependency warning in a separate candidate."""
import hashlib,json,shutil
from pathlib import Path
here=Path(__file__).resolve().parent
target=here.parent/'p2_stats_io_20261018'
if target.exists():raise SystemExit('Do not replace prior candidate')
old='''        for (int k=0;k<4;k++) {
#pragma HLS UNROLL
            if (k<lanes) {
                int32_t v=flags&S2_RAW ? sat(int32_t(w>>(32*k)),S2_DB) : int32_t(quant(int16_t(w>>(16*k)),12-S2_DF));
                put(m.x,j.slot,j.a,j.t,v);delta.valid=true;delta.slot=j.slot;delta.sum[j.t]+=v;delta.square[j.t]+=uint64_t(int64_t(v)*v);
                if (++j.t==6) {j.t=0;j.a++;}
            }
        }
'''
new='''        // An input word holds 2 or 4 consecutive token values, fewer than
        // six. Each token therefore has at most one write per word. Derive its
        // position from the original indices, not a chain of mutable indices.
        const int first=j.t,position=j.a,end=first+lanes;
        delta.valid=true;delta.slot=j.slot;
        for (int t=0;t<6;t++) {
#pragma HLS UNROLL
            const int k=t>=first?t-first:t+6-first;
            if (k<lanes) {
                const int p=position+(t<first?1:0);
                const int32_t v=flags&S2_RAW ? sat(int32_t(w>>(32*k)),S2_DB) : int32_t(quant(int16_t(w>>(16*k)),12-S2_DF));
                put(m.x,j.slot,p,t,v);
                delta.sum[t]=v;delta.square[t]=uint64_t(int64_t(v)*v);
            }
        }
        j.t=end>=6?end-6:end;j.a=position+(end>=6?1:0);
'''
engine=here/'src/hls/m3_s2/s2_engine.cpp'
text=engine.read_text(encoding='utf-8');assert text.count(old)==1
target.mkdir()
for directory in ('src','sim'):
    shutil.copytree(here/directory,target/directory)
(target/'src/hls/m3_s2/s2_engine.cpp').write_text(text.replace(old,new),encoding='utf-8')
shutil.copy2(here/'run_hls_xc.tcl',target/'run_hls_xc.tcl')
sources={str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ('src','sim') for p in (target/d).rglob('*') if p.is_file()}
(target/'candidate_manifest.json').write_text(json.dumps(dict(parent=str(here),parent_engine_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),sources=sources),indent=2),encoding='utf-8')
print(target)
