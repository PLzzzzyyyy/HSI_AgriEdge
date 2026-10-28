"""Make two explicit write ports per existing x bank; no extra RAM or weights."""
import hashlib,json,shutil
from pathlib import Path
here=Path(__file__).resolve().parent;target=here.parent/'p2_xwrite_20261018'
if target.exists():raise SystemExit('Preserve prior candidate')
engine=here/'src/hls/m3_s2/s2_engine.cpp';text=engine.read_text(encoding='utf-8')
def replace(old,new):
    global text
    assert text.count(old)==1,old[:100]
    text=text.replace(old,new)
replace('struct StatsDelta {bool valid;int slot;int64_t sum[6];uint64_t square[6];};',
'''struct StatsDelta {bool valid;int slot;int64_t sum[6];uint64_t square[6];};
struct XWrite {bool valid;State<12> address;Act value;};
typedef XWrite XWrites[6][4];
static void request_xwrite(XWrites &writes,int slot,int p,int t,int32_t value) {
#pragma HLS INLINE
    XWrite &r=writes[t][p&3];S2_ASSERT(!r.valid);
    r.valid=true;r.address=slot*662+(p>>2);r.value=Act(value);
}
static void commit_xwrites(MainMemory &m,const XWrites &context,const XWrites &residual,const XWrites &input) {
#pragma HLS INLINE
    for(int t=0;t<6;++t)for(int b=0;b<4;++b) {
#pragma HLS UNROLL
        const XWrite c=context[t][b],r=residual[t][b],i=input[t][b];
        S2_ASSERT(unsigned(c.valid)+unsigned(r.valid)+unsigned(i.valid)<=2);
        const XWrite first=c.valid?c:r.valid?r:i;
        const XWrite second=c.valid&&r.valid?r:i;
        const bool both=(c.valid&&(r.valid||i.valid))||(r.valid&&i.valid);
        if(first.valid){S2_ASSERT(first.address>=0 && first.address<S2_P*662);m.x[t][b][first.address]=first.value;}
        if(both){S2_ASSERT(second.address>=0 && second.address<S2_P*662 && first.address!=second.address);m.x[t][b][second.address]=second.value;}
    }
}''')
replace('static bool ctx_step(MainMemory &m,Slot &s,Job &j,int64_t sum[24],\n                     StatsDelta &delta)',
        'static bool ctx_step(MainMemory &m,Slot &s,Job &j,int64_t sum[24],\n                     StatsDelta &delta,XWrites &writes)')
replace('m.x[j.h][b][j.slot*662+at]=Act(value[b]);',
        'XWrite &r=writes[j.h][b];S2_ASSERT(!r.valid);r.valid=true;r.address=j.slot*662+at;r.value=Act(value[b]);')
replace('static bool res_step(MainMemory &m,Slot &s,Job &j,CoreOffer &offer,CoreResponse &response,bool &valid,\n                     StatsDelta &delta)',
        'static bool res_step(MainMemory &m,Slot &s,Job &j,CoreOffer &offer,CoreResponse &response,bool &valid,\n                     StatsDelta &delta,XWrites &writes)')
replace('int32_t y=sat(v,S2_DB);put(m.x,j.slot,j.p,t,y);',
        'int32_t y=sat(v,S2_DB);request_xwrite(writes,j.slot,j.p,t,y);')
replace('unsigned count,unsigned flags,unsigned lo,\n                    StatsDelta &delta)',
        'unsigned count,unsigned flags,unsigned lo,\n                    StatsDelta &delta,XWrites &writes)')
replace('put(m.x,j.slot,p,t,v);','request_xwrite(writes,j.slot,p,t,v);')
replace('        const uint64_t w=input[s.id*(15876/lanes)+j.p];',
'''        const uint64_t w=input[s.id*(15876/lanes)+j.p];
        int32_t decoded[4];
#pragma HLS ARRAY_PARTITION variable=decoded complete
        for(int k=0;k<4;++k) {
#pragma HLS UNROLL
            decoded[k]=flags&S2_RAW?(k<2?sat(int32_t(w>>(32*k)),S2_DB):0):int32_t(quant(int16_t(w>>(16*k)),12-S2_DF));
        }''')
replace('                const int32_t v=flags&S2_RAW ? sat(int32_t(w>>(32*k)),S2_DB) : int32_t(quant(int16_t(w>>(16*k)),12-S2_DF));',
        '                const int32_t v=decoded[k];')
replace('        StatsDelta ctx_delta={},res_delta={},io_delta={};',
'''        StatsDelta ctx_delta={},res_delta={},io_delta={};
        XWrites ctx_writes={},res_writes={},io_writes={};
#pragma HLS ARRAY_PARTITION variable=ctx_writes complete dim=0
#pragma HLS ARRAY_PARTITION variable=res_writes complete dim=0
#pragma HLS ARRAY_PARTITION variable=io_writes complete dim=0''')
replace('ctx_step(mem,s,j,ctx_sum,ctx_delta)','ctx_step(mem,s,j,ctx_sum,ctx_delta,ctx_writes)')
replace('res_step(mem,s,j,unit_core,returned,returned_valid,res_delta)','res_step(mem,s,j,unit_core,returned,returned_valid,res_delta,res_writes)')
replace('io_step(mem,s,j,input,logits,classes,features,count,flags,lo,io_delta)',
        'io_step(mem,s,j,input,logits,classes,features,count,flags,lo,io_delta,io_writes)')
replace('        // Commit math responses after execution.',
'''        // The dispatcher budgets at most two x accesses per bank. Workers
        // publish independent write requests; no producer's value or write
        // completion feeds the next producer's write-enable control path.
        commit_xwrites(mem,ctx_writes,res_writes,io_writes);
        // Commit math responses after execution.''')
target.mkdir()
for d in ('src','sim'):shutil.copytree(here/d,target/d)
(target/'src/hls/m3_s2/s2_engine.cpp').write_text(text,encoding='utf-8')
shutil.copy2(here/'run_hls_xc.tcl',target/'run_hls_xc.tcl')
sources={str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ('src','sim') for p in (target/d).rglob('*') if p.is_file()}
(target/'candidate_manifest.json').write_text(json.dumps(dict(parent=str(here),parent_engine_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),sources=sources),indent=2),encoding='utf-8')
print(target)
