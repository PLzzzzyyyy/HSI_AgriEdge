"""Read-only ABI4 IP/system evidence gate; not App Build or board acceptance."""
from pathlib import Path
import argparse,hashlib,json,re,xml.etree.ElementTree as ET,zipfile
from install_gcs_cycle_counter import install
ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'build/hls/optimization_build/tt_engine_gcs_r1_abi4'
EXPORT_BUILD=ROOT/'build/hls/optimization_build/tt_engine_gcs_r1_abi4_export'
IP=ROOT/'build/hls/optimization_build/tt_engine_gcs_r1_abi4_ip'
PREFIX=ROOT/'build/vivado/impl_gcs_r1_abi4'
XSA=ROOT/'build/vivado/tt_gcs_r1_abi4_zu5ev.xsa'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rtl_ready():
    """Read the completed 12:17 run, never rerun or modify its candidate."""
    snapshot=BUILD/'snapshot';sources={}
    for p in sorted(snapshot.rglob('*')):
        if not p.is_file() or p.name=='flags.txt':continue
        rel=p.relative_to(snapshot).as_posix()
        if not (ROOT/rel).is_file() or sha(ROOT/rel)!=sha(p):raise ValueError('HLS input drift: '+rel)
        sources[rel]=sha(p)
    flags=(snapshot/'flags.txt').read_text()
    if 'flags=-DTT_K3=7 -DTT_DB=18 -DTT_M3_OVERLAP=0' not in flags or 'abi=4' not in flags:
        raise ValueError('Wrong isolated serial candidate flags')
    receipts={}
    for stage,directory in (('synth','hls_synth'),('cosim','hls_cosim_declaration_fix')):
        run=ROOT/'build/host/gcs_round1_20261011'/directory
        record=json.loads((run/'run.json').read_text());log=(run/'console.log').read_text(encoding='utf-8',errors='strict')
        marker=f'GCS_HLS_PASS stage={stage} name=tt_engine_gcs_r1_abi4'
        if record.get('stage')!=stage or record.get('status')!='PASS' or record.get('exit')!=0 or not record.get('finished'):
            raise ValueError('No final PASS receipt for HLS '+stage)
        if record['log_sha256']!=sha(run/'console.log') or marker not in log or re.search(r'(?m)^\s*(ERROR:|FATAL:)',log):
            raise ValueError('HLS final log failed/drifted: '+stage)
        if marker not in (BUILD/(stage+'.done')).read_text():raise ValueError('Wrong completed HLS marker')
        if stage=='cosim':
            post=log.split('Starting C post checking ...')
            layers=re.findall(r'ATTENTION px=(\d+) layer=(\d+) words=36 mismatches=0',post[-1])
            if len(post)!=2 or '*** C/RTL co-simulation finished: PASS ***' not in post[-1] or [(int(p),int(l)) for p,l in layers]!=[(p,l) for p in range(3) for l in range(12)]:
                raise ValueError('Complete RTL attention postcheck absent')
            if record['counter']['sha256']!=sha(BUILD/'sol/syn/verilog/tt_engine.v'):
                raise ValueError('Cosim completed against a different counter/top RTL')
        receipts[stage]=dict(path=str(run/'run.json'),sha256=sha(run/'run.json'),log_sha256=record['log_sha256'])
    cycles=BUILD/'sol/sim/tv/rtldatafile/rtl.tt_engine.autotvout_cycles.dat'
    values=re.findall(r'\[\[transaction\]\]\s+(\d+)\s+(0x[0-9a-fA-F]+)\s+\[\[/transaction\]\]',cycles.read_text())
    if [int(n) for n,v in values]!=list(range(23)) or any(not 0<int(v,16)<0xffffffff for n,v in values):
        raise ValueError('Incomplete/invalid 23 RTL cycles-register transactions')
    return dict(result='COMPLETED_RTL_PROVENANCE_PASS_NOT_BOARD',sources=sources,receipts=receipts,
        counter=install(BUILD/'sol/syn/verilog/tt_engine.v',True),cycles=dict(path=str(cycles),sha256=sha(cycles),transactions=23))

def ip_ready():
    provenance=rtl_ready()
    for stage in ('synth','cosim','export'):
        if not ((EXPORT_BUILD if stage=='export' else BUILD)/(stage+'.done')).is_file():raise ValueError('Missing completed HLS '+stage)
    for rel in ('src/hls/tt_engine.cpp','src/hls/tt_engine.h','src/hls/tt_engine_regs.h','src/hls/tt_types.h','src/hls/tt_attn.cpp','src/hls/tt_attn.h','sim/hls_tb/tb_tt_engine_full.cpp','sim/hls_tb/tb_tt_engine_attention.cpp'):
        if sha(ROOT/rel)!=sha(BUILD/'snapshot'/rel):raise ValueError('HLS source drift: '+rel)
    counter=install(IP/'hdl/verilog/tt_engine.v',True)
    if counter['sha256']!=provenance['counter']['sha256']:raise ValueError('Export changed completed cosim RTL')
    tree=ET.parse(IP/'component.xml');ns={'s':'http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009'}
    if tree.getroot().findtext('s:version',namespaces=ns)!='4.0':raise ValueError('Wrong IP version')
    # Frozen register ABI: do not silently use a new BSP register map.
    new=next(IP.glob('drivers/*/src/xtt_engine_hw.h'))
    old=ROOT/'build/hls/optimization_build/tt_engine_m3_k7/sol/impl/ip/drivers/tt_engine_v2_0/src/xtt_engine_hw.h'
    if not old.exists():old=next((ROOT/'build/hls/optimization_build/tt_engine_m3_k7/sol/impl/ip').glob('drivers/*/src/xtt_engine_hw.h'))
    def offsets(p):return dict(re.findall(r'^#define\s+(XTT_ENGINE_CTRL_(?:ADDR|BITS)_\w+)\s+(0x[0-9a-fA-F]+|\d+)',p.read_text(),re.M))
    if not offsets(new) or offsets(new)!=offsets(old):raise ValueError('Generated register ABI changed; stop before platform use')
    files=[dict(path=p.relative_to(IP).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(IP.rglob('*')) if p.is_file()]
    root=ET.parse(BUILD/'sol/syn/report/tt_engine_csynth.xml').getroot();area=root.find('AreaEstimates')
    resources={n:int(area.find('Resources/'+n).text) for n in ('BRAM_18K','DSP','FF','LUT','URAM')}
    available={n:int(area.find('AvailableResources/'+n).text) for n in resources}
    if any(resources[k]>available[k] for k in resources):raise ValueError('HLS candidate over device capacity; not a system fit result')
    return dict(result='IP_READY',scope='HLS_CSIM_RTL_COSIM_COUNTER_AND_EXPORT_NOT_BOARD',abi=4,ip_vlnv='tt_hsi:hls:tt_engine:4.0',
        counter=counter,register_map=offsets(new),hls_estimate=resources,device_capacity=available,ip_files=files,
        ip_tree_sha256=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),rtl_provenance=provenance)
def system_ready():
    result=ip_ready();gate=json.loads(Path(str(PREFIX)+'_gate.json').read_text())
    if gate['result']!='PASS' or gate['wns']<0 or gate['whs']<0 or gate['ctrl_base']!='0x80000000':raise ValueError('Full-system timing/address gate failed')
    if gate['ref_mhz']!=33.333 or gate['pl_actual_mhz']!=199.998001:raise ValueError('XSA PS reference/PL0 configuration differs from measured contract')
    with zipfile.ZipFile(XSA) as z:
        bits=[n for n in z.namelist() if n.endswith('.bit')]
        if len(bits)!=1:raise ValueError('Full-system XSA must include exactly one bitstream')
        bit_sha=hashlib.sha256(z.read(bits[0])).hexdigest()
        handoffs=[n for n in z.namelist() if n.endswith('.hwh')]
        if len(handoffs)!=1:raise ValueError('XSA hardware handoff missing/ambiguous')
        hwh=ET.fromstring(z.read(handoffs[0]));engines=[m for m in hwh.iter('MODULE') if m.get('MODTYPE')=='tt_engine']
        ps=[m for m in hwh.iter('MODULE') if m.get('MODTYPE')=='zynq_ultra_ps_e']
        if len(engines)!=1 or len(ps)!=1 or engines[0].get('VLNV')!='tt_hsi:hls:tt_engine:4.0':raise ValueError('XSA does not contain the new ABI4 engine')
        eng_params={p.get('NAME'):p.get('VALUE') for p in engines[0].iter('PARAMETER')}
        ps_params={p.get('NAME'):p.get('VALUE') for p in ps[0].iter('PARAMETER')}
        expected={'PSU__PSS_REF_CLK__FREQMHZ':'33.333','PSU__CRL_APB__PL0_REF_CTRL__DIVISOR0':'4',
            'PSU__CRL_APB__PL0_REF_CTRL__DIVISOR1':'1','PSU__CRL_APB__PL0_REF_CTRL__SRCSEL':'RPLL',
            'PSU__CRL_APB__PL0_REF_CTRL__ACT_FREQMHZ':'199.998001'}
        if eng_params.get('C_S_AXI_CTRL_BASEADDR')!='0x80000000' or any(ps_params.get(k)!=v for k,v in expected.items()):
            raise ValueError('XSA HWH register address/clock divider mismatch')
        header=next(IP.glob('drivers/*/src/xtt_engine_hw.h'))
        if z.read('drivers/tt_engine_v4_0/src/xtt_engine_hw.h')!=header.read_bytes():raise ValueError('XSA driver/register map differs from finalized IP')
    reports={}
    for suffix in ('utilization','timing','drc','route_status','clocks','check_timing'):
        p=Path(str(PREFIX)+'_'+suffix+'.rpt')
        if not p.is_file() or not p.stat().st_size:raise ValueError('Missing full-system report '+suffix)
        reports[suffix]=dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p))
    check=Path(str(PREFIX)+'_check_timing.rpt').read_text()
    categories=dict(re.findall(r'^\d+\. checking (\w+) \((\d+)\)$',check,re.M))
    if len(categories)!=12 or any(int(v) for v in categories.values()):raise ValueError('Unconstrained/invalid timing checks remain')
    route=Path(str(PREFIX)+'_route_status.rpt').read_text()
    routing=dict(re.findall(r'# of (routable nets|fully routed nets|nets with routing errors)\.+\s*:\s*(\d+)',route))
    if routing.get('routable nets')!=routing.get('fully routed nets') or routing.get('nets with routing errors')!='0':raise ValueError('Incomplete/error routing')
    drc=Path(str(PREFIX)+'_drc.rpt').read_text()
    drc_rows=re.findall(r'^\|\s*([A-Z]+-\d+)\s*\|\s*(Warning|Advisory|Error|Critical Warning)\s*\|[^\n]*\|\s*(\d+)\s*\|$',drc,re.M)
    if any(severity in ('Error','Critical Warning') for _,severity,_ in drc_rows):raise ValueError('Critical/error DRC remains')
    if sum(int(n) for _,_,n in drc_rows)!=int(re.search(r'Violations found:\s*(\d+)',drc)[1]):raise ValueError('DRC coverage incomplete')
    utilization=Path(str(PREFIX)+'_utilization.rpt').read_text();actual={}
    for name in ('CLB LUTs','CLB Registers','Block RAM Tile','URAM','DSPs'):
        row=re.search(r'^\|\s*'+re.escape(name)+r'\s*\|\s*(\d+)\s*\|\s*\d+\s*\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|$',utilization,re.M)
        if not row or int(row[1])>int(row[2]):raise ValueError('Full-system resource gate failed: '+name)
        actual[name]=dict(used=int(row[1]),available=int(row[2]),percent=float(row[3]))
    result.update(result='HARDWARE_CANDIDATE_PASS',scope='FULL_SYSTEM_ROUTE_BITSTREAM_XSA_NOT_BOARD_ACCEPTANCE',system=gate,
        xsa=dict(path=XSA.relative_to(ROOT).as_posix(),sha256=sha(XSA),bit_member=bits[0],bit_sha256=bit_sha),reports=reports,
        configured_pl_hz=199998000,nominal_pl_hz=200000000,actual_resources=actual,timing_checks=categories,
        routing=routing,drc=[dict(rule=rule,severity=severity,count=int(n)) for rule,severity,n in drc_rows])
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stage',choices=('rtl','ip','system'),required=True);p.add_argument('--out',type=Path)
    a=p.parse_args();r={'rtl':rtl_ready,'ip':ip_ready,'system':system_ready}[a.stage]()
    if a.out:
        out=a.out.resolve()
        if not out.is_relative_to((ROOT/'build/host').resolve()) or out.exists():raise ValueError('New build/host evidence path required')
        out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in r.items() if k!='ip_files'},indent=2))
