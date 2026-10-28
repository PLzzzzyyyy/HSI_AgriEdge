"""Separate entry-state command arbitration from producer data paths."""
import hashlib,json,re,shutil
from pathlib import Path
here=Path(__file__).resolve().parent
target=here.parent/'p2_arbiter_20261018'
if target.exists():raise SystemExit('Preserve prior candidate')
engine=here/'src/hls/m3_s2/s2_engine.cpp';text=engine.read_text(encoding='utf-8')
begin=text.index('        for (int u=0;u<8;u++) {\n#pragma HLS UNROLL\n            Job &j=jobs[u];')
end=text.index('        // Commit math responses after execution.',begin)
block=text[begin:end]
assert block.count('if (pause(rng))')==1
block=re.sub(r'\bcore\b','unit_core',block)
block=block.replace('if (pause(rng)) {if (j.stage==IO_OUT) meta[8]++;continue;}',
                    'if (!execute[u]) {if (j.stage==IO_OUT) meta[8]++;continue;}\n            CoreOffer unit_core={};unit_core.ready=core.ready && core_winner==u;')
block=block.replace('            j.check_bounds();',
                    '            if(unit_core.valid) {S2_ASSERT(!core.valid);core.item=unit_core.item;core.valid=true;}\n            j.check_bounds();')
prefix='''        // Request eligibility uses entry state only. Preserve the original
        // NORMAL > PROJECT > COPY > RESIDUAL priority and native pause order,
        // without feeding an earlier producer's arithmetic into later ready.
        bool execute[8];
#pragma HLS ARRAY_PARTITION variable=execute complete
        int core_winner=-1;
        for(int u=0;u<8;++u) {
#pragma HLS UNROLL
            const Job &j=jobs[u];
            execute[u]=j.active && !pause(rng);
            const bool wants=u==NORMAL?j.phase==2:u==PROJECT?!j.have:
                (u==COPY||u==RESIDUAL)?(j.phase==1||!j.have):false;
            if(execute[u] && wants && core_winner<0)core_winner=u;
        }
'''
target.mkdir()
for d in ('src','sim','tests'):shutil.copytree(here/d,target/d)
(target/'src/hls/m3_s2/s2_engine.cpp').write_text(text[:begin]+prefix+block+text[end:],encoding='utf-8')
shutil.copy2(here/'run_hls_xc.tcl',target/'run_hls_xc.tcl')
sources={str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ('src','sim','tests') for p in (target/d).rglob('*') if p.is_file()}
(target/'candidate_manifest.json').write_text(json.dumps(dict(parent=str(here),parent_engine_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),sources=sources),indent=2),encoding='utf-8')
print(target)
