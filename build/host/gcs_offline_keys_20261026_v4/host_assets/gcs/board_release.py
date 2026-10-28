"""Current release identity; historical logs remain explicitly distinguishable."""
import os
import re
import json
from pathlib import Path

APP_ID='gcs_r1_abi4'
LEGACY_APP_ID='model_lifecycle_r1'
ENGINE_ABI=4
READY_APPS=rf'(?:{APP_ID}|{LEGACY_APP_ID})'  # offline history only; live RX requires APP_ID
BUILD_RE=re.compile(r'^S2C BUILD app=('+APP_ID+r') release=([0-9a-f]{64}) sources=([0-9a-f]{64}) xsa=([0-9a-f]{64})$',re.I|re.M)

def expected_build(path):
    if not path:raise ValueError('Current reviewed ELF evidence required before UART open')
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    keys=('app_id','release_id','source_set_sha256','hardware_xsa_sha256')
    demo=data.get('result')=='LOCAL_DEMO_UNREVIEWED' and os.environ.get('GCS_LOCAL_DEMO','')=='1'
    if data.get('app_id')!=APP_ID or any(not isinstance(data.get(k),str) or not re.fullmatch('[0-9a-f]{64}',data[k]) for k in keys[1:]):
        raise ValueError('Not current reviewed App/source/XSA evidence')
    if not demo and data.get('result')!='ELF_CANDIDATE_PASS':
        raise ValueError('Not current reviewed App/source/XSA evidence')
    out={k:data[k] for k in keys}
    if demo:
        out['demo']=True
        print('!! 本地演示模式（GCS_LOCAL_DEMO=1）：按 bundle manifest 的 release_id 对齐板端；未做发布审查，产物不得作为验收证据')
    return out

def uart_build(text,expected=None,required=True):
    text='\n'.join(line.strip('\r') for line in text.split('\n'))
    rows=BUILD_RE.findall(text)
    if not rows and not required:return None
    if len(rows)!=1:raise ValueError('Current App BUILD identity missing/duplicate')
    app,release,sources,xsa=rows[0]
    result=dict(app_id=app.lower(),release_id=release.lower(),source_set_sha256=sources.lower(),hardware_xsa_sha256=xsa.lower())
    if expected is not None and any(result[k]!=expected.get(k) for k in result):
        raise ValueError('UART App/source/XSA identity differs from reviewed ELF')
    return result
