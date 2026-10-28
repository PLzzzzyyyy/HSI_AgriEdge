"""Checked ABI4 RTL instrumentation in NEW candidate only; no old IP/device."""
from pathlib import Path
import argparse,hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'build/hls/optimization_build/tt_engine_gcs_r1_abi4'
EXPORT_BUILD=ROOT/'build/hls/optimization_build/tt_engine_gcs_r1_abi4_export'
FINAL_IP=ROOT/'build/hls/optimization_build/tt_engine_gcs_r1_abi4_ip'
TEMPLATE=ROOT/'src/rtl/tt_gcs_cycle_counter.v'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def verify_binding(text,template):
    required={'// GCS_ABI4_REAL_CYCLES':1,'wire [31:0] tt_gcs_cycles;':1,
        '.cycles(tt_gcs_cycles)':2,'.cycles_ap_vld(ap_done)':1,
        '.accepted(ap_CS_fsm_state1 && ap_start), .done(ap_done), .cycles(tt_gcs_cycles)':1,
        'tt_gcs_cycle_counter tt_gcs_measure (':1,'.clk(ap_clk), .resetn(ap_rst_n)':1}
    if any(text.count(token)!=count for token,count in required.items()):
        raise ValueError('Counter accepted-start/done/reset/AXI-lite binding changed')
    if ".cycles(32'd0)" in text or text.count(template.strip())!=1:
        raise ValueError('Counter template/tied-zero drift')
    if text.index('wire [31:0] tt_gcs_cycles;')>text.index('.cycles(tt_gcs_cycles)'):
        raise ValueError('Counter net declared after first use')

def install(path,check=False):
    path=Path(path).resolve()
    if not any(path.is_relative_to(p.resolve()) for p in (BUILD,EXPORT_BUILD,FINAL_IP)) or path.name!='tt_engine.v':
        raise ValueError('Only the isolated ABI4 tt_engine.v may be instrumented')
    text=path.read_text(encoding='utf-8')
    marker='// GCS_ABI4_REAL_CYCLES'
    if check:
        verify_binding(text,TEMPLATE.read_text(encoding='utf-8'))
        return dict(rtl=str(path),sha256=sha(path),template_sha256=sha(TEMPLATE),counter='real_ap_start_to_done')
    if marker in text:raise ValueError('Already instrumented; use --check')
    if text.count('.cycles(32\'d0)')!=1 or text.count('.cycles_ap_vld(cycles_ap_vld)')!=1:
        raise ValueError('Unexpected generated RTL cycles binding')
    if not re.search(r"ap_CS_fsm_state1\)\s*&\s*\(ap_start == 1'b0",text):
        raise ValueError('Cannot establish accepted-start state from generated idle logic')
    if text.count('\nendmodule')!=1:raise ValueError('Unexpected generated top module structure')
    before=sha(path)
    text=text.replace('.cycles(32\'d0)','.cycles(tt_gcs_cycles)').replace('.cycles_ap_vld(cycles_ap_vld)','.cycles_ap_vld(ap_done)')
    text,count=re.subn(r'(?m)^wire\s+ap_start;',lambda m:'wire [31:0] tt_gcs_cycles;\n'+m[0],text)
    if count!=1:raise ValueError('Cannot place counter declaration before generated instances')
    block='''
// GCS_ABI4_REAL_CYCLES: accepted start is state1 && ap_start, NOT ap_idle.
tt_gcs_cycle_counter tt_gcs_measure (
    .clk(ap_clk), .resetn(ap_rst_n),
    .accepted(ap_CS_fsm_state1 && ap_start), .done(ap_done), .cycles(tt_gcs_cycles)
);
'''
    text=text.replace('\nendmodule',block+'\nendmodule')+'\n'+TEMPLATE.read_text(encoding='utf-8')
    path.write_text(text,encoding='utf-8',newline='\n')
    result=install(path,True);result['original_sha256']=before
    path.with_suffix('.cycles.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('rtl',type=Path);p.add_argument('--check',action='store_true')
    a=p.parse_args();print(json.dumps(install(a.rtl,a.check),indent=2))
