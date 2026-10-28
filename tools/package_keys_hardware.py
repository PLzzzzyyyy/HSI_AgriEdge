"""Package the input-only GPIO ECO bitstream with unchanged PS/ABI4 metadata."""
import hashlib
import json
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/keys_eco_20261018_v4'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    gate=json.loads((OUT/'result.json').read_text())
    if gate['result']!='PASS' or min(gate['wns'],gate['whs'])<0:raise ValueError('Hardware gate not passed')
    original=ROOT/'firmware/tt_gcs_r1_abi4_zu5ev.xsa'
    basebit=ROOT/'firmware/tt_gcs_r1_abi4_zu5ev.bit'
    bit=OUT/'tt_gcs_keys.bit';target=OUT/'tt_gcs_keys.xsa'
    if target.exists():raise ValueError('Retain existing hardware package')
    evidence=dict(gate,base_xsa_sha256=sha(original),base_bit_sha256=sha(basebit),bit_sha256=sha(bit),
        checkpoint_sha256=sha(OUT/'keys_routed.dcp'),
        note='Input-only ECO on PS8 EMIOGPIOI0, accessible as PS GPIO78. Original PS configuration, peripheral addresses, HLS register map and software drivers unchanged; added bitstream wiring documented here.')
    with zipfile.ZipFile(original) as src,zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED) as dst:
        bits=[n for n in src.namelist() if n.endswith('.bit')]
        if len(bits)!=1 or hashlib.sha256(src.read(bits[0])).hexdigest()!=sha(basebit):raise ValueError('Base bitstream/XSA mismatch')
        for info in src.infolist():dst.writestr(info,bit.read_bytes() if info.filename==bits[0] else src.read(info.filename))
        dst.writestr('physical_keys_eco.json',json.dumps(evidence,indent=2))
    evidence['xsa_sha256']=sha(target)
    (OUT/'package.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(evidence,indent=2))
if __name__=='__main__':main()
