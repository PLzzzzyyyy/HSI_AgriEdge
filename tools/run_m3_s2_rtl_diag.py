"""Run SHA-validated P1 RTL directly; bounded real AXI backpressure, no synthesis."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import struct
from run_m3_s2_impl import ROOT, dump, require, sha, validate_ooc
from run_m3_s2_rtl_n1 import run_stage

VIVADO=Path('D:/xilinx/Vivado/2020.2/bin')
GUARD=0x5a719dce4362be08
OUT_WORDS=512+95260
MARKER='S2_RTL_N1_EXECUTION_COMPLETE_NOT_NUMERIC_PASS'


def validated_synth_rtl(tag):
    require(bool(re.fullmatch('[a-z0-9_]+',tag)), 'Invalid synthesis tag')
    run=ROOT/'build/host'/('m3_s2_synth_'+tag)
    rows=json.loads((run/'results.json').read_text())
    require(json.loads((run/'running.json').read_text()).get('finished') and
            len(rows)==1, 'Need a completed isolated P1 synthesis')
    row=rows[0]
    require(row.get('synthesis_completed') and row['exit']==0 and
            not row.get('timed_out') and (row['num'],row['p'],row['pack'])==(8,1,1),
            'Need successful W8 P1 synthesis (G2 status is retained separately)')
    build=ROOT/'build/hls/optimization_build'/row['name']
    csim=ROOT/'build/hls/optimization_build'/row['source_csim']
    require((build/'synth.done').is_file() and (csim/'csim.done').is_file(),
            'Missing synthesis/CSim completion marker')
    require(sha(ROOT/row['log'])==row['log_sha256'], 'HLS log mismatch')
    for name,digest in row['snapshot'].items():
        require(sha(build/'snapshot'/name)==digest, 'HLS snapshot mismatch: '+name)
        if name.startswith('src/'):
            require(sha(ROOT/name)==digest and sha(csim/'snapshot'/name)==digest,
                    'Current source/CSim mismatch: '+name)
    require((build/'sol/syn/verilog/s2_engine.v').is_file(), 'Missing new RTL')
    return build/'sol/syn/verilog'


def validated_fp_models(rtl,ooc):
    # Reuse only simulation IP, never the old DUT. Exact IP Tcl equality is
    # required; model hashes come from the frozen r9 direct-r4 input receipt.
    receipt=json.loads((ooc/'results.json').read_text())
    frozen=ROOT/'build/host/m3_s2_rtl_20261008_r9_n1_direct_r4/inputs.json'
    hashes=json.loads(frozen.read_text())['files']
    configs=list(rtl.glob('*_ip.tcl'))
    models=list((ooc/'project/s2_ooc.gen/sources_1/ip').glob('*/sim/*.v'))
    require(len(configs)==5 and len(models)==5, 'Need five matching FP IPs')
    for p in configs:
        require(sha(p)==receipt['inputs'].get('rtl/'+p.name), 'FP configuration changed: '+p.name)
    for p in models:
        require(sha(p)==hashes.get('rtl/'+p.name), 'FP model hash mismatch: '+p.name)
    return models


def load_observation(engine):
    lines=['$display("LOAD_ENGINE state=%h",dut.engine_task_U0.ap_CS_fsm);']
    for stem in ('core_send_weights','load'):
        instances=re.findall(r'\b(s2_engine_'+stem+r')\s+(grp_'+stem+r'_fu_\d+)\s*\(',engine)
        require(len(instances)==1, 'Cannot bind LOAD observation: '+stem)
        instance=instances[0][1]
        lines.append(f'$display("LOAD_{stem.upper()} done=%b idle=%b",dut.engine_task_U0.{instance}_ap_done,dut.engine_task_U0.{instance}_ap_idle);')
    return '\n'.join(lines)+'\n'


def validate_observation_nets(top,body):
    nets=set(re.findall(r'^\s*(?:wire|reg|input|output)\s+(?:\[[^\]]+\]\s*)?(\w+)\s*;',top,re.M))
    instances=set(re.findall(r'^\s*\w+\s+(\w+)\s*\(',top,re.M))
    referenced=set(re.findall(r'\bdut\.(\w+)',body))
    require(not (referenced-nets-instances), 'Unknown DUT observation: '+str(sorted(referenced-nets-instances)))


def execution_completed(receipt,text):
    return (MARKER in text and receipt['exit']==0 and not receipt['timed_out'] and
            not any(word in text for word in ('Fatal:','ERROR:',
                'cannot be opened for reading','Simulation engine not responding')))


def make_top(rtl, weight_words):
    parameters=re.findall(r'^parameter\s+(\w+)\s*=\s*([^;]+);',rtl,re.M)
    ports=re.findall(r'^(input|output)\s+(\[[^\]]+\])?\s*(\w+)\s*;',rtl,re.M)
    require(len(ports)>100,'Cannot identify complete DUT ports')
    lines=['`timescale 1ns/1ps','module s2_diag_top;']
    lines += [f'localparam {name}={value};' for name,value in parameters]
    for direction,width,name in ports:
        init=' = 0' if direction=='input' and not name.startswith('m_axi_') else ''
        lines.append(f'logic {width} {name}{init};')
    lines.append('s2_engine dut('+','.join(f'.{name}({name})' for _,_,name in ports)+');')
    connected='araddr awaddr wdata arlen awlen wstrb arsize awsize arburst awburst arid awid arvalid awvalid wvalid wlast rready bready arready awready wready rdata rvalid rlast rid bvalid bid rresp bresp'.split()
    for bus,words,file in [('wmem',weight_words,'weights.hex'),('inmem',3969,'input.hex'),('outmem',OUT_WORDS,'')]:
        args=['.clk(ap_clk)','.rst_n(ap_rst_n)']+[f'.{p}(m_axi_{bus}_{p.upper()})' for p in connected]
        lines.append(f's2_axi_memory #(.WORDS({words}),.FILE("{file}"),.READ_ONLY({int(bus!="outmem")})) {bus}('+','.join(args)+');')
        for signal in ('RUSER','BUSER'):
            lines.append(f'assign m_axi_{bus}_{signal}=0;')
    lines+=['`include "s2_rtl_n1_body.svh"','endmodule']
    return '\n'.join(lines)+'\n'


def write_hex(source,dest):
    data=source.read_bytes()
    require(len(data)%8==0,'Expected whole AXI words')
    dest.write_text(''.join(f'{word[0]:016x}\n' for word in struct.iter_unpack('<Q',data)))


def compare_output(out,golden):
    words=[]
    for line in (out/'output.hex').read_text().splitlines():
        line=line.split('//')[0].strip()
        if line:words.extend(int(x,16) for x in line.split())
    require(len(words)==OUT_WORDS,'Output memory dump size mismatch')
    actual=struct.pack('<'+'Q'*len(words),*words)
    expected=bytearray(struct.pack('<Q',GUARD)*OUT_WORDS)
    spans=[]
    for name,offset in [('logits_q16_i32.bin',0),('class_u32.bin',0x100)]+[(f'L{i}_x_out_i4.bin',0x1000+i*7938*8) for i in range(12)]:
        data=(golden/name).read_bytes();expected[offset:offset+len(data)]=data
        mismatch=[i for i,(a,b) in enumerate(zip(actual[offset:offset+len(data)],data)) if a!=b]
        spans.append(dict(name=name,bytes=len(data),match=not mismatch,first_mismatch_byte=mismatch[0] if mismatch else None))
    mismatch=[i for i,(a,b) in enumerate(zip(actual,expected)) if a!=b]
    return dict(passed=not mismatch,spans=spans,all_memory_including_guards_matches=not mismatch,
        mismatch_bytes=len(mismatch),first_mismatch_byte=mismatch[0] if mismatch else None,
        actual_sha256=sha(out/'output.hex'))


def compare_layer_snapshots(out,golden):
    spans=[]
    for layer in range(12):
        p=out/f'layer_{layer:02d}.hex'
        if not p.exists():continue
        words=[]
        for line in p.read_text().splitlines():
            words.extend(int(x,16) for x in line.split('//')[0].split())
        require(len(words)==7938,'Incomplete layer snapshot: '+p.name)
        data=struct.pack('<'+'Q'*len(words),*words)
        expected=(golden/f'L{layer}_x_out_i4.bin').read_bytes()
        spans.append(dict(layer=layer,match=data==expected,bytes=len(data),sha256=sha(p)))
    return dict(scope='Partial observed layer data only; NOT complete n1/guard/drain PASS',
                layers=spans,all_12_match=len(spans)==12 and all(s['match'] for s in spans))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True)
    ap.add_argument('--timeout',type=int,default=3600)
    ap.add_argument('--synth-tag',help='Fresh P1 synthesis; never reuse the old DUT after a source change')
    args=ap.parse_args();require(bool(re.fullmatch('[a-z0-9_]+',args.tag)),'Invalid tag')
    require(args.timeout>0,'Invalid timeout')
    ooc=ROOT/'build/host/m3_s2_ooc_20261008_t3_fix_r9_ip'
    if args.synth_tag:
        source_rtl=validated_synth_rtl(args.synth_tag)
    else:
        validate_ooc(ooc)
        source_rtl=ooc/'rtl'
    models=validated_fp_models(source_rtl,ooc)
    validate_observation_nets((source_rtl/'s2_engine.v').read_text(),
                              (ROOT/'sim/hls_tb/s2_rtl_n1_body.svh').read_text())
    import subprocess
    check=subprocess.run(['powershell','-NoProfile','-Command',
        "Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(vitis_hls|vivado_hls|vivado|xsim|xelab|xvlog)(\\.exe)?$'} | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json"],capture_output=True,text=True,check=True)
    require(not check.stdout.strip(),'Hardware task occupied: '+check.stdout)
    out=ROOT/'build/host'/('m3_s2_rtl_'+args.tag);out.mkdir(exist_ok=False,parents=True)
    (out/'occupancy.txt').write_text(check.stdout)
    rtl=out/'rtl';shutil.copytree(source_rtl,rtl)
    # Generated readmemh paths are relative to simulation CWD, not RTL files.
    for p in rtl.glob('*.dat'):shutil.copy2(p,out/p.name)
    for p in rtl.glob('*.v'):
        for name in re.findall(r'\$readmemh\("([^\"]+)"',p.read_text()):
            require((out/name).is_file(),'Missing RTL initialization file: '+name)
    for p in models:shutil.copy2(p,rtl/p.name)
    for name in ('s2_axi_memory.sv','s2_rtl_n1_body.svh'):
        shutil.copy2(ROOT/'sim/hls_tb'/name,out/name)
    (out/'s2_load_observation.svh').write_text(load_observation((rtl/'s2_engine_engine_task.v').read_text()))
    for p in (Path(__file__),ROOT/'tools/run_m3_s2_rtl_n1.py',ROOT/'tools/run_m3_s2_impl.py'):
        shutil.copy2(p,out/p.name)
    golden=ROOT/'sim/golden/n6_engine_i8'
    write_hex(golden/'weights_engine.bin',out/'weights.hex')
    write_hex(golden/'a/x_in_i16.bin',out/'input.hex')
    (out/'s2_diag_top.sv').write_text(make_top((rtl/'s2_engine.v').read_text(),(golden/'weights_engine.bin').stat().st_size//8))
    project=''.join(f'verilog xil_defaultlib "rtl/{p.name}"\n' for p in sorted(rtl.glob('*.v')))
    project+='sv xil_defaultlib "s2_axi_memory.sv"\nsv xil_defaultlib "s2_diag_top.sv"\n'
    (out/'diag.prj').write_text(project)
    (out/'run.tcl').write_text('run all\nquit\n')
    inputs={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()}
    dump(out/'inputs.json',dict(source_rtl=str(source_rtl),synth_tag=args.synth_tag,fp_model_ooc=str(ooc),files=inputs,
        golden={p.relative_to(golden).as_posix():sha(p) for p in golden.rglob('*.bin') if p.parent==golden or p.parent==golden/'a'}))
    command=[str(VIVADO/'xelab.bat'),'xil_defaultlib.s2_diag_top','-prj','diag.prj',
        '-L','floating_point_v7_1_11','-L','xil_defaultlib','-L','unisims_ver','-L','xpm',
        '-s','s2_diag','-debug','off','-mt','4']
    compile_result=run_stage(out,'compile',command,dict(os.environ),1800)
    result=dict(scope='SHA-validated P1 n1 12-layer DUMP with real AXI stalls; NOT CLASS_ONLY/n16/P2/system',synth_tag=args.synth_tag,compile=compile_result,finished=True,passed=False)
    if compile_result['exit']==0 and (out/'xsim.dir/s2_diag/xsimk.exe').is_file():
        result['simulation']=run_stage(out,'simulate',[str(VIVADO/'xsim.bat'),'s2_diag','-tclbatch','run.tcl'],dict(os.environ),args.timeout)
        text=(out/'simulate.log').read_text(errors='replace')
        result['execution_completed']=execution_completed(result['simulation'],text)
        result['calls']=[dict(id=int(i),cycle=int(c),cycles=int(n),rc=int(rc),fifo_empty=empty) for i,c,n,rc,empty in re.findall(r'CALL_DONE id=(\d+) cycle=(\d+) cycles=(\d+) return=(\d+) fifo_empty=(\d+)',text)]
        result['axi_stats']=[line for line in text.splitlines() if line.startswith('AXI_STATS')]
        try:result['layer_snapshots']=compare_layer_snapshots(out,golden/'a')
        except Exception as exc:result['layer_snapshots']=dict(all_12_match=False,error=repr(exc))
        if result['execution_completed']:
            try:result['numeric']=compare_output(out,golden/'a')
            except Exception as exc:result['numeric']=dict(passed=False,error=repr(exc))
            result['passed']=result['numeric']['passed'] and len(result['calls'])==2 and all(c['rc']==0 and c['fifo_empty']=='1111' for c in result['calls'])
    if args.synth_tag:validated_synth_rtl(args.synth_tag)
    else:validate_ooc(ooc)
    validated_fp_models(source_rtl,ooc)
    for p in source_rtl.glob('*'):
        if p.is_file():require(sha(p)==sha(rtl/p.name),'DUT RTL changed: '+p.name)
    dump(out/'results.json',result)
    print(json.dumps(result,indent=2),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
