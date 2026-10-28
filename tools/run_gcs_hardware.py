"""One isolated hardware stage; never App Build, device access or old P2."""
from pathlib import Path
from datetime import datetime
import argparse,hashlib,json,os,re,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'build/hls/optimization_build/tt_engine_gcs_r1_abi4'
EXPORT_BUILD=ROOT/'build/hls/optimization_build/tt_engine_gcs_r1_abi4_export'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=('synth','cosim','export','system'))
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    out=a.out.resolve()
    if not out.is_relative_to((ROOT/'build/host').resolve()):p.error('New build/host evidence directory required')
    out.mkdir(parents=True,exist_ok=False)
    if a.stage=='synth' and BUILD.exists():p.error('Do not overwrite existing HLS candidate')
    if a.stage=='export':
        from check_gcs_hardware import rtl_ready
        preflight=rtl_ready()
        (out/'preflight.json').write_text(json.dumps(preflight,indent=2)+'\n',encoding='utf-8')
        # Preserve the completed original and the failed first export. Copy only
        # synthesis/export inputs; no rerun, reset, move or delete of cosim.
        if EXPORT_BUILD.exists():
            if (EXPORT_BUILD/'sol/impl').exists() or (EXPORT_BUILD/'export.done').exists():
                p.error('Do not overwrite an attempted/completed IP export')
            clone=json.loads((EXPORT_BUILD/'export_clone.json').read_text())
            for row in clone['files']:
                rel=Path(row['path'])
                if rel.is_absolute() or '..' in rel.parts or sha(EXPORT_BUILD/rel)!=row['sha256'] or sha(BUILD/rel)!=row['sha256']:
                    raise ValueError('Unused clone changed; no overwrite/reuse')
        else:
            EXPORT_BUILD.mkdir();(EXPORT_BUILD/'sol').mkdir()
            copied=[]
            for rel in ('hls.app','synth.done','cosim.done','sol/sol.aps','sol/sol.directive','sol/sol.funcunit','sol/sol_data.json','sol/.autopilot','sol/syn'):
                source=BUILD/rel;target=EXPORT_BUILD/rel
                if source.is_dir():shutil.copytree(source,target)
                else:shutil.copyfile(source,target)
                for f in (sorted(target.rglob('*')) if target.is_dir() else [target]):
                    if f.is_file():
                        r=f.relative_to(EXPORT_BUILD)
                        if sha(f)!=sha(BUILD/r):raise ValueError('Export clone copy mismatch: '+str(r))
                        copied.append(dict(path=r.as_posix(),sha256=sha(f)))
            clone=dict(scope='COPY_OF_COMPLETED_SYNTHESIS_NOT_NEW_COSIM',origin=str(BUILD),files=copied)
            (EXPORT_BUILD/'export_clone.json').write_text(json.dumps(clone,indent=2)+'\n',encoding='utf-8')
        (out/'export_clone.json').write_text(json.dumps(clone,indent=2)+'\n',encoding='utf-8')
    if a.stage=='cosim':
        from install_gcs_cycle_counter import install
        rtl=BUILD/'sol/syn/verilog/tt_engine.v'
        install(rtl,check=rtl.with_suffix('.cycles.json').exists())
    if a.stage=='system':
        from check_gcs_hardware import ip_ready
        (out/'preflight.json').write_text(json.dumps(ip_ready(),indent=2)+'\n',encoding='utf-8')
        command=['D:/xilinx/Vivado/2020.2/bin/vivado.bat','-mode','batch','-source',str(ROOT/'build/vivado/build_gcs_round1.tcl')]
        marker='GCS_SYSTEM_PASS'
    else:
        command=['D:/xilinx/Vitis_HLS/2020.2/bin/vitis_hls.bat','-f',str(ROOT/'build/hls/run_gcs_round1.tcl')]
        marker='GCS_HLS_PASS stage='+a.stage+' name=tt_engine_gcs_r1_abi4'
    baseline=ROOT/'build/vivado/tt_m3a_zu5ev.xsa';before=sha(baseline)
    receipt=dict(stage=a.stage,started=datetime.now().isoformat(),status='RUNNING',pid=os.getpid(),command=command,baseline_xsa=before)
    def save():(out/'run.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    save();env={**os.environ,'GCS_HLS_STAGE':a.stage,'TT_TB_LAYERS':'12'}
    with (out/'console.log').open('wb') as f:
        proc=subprocess.Popen(command,cwd=out,env=env,stdout=f,stderr=subprocess.STDOUT)
        receipt['child_pid']=proc.pid;save();code=proc.wait()
    text=(out/'console.log').read_text(encoding='utf-8',errors='replace')
    ok=code==0 and marker in text and not re.search(r'(?m)^\s*(ERROR:|FATAL:)',text) and sha(baseline)==before
    if ok and a.stage in ('cosim','export'):
        from install_gcs_cycle_counter import install
        rtl=EXPORT_BUILD/'sol/impl/ip/hdl/verilog/tt_engine.v' if a.stage=='export' else BUILD/'sol/syn/verilog/tt_engine.v'
        try:receipt['counter']=install(rtl,True)
        except Exception as exc:ok=False;receipt['counter_error']=str(exc)
    if ok and a.stage in ('export','system'):
        from check_gcs_hardware import ip_ready,system_ready
        try:
            gate=ip_ready() if a.stage=='export' else system_ready()
            (out/'verified.json').write_text(json.dumps(gate,indent=2)+'\n',encoding='utf-8')
        except Exception as exc:ok=False;receipt['gate_error']=str(exc)
    receipt.update(exit=code,status='PASS' if ok else 'FAIL',finished=datetime.now().isoformat(),log_sha256=sha(out/'console.log'))
    save();print(json.dumps(receipt,indent=2),flush=True);print(text[-2000:]);return 0 if ok else 1
if __name__=='__main__':sys.exit(main())
