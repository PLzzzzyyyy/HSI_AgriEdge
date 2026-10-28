"""Retain raw export; finalize a NEW catalog with byte-exact completed RTL.

HLS 2020.2 inserts its simulation-only deadlock include into every module in
the top file, including the appended counter. Allow only that known addition
and line-ending conversion; restore the proven top in a separate IP tree.
"""
from pathlib import Path,PurePosixPath
from datetime import datetime
import argparse,hashlib,json,re,subprocess,sys,zipfile
from check_gcs_hardware import ROOT,BUILD,EXPORT_BUILD,IP,rtl_ready,ip_ready

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def completed_top(exported,completed):
    block='\n\n// synthesis translate_off\n`include "tt_engine_hls_deadlock_detector.vh"\n// synthesis translate_on\n'
    if exported.count(block)!=2:raise ValueError('Unexpected export simulation instrumentation')
    if exported.replace(block,'').strip()!=completed.strip():raise ValueError('Export has changes beyond known simulation-only insertion/EOL')
    return completed

def finalize(out):
    out=Path(out).resolve()
    if not out.is_relative_to(ROOT/'build/host') or out.exists():raise ValueError('New build/host receipt directory required')
    provenance=rtl_ready();raw=EXPORT_BUILD/'sol/impl/ip'
    if not (EXPORT_BUILD/'export.done').is_file() or IP.exists():raise ValueError('Need completed raw export and absent final IP; never overwrite')
    original=BUILD/'sol/syn/verilog/tt_engine.v';exported=raw/'hdl/verilog/tt_engine.v'
    completed_top(exported.read_text(),original.read_text())
    archive=raw/'tt_hsi_hls_tt_engine_4_0.zip'
    out.mkdir(parents=True,exist_ok=False)
    result=dict(result='RUNNING',started=datetime.now().isoformat(),scope='CATALOG_FINALIZATION_NO_RESYNTHESIS_NO_BOARD',
        raw_archive_sha256=sha(archive),raw_top_sha256=sha(exported),completed_top_sha256=sha(original),provenance=provenance)
    def save():(out/'run.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        with zipfile.ZipFile(archive) as z:
            names=z.namelist()
            for name in names:
                p=PurePosixPath(name)
                if p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name:raise ValueError('Unsafe vendor archive path')
            if hashlib.sha256(z.read('hdl/verilog/tt_engine.v')).hexdigest()!=sha(exported):raise ValueError('Raw ZIP/RTL mismatch')
            IP.mkdir(parents=True,exist_ok=False)
            for item in z.infolist():
                p=IP/item.filename
                if item.is_dir():p.mkdir(parents=True,exist_ok=True)
                else:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(item))
        (IP/'hdl/verilog/tt_engine.v').write_bytes(original.read_bytes())
        command=['D:/xilinx/Vivado/2020.2/bin/vivado.bat','-mode','batch','-source',str(ROOT/'build/vivado/finalize_gcs_ip.tcl')]
        result['command']=command;save()
        with (out/'console.log').open('wb') as log:code=subprocess.run(command,cwd=out,stdout=log,stderr=subprocess.STDOUT).returncode
        text=(out/'console.log').read_text(encoding='utf-8',errors='replace')
        result.update(exit=code,log_sha256=sha(out/'console.log'))
        if code or 'GCS_IP_FINALIZE_PASS' not in text or re.search(r'(?m)^\s*(ERROR:|FATAL:)',text):raise ValueError('IP metadata finalization failed; retain partial tree')
        verified=ip_ready();(out/'verified.json').write_text(json.dumps(verified,indent=2)+'\n',encoding='utf-8')
        result.update(result='FINALIZED_IP_READY_NOT_BOARD',ip_tree_sha256=verified['ip_tree_sha256'])
    except Exception as exc:result.update(result='FAIL',error=str(exc));raise
    finally:result['finished']=datetime.now().isoformat();save()
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path)
    r=finalize(p.parse_args().out);print(json.dumps({k:v for k,v in r.items() if k!='provenance'},indent=2))
