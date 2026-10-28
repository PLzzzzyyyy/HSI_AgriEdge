"""Real board ROI and DP framebuffer capture; does not simulate physical keys."""
import asyncio,json,time,urllib.request
from pathlib import Path
import websockets
OUT=Path(__file__).resolve().parent
BASE='http://127.0.0.1:8765'
HTTP=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(path):
    with HTTP.open(BASE+path,timeout=25) as r:return r.read()
def state():return json.loads(get('/api/state'))
def frame(name):
    data=get('/api/dp/frame.png');assert data[:8]==b'\x89PNG\r\n\x1a\n'
    (OUT/(name+'.png')).write_bytes(data)
async def main():
    s=state();assert s['source']['channel_ready']
    assert s['source']['release_id']=='c0ea04b7b9bb30c50652232b2d2886de4c33c670d26ed31294d4700758d8ff67'
    await asyncio.to_thread(frame,'live_idle_before')
    async with websockets.connect('ws://127.0.0.1:8765/ws',max_size=8*1024*1024) as ws:
        await ws.recv()
        await ws.send(json.dumps(dict(cmd='start',kind='region',scene='longkou',version='v2',rect=[170,150,40,40])))
        deadline=time.monotonic()+45;rid=None
        while time.monotonic()<deadline:
            event=await asyncio.wait_for(ws.recv(),30)
            if isinstance(event,bytes):continue
            event=json.loads(event)
            if event.get('type')=='command_error':raise RuntimeError(event)
            if event.get('type')=='run_start':rid=event['run']['id'];break
        assert rid
        # Wait for actual pixels: first-load SD preparation can temporarily
        # defer framebuffer service beyond the mirror HTTP timeout.
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            live=await asyncio.to_thread(state);current=live.get('run') or {}
            if current.get('id')==rid and current.get('done',0)>0:break
            await asyncio.sleep(.2)
        else:raise TimeoutError('First computed pixels')
        await asyncio.to_thread(frame,'live_pc_running')
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            s=await asyncio.to_thread(state);run=s.get('run') or {}
            if run.get('id')==rid and run.get('status')=='done':break
            if run.get('status') in ('error','stopped'):raise RuntimeError(run['status'])
            await asyncio.sleep(.5)
        else:raise TimeoutError('ROI completion')
        assert run['done']==run['total']==1600
        await asyncio.sleep(.8)
        await asyncio.to_thread(frame,'live_idle_after')
    before=json.loads((OUT/'before_restart.json').read_text(encoding='utf-8-sig'))
    assert set(before['historyIds']).issubset({r['id'] for r in s['runs']})
    startup=s['source']['startup_evidence']
    discovery=json.loads((Path(startup)/'discovery.json').read_text())
    assert discovery['ready'] and discovery['startup']['dp_rc']==0
    result=dict(result='BOARD_CAPTURED_PENDING_IMAGE_CHECK',release_id=s['source']['release_id'],boot=s['source']['boot_id'],dp_init_rc=0,
        run_id=rid,pixels=1600,history_before=before['historyCount'],history_after=len(s['runs']),
        physical_keys='KEY5/KEY6 source and lifecycle covered by host rendering test; no physical key pressed by automation',
        captures=['live_idle_before.png','live_pc_running.png','live_idle_after.png'])
    (OUT/'live_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
asyncio.run(main())
