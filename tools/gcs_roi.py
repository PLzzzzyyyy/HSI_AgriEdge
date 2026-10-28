#!/usr/bin/env python3
"""One entry for formal GCS ROI: serve (locked), authorize, test, verify.
No board UDP is sent by this launcher. Only the user's UI Start sends a job.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def api(port, path, data=None):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}',
                                 data=json.dumps(data).encode() if data else None,
                                 headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def verify(args):
    # Strictly read-only: no service, socket, random, inference or board interaction.
    sys.path.insert(0,str(ROOT/'gcs'))
    import board_roi as b
    d=args.run_dir.resolve()
    info=json.loads((d/'session.json').read_text(encoding='utf-8-sig'))
    j=b.Job(info['boot_id'],info['session'],info['task'])
    for line in (d/'packets.jsonl').read_text(encoding='utf-8-sig').splitlines():
        p=json.loads(line);data=bytes.fromhex(p['hex'])
        if p.get('phase')=='interaction':
            if not j.audit.complete():raise ValueError('Interaction before complete task')
            continue  # separately audited probe session, not a new ROI task
        if tuple(p['peer'])!=b.wire.TARGET:
            if p['direction']=='tx':raise ValueError('TX outside fixed endpoint')
            continue
        if p['direction']=='tx':j.sent(data)
        elif p['direction']=='rx':j.receive(data)
        else:raise ValueError('Unknown packet direction')
    if not j.finish():raise ValueError(j.error)
    actual=j.snapshot()
    saved=json.loads((d/'summary.json').read_text(encoding='utf-8-sig'))
    for key in ('boot_id','session','task','ack','start_seq','cells','done_status','received_pixels','status'):
        if saved[key]!=actual[key]:raise ValueError('Saved/UDP mismatch: '+key)
    checks=dict(udp_complete=True, saved_exact=True, uart_verified=False, ui_verified=False)
    if args.uart:
        uart=args.uart.read_text(encoding='utf-8-sig')
        words=re.findall(r'ROI x=(\d+) y=(\d+) class_word=([0-9A-Fa-f]{8})',uart)
        expected={(c['x'],c['y']):c['class_word'].upper() for c in actual['cells']}
        got={(int(x),int(y)):word.upper() for x,y,word in words}
        if len(words)!=15 or got!=expected:raise ValueError('UART requires exactly 15 unique matching words')
        # Accept only the actual S2c RESULT grammar, not generic nearby success text.
        result=re.search(r'S2C RESULT[^\r\n]*',uart)
        execution=re.search(r'S2C EXEC[^\r\n]*',uart)
        if not result or not execution:raise ValueError('Missing S2C EXEC/RESULT identity evidence')
        for token in (f'session={actual["session"]}',f'task={actual["task"]}'):
            if token.lower() not in execution[0].lower():raise ValueError('UART EXEC identity mismatch: '+token)
        for token in ('rc=0','driver=0','completed=15','halted=0'):
            if not re.search(r'(?<!\w)'+re.escape(token)+r'(?!\d)',result[0]):raise ValueError('UART RESULT not successful: '+token)
        if not re.search(r'READY[^\r\n]*boot_id='+actual['boot_id'],uart,re.I):raise ValueError('UART READY boot mismatch')
        checks['uart_verified']=True
    if args.ui:
        ui=json.loads(args.ui.read_text(encoding='utf-8-sig'))
        if ui.get('mode')!='live-board' or ui.get('boot_id')!=actual['boot_id'] or ui.get('session')!=actual['session'] or ui.get('task')!=actual['task']:
            raise ValueError('UI identity/mode mismatch; offline fixtures cannot be board evidence')
        if ui.get('cells')!=actual['cells'] or not ui.get('checks') or not all(ui['checks'].values()):raise ValueError('UI cells/checks mismatch')
        checks['ui_verified']=True
    # Reference is comparison only, never used for missing actual pixels.
    ref=b.wire.reference()
    checks['reference_word_match']=all(int(c['class_word'],16)==ref[c['x'],c['y']] for c in actual['cells'])
    checks['formal_acceptance']=all(checks.values())
    print(json.dumps(dict(checks=checks,boot_id=actual['boot_id'],session=actual['session'],task=actual['task']),indent=2))
    return 0 if checks['formal_acceptance'] else 2


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sp=p.add_subparsers(dest='command',required=True)
    serve=sp.add_parser('serve');serve.add_argument('--port',type=int,default=8765)
    auth=sp.add_parser('authorize');auth.add_argument('--port',type=int,default=8765)
    auth.add_argument('--boot-id',required=True);auth.add_argument('--board-started',action='store_true')
    sp.add_parser('test')
    v=sp.add_parser('verify');v.add_argument('--run-dir',type=Path,required=True)
    v.add_argument('--uart',type=Path);v.add_argument('--ui',type=Path)
    a=p.parse_args()
    if a.command=='test':
        return subprocess.call([sys.executable,'-B',str(ROOT/'tools/test_gcs_features.py')],cwd=ROOT)
    if a.command=='verify':return verify(a)
    if a.command=='authorize':
        if not a.board_started:p.error('Require explicit user confirmation and --board-started')
        result=api(a.port,'/api/board/authorize',dict(boot_id=a.boot_id,board_started=True))
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    with socket.socket() as s:
        occupied=s.connect_ex(('127.0.0.1',a.port))==0
    if occupied:
        try:state=api(a.port,'/api/state')
        except Exception:raise SystemExit('Port occupied by another service; not stopping/replacing it')
        if state.get('service')!='gcs-s2c-roi':raise SystemExit('Port occupied by another service; not replacing it')
        print(f'Existing GCS reused: http://127.0.0.1:{a.port}; no duplicate process')
        return 0
    print(f'Formal GCS (board locked): http://127.0.0.1:{a.port}',flush=True)
    sys.path.insert(0,str(ROOT/'gcs'))
    import server
    server.uvicorn.run(server.app,host='127.0.0.1',port=a.port,log_level='info')
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        print(f'FAIL: {type(exc).__name__}: {exc}',file=sys.stderr);sys.exit(1)
