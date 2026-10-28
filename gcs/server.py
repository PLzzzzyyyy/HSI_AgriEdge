"""无人机高光谱张量农情分析系统 · 地面站服务端。

    D:/pytorch/python.exe gcs/server.py [--port 8765] [--no-browser]

浏览器打开 http://127.0.0.1:8765 。默认板卡地面站；启动/刷新不连接串口或发送设备命令。
WebSocket /ws：客户端发 JSON 命令；服务端发 JSON 事件与二进制结果块
    结果块：u8 1 | u8 0 | u16 run | u32 n | u16 row[n] | u16 col[n] | u8 label[n] | u8 conf255[n]
"""
import argparse
import asyncio
import json
import hashlib
import re
import struct
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
import uuid
from contextlib import ExitStack
from pathlib import Path
from datetime import datetime

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analysis  # noqa: E402
import engine as E  # noqa: E402
import sources  # noqa: E402
import board_roi  # noqa: E402
import board_task  # noqa: E402
import board_link  # noqa: E402
import board_models  # noqa: E402
import board_timing  # noqa: E402
import board_boot  # noqa: E402
import board_log  # noqa: E402
import board_release  # noqa: E402
import board_history  # noqa: E402
import uart_capture  # noqa: E402
import scene_input  # noqa: E402
import board_metrics  # noqa: E402
import board_agri  # noqa: E402
import display_name
import display_labels
import board_keys
import speed_compare
import gcs_release  # full ABI4 release gate; never the legacy 24-source synchronizer

ROOT = E.ROOT
LOADED_RELEASE_ASSETS = gcs_release.runtime_assets()
app = FastAPI()
eng = E.Engine()
INPUTS = scene_input.InputReader(E.DATA)
CHUNK = struct.Struct('<BBHI')


class Run:
    def __init__(self, rid, kind, scene, version, rect, coords, H, W, source):
        self.id, self.kind, self.scene, self.version, self.rect = rid, kind, scene, version, rect
        self.coords, self.total, self.source = coords, len(coords), source
        self.pred = np.zeros((H, W), np.uint8)
        self.conf = np.zeros((H, W), np.float32)
        self.done = np.zeros((H, W), bool)
        self.n = 0
        self.compute_s = 0.0
        self.energy_j = 0.0
        self.board_ms_per_px = None
        self.t0, self.t_end = time.time(), None
        self.status = 'running'
        self.row = 0
        self.board_job = None
        self.lock = threading.RLock()

    def summary(self):
        with self.lock:return self._summary()

    def _summary(self):
        el = (self.t_end or time.time()) - self.t0
        b=self.board_job.snapshot(include_cells=not self.board_job.full) if self.board_job else None
        ms=(b.get('performance') or {}).get('ms_per_pixel') if b else self.board_ms_per_px
        return dict(id=self.id, kind=self.kind, scene=self.scene, version=self.version, rect=self.rect,
                    source=self.source, total=self.total, done=self.n, status=self.status, elapsed=el,
                    compute_s=self.compute_s if self.source != 'board' else None,
                    energy_j=self.energy_j if self.source != 'board' else None, row=self.row,
                    power_estimate=b.get('power_estimate') if b else None,
                    board_ms_per_px=ms,
                    receive_rate=self.n/el if el>0 and self.source=='board' else None,
                    board=b,origin=getattr(self,'origin',None))


class State:
    def __init__(self, history_root=None):
        self.board_source = board_link.BoardSource(history_root)
        self.parcels = board_agri.ParcelStore(self.board_source.root/'ledger')
        self.source = self.board_source
        self.control_lock = threading.Lock()
        self.clients = set()
        self.run = None
        self.runs = {}
        self.next_id = 1
        self.loop = None
        self.out = None
        self.finetune = None
        self.key_context=None
        self.speed=speed_compare.Comparison(self.board_source.root/'speed_compare')
        self.model_catalog_errors=E.discover_board_exports()
        self.history_errors = []
        jobs,self.history_errors=board_history.load_all(self.board_source.root)
        for job in jobs:
            a=job.audit;meta=job.host_run or {}
            rid=meta.get('id',self.next_id)
            if type(rid) is not int or rid<1 or rid in self.runs:
                self.history_errors.append(dict(path=str(job.out),error='历史任务编号重复/无效；保留证据并重新编号'))
                rid=self.next_id
            kind=meta.get('kind','scan' if a.total==a.scene_height*a.scene_width else 'region')
            rect=None if kind=='scan' else [a.y,a.x,a.height,a.width]
            rr,cc=np.mgrid[a.y:a.y+a.height,a.x:a.x+a.width]
            run=Run(rid,kind,a.scene,meta.get('version',a.identity['model']),rect,np.stack([rr.ravel(),cc.ravel()],1),a.scene_height,a.scene_width,'board')
            run.board_job=job;run.lock=job.lock
            run.origin=meta.get('origin')
            run.t0=meta.get('t0',run.t0)
            run.t_end=datetime.fromisoformat(job.ended).timestamp() if job.ended else time.time()
            run.status=job.state
            for y,words in a.rows.items():
                for x,word in enumerate(words):
                    if word is not None:
                        run.pred[y,x]=(word&255)+1;run.conf[y,x]=(word>>16)/65536;run.done[y,x]=True
            run.n=a.count;run.row=a.y+a.reported_done//a.width
            # Restored files are history, never the current live board task.
            self.runs[rid]=run;self.next_id=max(self.next_id,rid+1)


S = State()


def uart_ready(boot):
    with S.control_lock:
        if S.source is not S.board_source:
            raise ValueError('Source changed during UART identity capture; no automatic task')
        build=UART.snapshot().get('build')
        if not build:raise ValueError('Reviewed App BUILD identity missing; no automatic task')
        gate=S.board_source.authorize(boot,True,build['release_id'])
    emit_json(dict(type='board_gate',source=gate))


UART = uart_capture.Capture(ROOT/'build/host/gcs_uart',uart_ready)


def emit_json(msg):
    if S.loop:
        S.loop.call_soon_threadsafe(S.out.put_nowait, json.dumps(msg, ensure_ascii=False))


def log(msg, level='info'):
    emit_json(dict(type='log', level=level, msg=msg, t=time.strftime('%H:%M:%S')))


async def sender():
    while True:
        m = await S.out.get()
        dead = []
        for ws in list(S.clients):
            try:
                if isinstance(m, bytes):
                    await ws.send_bytes(m)
                else:
                    await ws.send_text(m)
            except Exception:       # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            S.clients.discard(ws)


async def ticker():
    last_n, last_t, last_id = 0, time.time(), None
    while True:
        await asyncio.sleep(0.25)
        if time.monotonic()-getattr(S,'dp_last_sync',0)>1:
            S.dp_last_sync=time.monotonic()
            await asyncio.to_thread(sync_dp_selection)
        if not S.clients:
            continue
        S.board_source.display_observer_until=time.monotonic()+3
        r = S.run
        now = time.time()
        msg = dict(type='tick', telemetry=S.source.telemetry(), source=S.source.describe(), uart=UART.snapshot(),board_records_protocol=1,
                   speed_compare=S.speed.snapshot())
        if r is not None:
            s = r.summary()
            if r.id!=last_id:last_n=0;last_t=r.t0;last_id=r.id
            dn = max(0,r.n - last_n) if r.status == 'running' else 0
            s['rate'] = dn / max(now - last_t, 1e-6)
            s['compute_rate'] = r.n / r.compute_s if r.compute_s > 0 else None
            msg['run'] = s
            last_n = r.n
        last_t = now
        await S.out.put(json.dumps(msg, ensure_ascii=False))


def key_version(scene):
    """Prefer the displayed task model; otherwise the first registered export."""
    ids=[v['id'] for v in E.VERSIONS[scene]]
    if S.run and S.run.scene==scene and S.run.version in ids:
        ids.remove(S.run.version);ids.insert(0,S.run.version)
    for version in ids:
        try:candidate,_=S.board_source.candidate(scene,version)
        except (ValueError,KeyError,OSError):continue
        if board_models.registered(candidate,S.board_source.registry):return version
    raise ValueError('当前场景没有已登记的配套模型；请先下发权重')


def execute_key(event):
    speed_guard()
    owner=S.board_source;scene=event['scene'];gesture=event['gesture'];key=event['key']
    S.key_thread=threading.get_ident()
    owner.key_thread=S.key_thread
    def check():
        if owner is not S.board_source or S.source is not owner or (event['boot_id'],event['session'])!=(owner.boot,owner.session):
            raise ValueError('按键对应的板卡连接已改变')
        if not owner.healthy or not owner.channel_ready:raise ValueError('板卡连接尚未就绪')
    def wait_for(predicate,timeout):
        deadline=time.monotonic()+timeout
        while not predicate():
            check()
            if time.monotonic()>deadline:raise ValueError('等待板卡确认超时；未自动重发任务')
            time.sleep(.05)
    check()
    if owner.operation and not owner.operation.complete:raise ValueError('模型事务尚未结束')
    if gesture==3:
        # Physical long hold is the explicit switch request. Stop safely and
        # retain the partial result before activating the next scene.
        S.key_context=dict(type='key_action',state='preparing',action='scene',event=event,scene=scene)
        emit_json(S.key_context)
        with S.control_lock:
            current=S.run
            if current and current.status in ('running','paused'):owner.stop()
        if current:
            wait_for(lambda:current.status not in ('running','paused'),90)
            if S.run is not current:raise ValueError('任务已由网页切换，本次切景未继续')
        scene=board_keys.SCENES[(board_keys.SCENES.index(scene)+1)%3]
        with S.control_lock:
            check();version=key_version(scene)
            # Select a registered scene/model without loading its 244--491 MB
            # cube. The next real START retains full activation and CRC checks.
        S.key_preview=True
        S.dp_selection=None
        with owner.lock:
            owner.display_pending=None;owner.display_status=dict(state='idle')
        S.key_context=dict(type='key_action',state='done',action='scene',event=event,scene=scene,version=version)
        emit_json(S.key_context)
        owner.finish_key(event,code=10,scene=scene)
        log(f'KEY{key} 长按：已选中 {scene} / {version}；首次识别时加载输入，原任务结果保留')
        return
    version=key_version(scene)
    meta=business_metadata(scene);height,width=meta['shape']
    if key==5 and gesture==1:
        import secrets
        row,col=secrets.randbelow(height),secrets.randbelow(width)
        with S.control_lock:
            check();run=S.run
            reusable=run and owner.job is run.board_job and run.scene==scene and run.version==version and not getattr(S,'key_preview',False)
            if reusable:
                owner.probe(run.board_job,row,col)
        if not reusable:
            result=api_board_point_probe(dict(confirmed=True,scene=scene,version=version,row=row,col=col,origin='board_keys'))
            run=S.runs[result['run']['id']]
        S.key_preview=False
        S.key_context=dict(type='key_action',state='started',action='point',event=event,scene=scene,version=version,row=row,col=col,run=run.summary())
        emit_json(S.key_context)
        wait_for(lambda:run.board_job.probe_result and run.board_job.probe_result['state'] in ('done','error'),90)
        if run.board_job.probe_result['state']!='done':raise ValueError(run.board_job.probe_result.get('error') or '单点探查失败')
    else:
        with S.control_lock:
            check()
            if S.run and S.run.status in ('running','paused'):raise ValueError('当前任务运行中，请等待完成；长按可停止并切景')
            if key==5:
                action='scan';rect=None;parcel=None
            elif gesture==1:
                action='region';rect=board_keys.rectangle(scene,height,width);parcel=None
            else:
                action='parcel';rect,points=board_keys.polygon(scene,height,width)
                ledger=S.parcels.load(scene,meta['shape'])
                parcel=dict(id='key_'+uuid.uuid4().hex,name=f'按键地块 {len(ledger["parcels"])+1}',pts=points)
                # Optimistic save appends to the latest ledger; never replace
                # manual parcels with a cached page or a random demonstration.
                S.parcels.save(scene,meta['shape'],ledger['parcels']+[parcel],ledger['revision'])
            run=start_run(dict(kind='scan' if action=='scan' else 'region',scene=scene,version=version,rect=rect,origin='board_keys'))
            S.key_preview=False
            if parcel:S.dp_selection=dict(rid=run.id,parcel_id=parcel['id'],threshold=.6)
        S.key_context=dict(type='key_action',state='started',action=action,event=event,scene=scene,version=version,rect=rect,
                           parcel_id=parcel['id'] if parcel else None,threshold=.6 if parcel else None,run=run.summary())
        emit_json(S.key_context)
        wait_for(lambda:run.n>0 or run.status not in ('running','paused'),90)
        if not run.n:raise ValueError('板卡未返回任务像素，请检查任务错误；未自动重发')
    owner.finish_key(event)
    log(f'KEY{key}：{"单点探查" if key==5 and gesture==1 else "整景巡检" if key==5 else "随机区域" if gesture==1 else "随机地块识别"} 已执行')


async def key_dispatcher():
    while True:
        await asyncio.sleep(.05)
        event=S.board_source.take_key()
        if event is None:continue
        owner=S.board_source
        owner.key_executing=True
        try:
            await asyncio.to_thread(execute_key,event)
        except Exception as exc:
            message=str(getattr(exc,'detail',exc));code=2 if '运行中' in message or '事务' in message else 4
            S.board_source.finish_key(event,state=4,code=code)
            emit_json(dict(type='key_action',state='error',event=event,error=message))
            log(f'KEY{event["key"]} 未执行：{message}','error')
        finally:owner.key_executing=False


@app.on_event('startup')
async def startup():
    S.loop = asyncio.get_running_loop()
    S.out = asyncio.Queue()
    asyncio.create_task(sender())
    asyncio.create_task(ticker())
    asyncio.create_task(key_dispatcher())


@app.on_event('shutdown')
async def shutdown():
    try:S.board_source.shutdown()
    finally:UART.stop()


def controlled(fn, cmd):
    with S.control_lock:
        return fn(cmd)


@app.middleware('http')
async def no_cache(request, call_next):
    """前端文件每次向服务端校验（ETag 未变则 304），改了 JS/CSS 刷新即生效。"""
    resp = await call_next(request)
    if request.url.path == '/' or request.url.path.startswith('/web/'):
        resp.headers['Cache-Control'] = 'no-cache'
    return resp


# ---------- REST ----------

@app.get('/')
def index():
    return FileResponse(HERE / 'web' / 'index.html')


app.mount('/web', StaticFiles(directory=HERE / 'web'), name='web')


@app.get('/api/state')
def api_state():
    context=dict(S.key_context) if S.key_context else None
    if context and context.get('run') and context['run']['id'] in S.runs:
        context['run']=S.runs[context['run']['id']].summary()
    return dict(scenes=list(E.VERSIONS), device=eng.device_name, source=S.source.describe(),key_context=context,
                run=S.run.summary() if S.run else None, runs=[r.summary() for r in S.runs.values()],
                board_gate=S.board_source.describe(), uart=UART.snapshot(), history_errors=S.history_errors,
                model_catalog_errors=S.model_catalog_errors, service='gcs-s2c-roi',board_records_protocol=1,speed_compare=S.speed.snapshot())


def speed_guard():
    comparison=getattr(S,'speed',None)
    if comparison and comparison.busy and comparison.thread_id!=threading.get_ident():
        raise ValueError('速度对比正在独占板卡；请等待完成或先停止对比')


@app.get('/api/speed')
def api_speed():
    return dict(current=S.speed.snapshot(),history=S.speed.history())


@app.get('/api/speed/history/{name}')
def api_speed_history(name:str):
    try:return S.speed.load(name)
    except (ValueError,OSError) as exc:raise HTTPException(404,str(exc)) from exc


@app.post('/api/speed/start')
def api_speed_start(cmd:dict):
    try:
        with S.control_lock:
            speed_guard()
            if S.source is not S.board_source:raise ValueError('请先连接板卡')
            if S.run and S.run.status in ('running','paused'):raise ValueError('请先停止或等待当前任务完成')
            scene,versions,rect=cmd['scene'],cmd['versions'],cmd['rect']
            if not isinstance(versions,list) or len(versions)!=2:raise ValueError('请选择两个权重')
            for version in versions:
                S.board_source.validate(dict(kind='region',scene=scene,version=version,rect=rect))
            owner=S.board_source;boot=owner.boot;session=owner.session
            def check():
                if S.source is not owner or owner.boot!=boot or (session is not None and owner.session!=session) or not owner.healthy or not owner.channel_ready:
                    raise ValueError('板卡连接已改变或不可用，停止本次对比')
            def start(version,identity):
                nonlocal session
                with S.control_lock:
                    check()
                    result=start_run(dict(kind='region',scene=scene,version=version,rect=rect,origin='speed:'+identity))
                    session=owner.session
                    return result
            def stop(run):
                with S.control_lock:
                    if S.run is run and run.status in ('running','paused') and not run.board_job.command:owner.stop()
            return S.speed.start(scene,versions,rect,start,stop,check)
    except (ValueError,KeyError,TypeError,OSError) as exc:raise HTTPException(409,str(exc)) from exc


@app.post('/api/speed/stop')
def api_speed_stop():
    S.speed.stop()
    return dict(ok=True)


@app.get('/api/uart/ports')
def api_uart_ports():
    return UART.ports()  # enumeration only, no connection


@app.post('/api/uart/start')
def api_uart_start(cmd: dict):
    try:
        with S.control_lock:
            connect_board=cmd.get('connect_board') is True
            if (S.board_source.describe()['active']
                or (S.run is not None and S.run.status in ('running','paused'))
                or (S.source is not S.board_source and not connect_board)):
                raise ValueError('Select idle board source; active UDP task/session cannot be taken over')
            if UART.snapshot()['active']:
                raise ValueError('UART already connected')
            if cmd.get('confirmed') is not True:
                raise ValueError('Confirm exclusive UART0 and user cold startup first')
            # User clicks after Build, BEFORE cold startup. Audit source/ELF
            # without Build/link/download; refuse old/bad ELF before opening COM.
            build_receipt=gcs_release.audited_elf(loaded_assets=LOADED_RELEASE_ASSETS)
            # Invalidate a previous unconsumed manual gate before this new boot.
            previous=S.board_source.boot
            S.board_source.boot=None
            try:
                result=UART.start(cmd.get('port'),cmd.get('baudrate'),cmd.get('confirmed'),str(build_receipt))
                # Explicit Connect board click selects the idle board source;
                # page load/restoration never does. No UDP or inference here.
                if connect_board and S.source is not S.board_source:
                    S.source=S.board_source
                    S.run=None
                    emit_json(dict(type='source',source=S.source.describe()))
                return result
            except (ValueError,OSError):
                S.board_source.boot=previous
                raise
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(409,str(exc)) from exc


@app.post('/api/uart/stop')
def api_uart_stop():
    try:return UART.stop()  # do not hold control lock while joining worker
    except RuntimeError as exc:raise HTTPException(409,str(exc)) from exc


@app.post('/api/board/sd_connect')
def api_sd_connect(cmd: dict):
    # Retained API alias; no false SD claim is made by the normal JTAG UI.
    return api_board_connect(dict(cmd,boot_method='sd'))


@app.post('/api/board/connect')
def api_board_connect(cmd: dict):
    try:
        with S.control_lock:
            if cmd.get('confirmed') is not True:raise ValueError('请确认已由你启动应用；不会自动连接或启动任务')
            method=cmd.get('boot_method')
            if method not in ('jtag','sd'):raise ValueError('请如实选择JTAG或SD启动方式')
            if UART.snapshot()['active'] or S.board_source.describe()['active'] or (S.run is not None and S.run.status in ('running','paused')):
                raise ValueError('Existing UART/task/model owner; cannot replace it')
            build_receipt=gcs_release.audited_elf(loaded_assets=LOADED_RELEASE_ASSETS)
            S.board_source.boot=None
            build=board_release.expected_build(build_receipt)
            found=board_boot.connect(ROOT/'build/host/gcs_network_boot',S.board_source.addr,True,method,build,build_receipt)
            if not found.get('ready'):
                return dict(source=S.board_source.describe(),discovery=found,ready=False,uart_opened=False)
            source=S.board_source.authorize(found['boot_id'],True,build['release_id'],network_startup=found['evidence'],build_evidence=str(build_receipt),
                terminal_info=found['info'] if found.get('terminal_reconnect') else None)
            if found.get('terminal_reconnect'):S.board_source.resume_terminal(found['info'])
            S.source=S.board_source
            S.run=None
            S.key_context=None;S.key_preview=False;S.dp_selection=None
            # Read-only registry/heartbeat owner also carries real temperature;
            # this does not upload, activate weights, or START an inference.
            S.board_source.request_models('query',on_update=model_event)
            emit_json(dict(type='source',source=source))
            return dict(source=source,discovery=found,ready=True,build_evidence=str(build_receipt),uart_opened=False,
                note='Ethernet INFO and CRC-checked actual board records only; start explicitly. No UART required.')
    except (ValueError,OSError,RuntimeError) as exc:raise HTTPException(409,str(exc)) from exc


@app.post('/api/board/authorize')
def api_authorize(cmd: dict):
    # Local PC permission only. Does not open a UDP socket or start inference.
    try:
        with S.control_lock:
            if isinstance(S.board_source, board_task.BoardSource):
                raise ValueError('请通过连接板卡核对启动版本；不能手工跳过版本检查')
            if UART.snapshot()['active']:
                raise ValueError('UART helper owns identity acquisition; do not also enter a manual boot_id')
            result = S.board_source.authorize(cmd.get('boot_id', ''), cmd.get('board_started'))
        emit_json(dict(type='board_gate', source=result))
        return result
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get('/api/run/{rid}/board')
def api_board_result(rid: int):
    job = _run(rid).board_job
    if job is None:
        raise HTTPException(400, 'Not a board run')
    return job.snapshot()


@app.get('/api/run/{rid}/board.csv')
def api_board_csv(rid: int):
    return Response('\ufeff' + board_task.csv_text(api_board_result(rid)), media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="board_run_{rid}.csv"'})


def task_phase_timing(job,snapshot=None):
    if job is None:return board_timing.unavailable('没有板卡任务')
    with job.lock:
        snapshot=job.snapshot(False) if snapshot is None else snapshot
        evidence=(job.host_run or {}).get('uart_evidence')
        network=(snapshot.get('board_log') or {}).get('evidence')
        network_required=bool((job.host_run or {}).get('network_startup'))
    if network or network_required:
        state=snapshot.get('board_log') or {}
        if state.get('state')!='ready' or not network:
            return board_timing.unavailable('以太网板端记录尚未核验：'+str(state.get('error') or state.get('state') or '未回读'))
        try:
            path=Path(network).resolve()
            if not path.is_relative_to((job.out/'board_logs').resolve()):raise ValueError('板端记录路径不属于此任务')
            return board_timing.from_network(snapshot,path)
        except (OSError,ValueError,KeyError,TypeError) as exc:return board_timing.unavailable('以太网计时记录未核验：'+str(exc))
    receipt=UART.snapshot()
    if not evidence and receipt.get('boot_id')==snapshot.get('boot_id'):evidence=receipt.get('evidence')
    if not evidence:return board_timing.unavailable('缺少本任务UART记录；不以PC耗时回填')
    try:
        raw=(Path(evidence)/'uart.txt').read_bytes()
        result=board_timing.from_snapshot(snapshot,raw.decode('utf-8-sig'))
        result['uart_raw_sha256']=hashlib.sha256(raw).hexdigest();return result
    except (OSError,ValueError,KeyError,TypeError) as exc:return board_timing.unavailable('计时记录未核验：'+str(exc))


@app.get('/api/run/{rid}/timing')
def api_task_timing(rid:int):
    # Reads an already captured artifact. GET never opens a socket or UART.
    return task_phase_timing(_run(rid).board_job)


def network_task_records(job,refresh=False):
    """Explicit live refresh stays on the sole owner; history is file-only."""
    if job is None or not ((job.host_run or {}).get('network_startup') or job.board_log_evidence):
        raise ValueError('本任务没有以太网启动/板端记录；不能伪造或回退到串口')
    refreshed=False
    if refresh and S.board_source.job is job and S.board_source.describe()['active']:
        S.board_source.read_evidence(job);refreshed=True
    with job.lock:
        if job.state not in ('done','stopped') or job.error or job.command or job.recovering:
            raise ValueError('只能核验健康终态任务，不接管运行任务')
        if job.probe_result and job.probe_result['state'] in ('queued','running'):
            raise ValueError('请等待探查结束，不能读取仍变化的证据')
        if job.board_log_state!='ready' or not job.board_log_evidence:
            raise ValueError('板端记录不完整：'+str(job.board_log_error or job.board_log_state))
        path=Path(job.board_log_evidence).resolve()
        if not path.is_relative_to((job.out/'board_logs').resolve()):raise ValueError('板端记录路径不属于此任务')
        board_log.audit(path,job.audit.boot,job.audit.session,job.audit.task)
        return path,refreshed


@app.post('/api/run/{rid}/board/records')
def api_board_records(rid:int):
    try:
        with S.control_lock:
            job=_run(rid).board_job;_,refreshed=network_task_records(job,refresh=True)
            return dict(board_log=job.snapshot(False)['board_log'],refreshed=refreshed,uart_opened=False)
    except (ValueError,OSError,RuntimeError) as exc:raise HTTPException(409,str(exc)) from exc


@app.post('/api/run/{rid}/board/probe')
def api_board_probe(rid: int, cmd: dict):
    try:
        with S.control_lock:
            speed_guard()
            if S.source is not S.board_source:
                raise ValueError('Select board source first; no PC fallback')
            run = _run(rid)
            if 'model_scene' in cmd or 'model_version' in cmd:
                if not isinstance(S.board_source,board_link.BoardSource):raise ValueError('旧连接不支持跨模型探查')
                candidate,_=S.board_source.candidate(cmd['model_scene'],cmd['model_version'])
                result=S.board_source.probe(run.board_job,cmd.get('row'),cmd.get('col'),board_models.candidate_identity(candidate))
            else:result = S.board_source.probe(run.board_job, cmd.get('row'), cmd.get('col'))
        return result
    except (ValueError, KeyError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post('/api/board/session/close')
def api_board_close():
    try:
        with S.control_lock:
            speed_guard()
            S.board_source.close()
        return S.board_source.describe()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post('/api/board/point-probe')
def api_board_point_probe(cmd: dict):
    """Explicit click: receive a real 1x1 task, then request its full PL probe."""
    try:
        with S.control_lock:
            speed_guard()
            if cmd.get('confirmed') is not True:
                raise ValueError('请明确点击发送单点探查')
            if S.source is not S.board_source or not isinstance(S.source,board_link.BoardSource):
                raise ValueError('请先连接支持单点探查的板卡')
            row,col=cmd.get('row'),cmd.get('col')
            if type(row) is not int or type(col) is not int:
                raise ValueError('探查行列必须为整数')
            request=dict(kind='region',scene=cmd['scene'],version=cmd['version'],rect=[row,col,1,1],pace_rows=0,origin=cmd.get('origin'))
            board_task.rect_for(request)  # reject bounds before any START
            run=start_run(request)
        deadline=time.monotonic()+90
        while run.status in ('running','paused'):
            if S.run is not run or S.source is not S.board_source:
                raise ValueError(f'任务 #{run.id} 已切换；未追加探查')
            if time.monotonic()>=deadline:
                raise ValueError(f'任务 #{run.id} 尚未完成，请查看任务状态；不会自动重发')
            time.sleep(.05)
        with S.control_lock:
            if S.run is not run or S.source is not S.board_source:
                raise ValueError(f'任务 #{run.id} 已切换；未追加探查')
            if run.status!='done' or run.n!=1:
                raise ValueError(f'任务 #{run.id} 未完整收到单点像素，请查看任务错误')
            result=S.board_source.probe(run.board_job,row,col)
            return dict(run=run.summary(),probe=result)
    except (ValueError,KeyError,OSError,RuntimeError) as exc:
        raise HTTPException(409,str(exc)) from exc


@app.post('/api/run/{rid}/board/acceptance')
def api_board_acceptance(rid: int, cmd: dict):
    """User-clicked read-only evidence check; never UART/UDP/task execution."""
    try:
        job=_run(rid).board_job
        if isinstance(job,board_task.Job):
            return task_acceptance(rid,job,cmd)
        if not job or not job.full or job.state!='done' or not job.out:
            raise ValueError('This entry requires a completed new full-scene task; old ROI PASS is not rerun')
        receipt=UART.snapshot()
        if receipt['boot_id']!=f'{job.audit.boot:08x}' or not receipt['evidence'] or receipt['error']:
            raise ValueError('Matching UART capture missing or failed; do not rerun inference to hide the gap')
        import gcs_scene_verify as verifier
        import gcs_probe_verify
        uart=Path(receipt['evidence'])/'uart.txt'
        report=verifier.verify(job.out,uart)
        report['probe']=gcs_probe_verify.verify(job.out,uart.read_text(encoding='utf-8-sig'))
        if any(cmd.get(k)!=report[k] for k in ('boot_id','session','task','browser_words_sha256')):
            raise ValueError('Browser full words/seen mask or identity differs from received UDP data')
        # Verify the actual JSON bytes that will be placed in the downloadable
        # package, not a histogram or a claim that the UI has already downloaded it.
        exported=(job.out/'summary.json').read_bytes()
        verifier.verify_export(json.loads(exported),job.snapshot())
        checks=report['checks'];checks.pop('downloaded_gcs_json_exact')
        checks.update(browser_220000_raw_words_and_seen_exact=True,packaged_json_exact=True)
        report.update(data_acceptance=all(checks.values()),missing=[],
            batch_acceptance=all(checks.values()) and report['s3']['passed'] and report['probe']['passed'],
            packaged_export_sha256=hashlib.sha256(exported).hexdigest(),
            scope='FULL_SCENE_DATA_UART_UDP_BROWSER_EXPORT_ONLY',
            not_covered=['DP visual acceptance','task controls/recovery','model update','Test100/OA','full first release'])
        (job.out/'data_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        with zipfile.ZipFile(job.out/'data_acceptance.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('gcs_export.json',exported)
            for name in ('data_acceptance.json','session.json','packets.jsonl','results.csv'):
                archive.write(job.out/name,name)
            if (job.out/'interaction.json').exists():archive.write(job.out/'interaction.json','interaction.json')
            archive.write(uart,'uart.txt')
        return dict(report=report,download=f'/api/run/{rid}/board/acceptance.zip')
    except (ValueError,KeyError,OSError) as exc:
        raise HTTPException(409,str(exc)) from exc


def task_acceptance(rid, job, cmd):
    import gcs_task_verify
    network=None
    if (job.host_run or {}).get('network_startup') or job.board_log_evidence:
        network,_=network_task_records(job,refresh=True)
    with job.lock:
        if job.state not in ('done','stopped') or job.error or job.command or job.recovering:
            raise ValueError('仅核验终态且无未决指令/错误的任务；保留部分结果')
        if job.probe_result and job.probe_result['state'] in ('queued','running'):
            raise ValueError('请等待探查结束，不能打包仍变化的证据')
        if network:
            evidence=network;uart_bytes=(network/'board_log.txt').read_bytes()
        else:
            receipt=UART.snapshot()
            evidence=(job.host_run or {}).get('uart_evidence')
            if not evidence and receipt.get('boot_id')==f'{job.audit.boot:08x}':evidence=receipt.get('evidence')
            if not evidence:raise ValueError('缺少历史任务记录；不会自动补跑或补造')
            uart_bytes=(Path(evidence)/'uart.txt').read_bytes()
        uart=job.out/('board_log_snapshot.txt' if network else 'uart_snapshot.txt')
        uart.write_bytes(uart_bytes)
        release_file=None
        if ('app='+gcs_release.APP_ID).encode() in uart_bytes.lower():
            release_file=job.out/'elf_audit.json';raw=(Path(evidence)/'elf_audit.json').read_bytes()
            if release_file.exists() and release_file.read_bytes()!=raw:raise ValueError('本任务已有不同的App/ELF证据；保留原记录并停止')
            release_file.write_bytes(raw)
        snapshot=job.snapshot()
        board_task.save_json(job.out/'summary.json',snapshot)
        report=gcs_task_verify.verify(job.out,uart,elf_audit=release_file,network_log=network)
        if any(cmd.get(k)!=report[k] for k in ('boot_id','session','task','browser_words_sha256')):
            raise ValueError('浏览器原始字/掩码/任务身份与日志不一致')
        report['checks']['browser_raw_words_and_seen_exact']=True
        board_task.save_json(job.out/'data_acceptance.json',report)
        (job.out/'results.csv').write_text(board_task.csv_text(snapshot),encoding='utf-8-sig')
        # Hold the same producer lock through the entire archive snapshot.
        with zipfile.ZipFile(job.out/'data_acceptance.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
            files={name:(job.out/name).read_bytes() for name in ('data_acceptance.json','session.json','packets.jsonl','summary.json','results.csv')}
            if network:
                for name in ('packets.jsonl','receipt.json','boot_log.bin','task_log.bin','board_log.txt','elf_audit.json'):
                    files['board_log/'+name]=(network/name).read_bytes()
            else:files['uart.txt']=uart_bytes
            if release_file:files['elf_audit.json']=release_file.read_bytes()
            files['gcs_export.json']=files['summary.json']
            manifest={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
            for name,data in files.items():archive.writestr(name,data)
            archive.writestr('sha256.json',json.dumps(manifest,indent=2))
        return dict(report=report,download=f'/api/run/{rid}/board/acceptance.zip')


@app.get('/api/run/{rid}/board/acceptance.zip')
def api_board_acceptance_zip(rid: int):
    job=_run(rid).board_job
    if not job or not job.out or not (job.out/'data_acceptance.zip').is_file():
        raise HTTPException(404,'No verified data package for this run')
    return FileResponse(job.out/'data_acceptance.zip',filename=f'board_{rid}_data_acceptance.zip')


@app.get('/api/run/{rid}/board_words')
def api_board_words(rid: int):
    r=_run(rid)
    if r.board_job is None:raise HTTPException(400,'Not a board run')
    with getattr(r.board_job,'lock',r.lock):
        words=np.zeros(r.pred.shape,dtype='<u4');seen=np.zeros(r.pred.shape,dtype=np.uint8)
        for y,row in r.board_job.audit.rows.items():
            for x,word in enumerate(row):
                if word is not None:words[y,x]=word;seen[y,x]=1
        return Response(words.tobytes()+seen.tobytes(),media_type='application/octet-stream')


@app.post('/api/run/{rid}/board/recover')
def api_board_recover(rid: int, cmd: dict):
    try:
        with S.control_lock:
            run=_run(rid);job=run.board_job
            if not job or not isinstance(job,board_task.Job):raise ValueError('只支持新版任务恢复')
            identity=job.snapshot(False)
            if any(cmd.get(k)!=identity[k] for k in ('boot_id','session','task','wcrc')):
                raise ValueError('恢复确认身份不一致')
            # Older retained results remain read-only. INFO must match the most
            # recent task; never revive an older task or reuse a START number.
            if any(r.board_job and r.board_job.audit.boot==job.audit.boot and r.board_job.audit.task>job.audit.task for r in S.runs.values()):
                raise ValueError('已有更新任务；旧任务仅可查看/导出')
            receipt={} if (job.host_run or {}).get('network_startup') else UART.snapshot()
            if receipt.get('boot_id')==identity['boot_id'] and receipt.get('error'):
                raise ValueError('UART 已记录失败，不能恢复清除故障')
            if cmd.get('confirmed') is not True:raise ValueError('请明确确认恢复此任务')
            reviewed=board_release.expected_build(gcs_release.audited_elf(loaded_assets=LOADED_RELEASE_ASSETS))
            S.board_source.release_id=reviewed['release_id']
            run.lock=S.board_source.lock
            result=S.board_source.recover(job,cmd.get('confirmed'),run_callbacks(run))
            S.source=S.board_source;S.run=run
            if run.status in ('running','paused'):run.t_end=None
            return result
    except (ValueError,KeyError,OSError) as exc:raise HTTPException(409,str(exc)) from exc


@app.get('/api/scene/{name}')
def api_scene(name: str):
    sc = eng.get_scene(name)
    info = sc.info()
    info['display_classes']=display_labels.names(name,info['classes'],info['palette'])
    recipe=E.closed_loop_info(name)
    # Public UI gets the recipe, not historical CPU accuracy/reference scores.
    # Training provenance stays in its original local files, never board grades.
    info['closed_loop']=None if not recipe else dict(region={k:recipe['region'][k] for k in
        ('scene','model','seed','hold_class','hold_name','official_train','official_test','region') if k in recipe['region']})
    for v in info['versions']:
        try:
            candidate,_=board_link.local_candidate(name,v['id'])
            v.update(pkg_bytes=sum(p['bytes'] for p in candidate['parts']),deployable=True,board_candidate=candidate,deploy_error=None)
        except (OSError,ValueError,KeyError,TypeError) as exc:v.update(pkg_bytes=None,deployable=False,deploy_error=str(exc))
    return info


@app.get('/api/scene/{name}/gt')
def api_gt(name: str):
    return Response(eng.get_scene(name).gt.tobytes(), media_type='application/octet-stream')


@app.get('/api/scene/{name}/split')
def api_split(name: str):
    sc = eng.get_scene(name)
    m = sc.train_mask.astype(bool).astype(np.uint8) | (sc.test_mask.astype(bool).astype(np.uint8) << 1)
    return Response(m.tobytes(), media_type='application/octet-stream')


@app.get('/api/scene/{name}/rgb')
def api_rgb(name: str):
    return FileResponse(HERE / 'scenes' / name / 'rgb.png')


@app.get('/api/scene/{name}/library')
def api_library(name: str):
    sc = eng.get_scene(name)
    return dict(wavelengths=sc.wavelengths, library=sc.library, classes=sc.classes)


@app.get('/api/scene/{name}/cube/edges')
def api_cube_edges(name: str, r0: int = 0, c0: int = 0, h: int = 0, w: int = 0):
    sc = eng.get_scene(name)
    return Response(sc.cube_edges(*sc.clip_rect(r0, c0, h, w)), media_type='application/octet-stream')


@app.get('/api/scene/{name}/cube/band/{b}')
def api_cube_band(name: str, b: int, r0: int = 0, c0: int = 0, h: int = 0, w: int = 0):
    sc = eng.get_scene(name)
    return Response(sc.band_image(max(0, min(b, sc.B - 1)), *sc.clip_rect(r0, c0, h, w)), media_type='application/octet-stream')


@app.get('/api/probe')
def api_probe(scene: str, version: str, r: int, c: int):
    raise HTTPException(409, '请使用当前任务的单点探查')


@app.get('/api/scene/{name}/input-point')
def api_input_point(name: str, r: int, c: int):
    """Read local input only; this endpoint never calls eng.probe or board PROBE."""
    try:
        return INPUTS.point(name, r, c)
    except (ValueError, OSError) as exc:
        raise HTTPException(409, f'Local input unavailable: {exc}') from exc


def _run(rid):
    r = S.runs.get(rid)
    if r is None:
        raise KeyError(rid)
    return r


@app.get('/api/run/{rid}/analysis')
def api_analysis(rid: int, conf_thr: float = 0.6, min_px: int = 6):
    try:
        t0 = time.perf_counter()
        result, _, meta = business_result(rid)
        res = board_agri.analyze(result, meta['gsd_m'], conf_thr, min_px)
        res['ms'] = (time.perf_counter()-t0)*1000  # CPU business analysis, NOT board compute timing
        return res
    except (ValueError, KeyError, OSError) as exc:raise HTTPException(409, str(exc)) from exc


def business_metadata(scene):
    """Existing scene metadata only; never load a PC model/cube for statistics."""
    if scene not in E.MISSION:raise ValueError('Unknown scene')
    meta = json.loads((HERE/'scenes'/scene/'palette.json').read_text(encoding='utf-8'))
    names = display_labels.names(scene,meta['classes'][1:],meta['colors'])
    return dict(shape=(meta['height'], meta['width']), classes=names, palette=meta['colors'],
                gsd_m=E.MISSION[scene]['gsd_m'])


def business_result(rid):
    run = _run(rid)
    if run.source != 'board' or run.board_job is None:raise ValueError('只支持实际收到的板卡任务结果')
    meta = business_metadata(run.scene)
    with getattr(run.board_job, 'lock', run.lock):
        snapshot = run.board_job.snapshot()
        summary = dict(id=run.id, kind=run.kind, scene=run.scene, version=run.version,
                       status=snapshot['status'], elapsed=(run.t_end or time.time())-run.t0)
    expected_model=run.board_job.audit.identity['model'] if snapshot.get('model_lifecycle') else run.version
    if (snapshot.get('scene'), snapshot.get('model')) != (run.scene, expected_model):
        raise ValueError('Run and raw board scene/model differ')
    return board_agri.BoardResult(snapshot, meta['shape'], meta['classes']), summary, meta


def sync_dp_selection():
    selection=getattr(S,'dp_selection',None)
    if selection is None:return
    try:
        run=S.run
        if not run or run.id!=selection['rid']:S.dp_selection=None;return
        owner=S.board_source
        if owner.display_pending or not owner.channel_ready:return
        result,_,meta=business_result(run.id)
        ledger=S.parcels.load(run.scene,meta['shape'])
        parcel=next((p for p in ledger['parcels'] if p['id']==selection['parcel_id']),None)
        row=None
        if parcel:
            row=board_agri.parcel_rows(result,[parcel],meta['gsd_m'],selection['threshold'])[0]
        bits=display_name.bitmap(parcel['name']) if parcel else bytes(576)
        owner.queue_display(run.board_job,ledger['revision'],parcel,row,selection['threshold'],bits)
        if not parcel:S.dp_selection=None
    except (ValueError,KeyError,OSError,subprocess.SubprocessError) as exc:
        S.board_source.display_status=dict(state='error',error=str(exc))


@app.post('/api/dp/selection')
def api_dp_selection(cmd:dict):
    try:
        with S.control_lock:
            run=S.run
            if not run or cmd.get('run_id')!=run.id:raise ValueError('请选择当前板卡任务，历史任务不能覆盖 DP')
            ledger=S.parcels.load(run.scene,business_metadata(run.scene)['shape'])
            if cmd.get('revision')!=ledger['revision']:raise ValueError('台账已更新，请重新加载后选择')
            pid=cmd.get('parcel_id')
            if pid is not None and not any(p['id']==pid for p in ledger['parcels']):raise ValueError('请先绘制并保存有效地块')
            threshold=cmd.get('threshold',.6);board_agri.parameters(1,threshold)
            if not S.board_source.channel_ready:raise ValueError('请先在开始按钮旁恢复当前任务连接')
            S.dp_selection=dict(rid=run.id,parcel_id=pid,threshold=threshold)
            sync_dp_selection()
            return dict(selection=S.dp_selection,status=S.board_source.display_status)
    except (ValueError,KeyError,OSError) as exc:raise HTTPException(409,str(exc)) from exc


@app.get('/api/dp/frame.png')
def api_dp_frame():
    try:
        owner=S.board_source
        request=owner.request_mirror()
        previous=owner.mirror_at;deadline=time.monotonic()+13
        while owner.mirror_request and time.monotonic()<deadline:time.sleep(.02)
        if owner.mirror_at<=previous or not owner.mirror_png:raise ValueError('DP 镜像读取超时，保留上一次画面')
        return Response(owner.mirror_png,media_type='image/png',headers={'Cache-Control':'no-store','X-DP-Frame':str(request)})
    except (ValueError,OSError) as exc:raise HTTPException(409,str(exc)) from exc


@app.get('/dp')
def api_dp_page():
    return FileResponse(HERE/'web/dp.html')


def business_labels(result):
    test, manifest = board_metrics.load_labels(scene=result.identity['scene'])
    if test.shape != result.shape or len(manifest['classes']) != len(result.classes):raise ValueError('Evaluation/scene mismatch')
    return test, manifest


def business_compare(ra, rb):
    try:test, manifest = business_labels(ra)
    except (ValueError, KeyError, OSError) as exc:
        return board_agri.compare(ra, rb, evaluation_error=str(exc))
    return board_agri.compare(ra, rb, test, manifest)


@app.get('/api/scene/{scene}/parcels')
def api_parcels(scene: str):
    try:return S.parcels.load(scene, business_metadata(scene)['shape'])
    except (ValueError, KeyError, OSError) as exc:raise HTTPException(409, str(exc)) from exc


@app.put('/api/scene/{scene}/parcels')
def api_save_parcels(scene: str, cmd: dict):
    try:return S.parcels.save(scene, business_metadata(scene)['shape'], cmd.get('parcels'), cmd.get('revision'))
    except (ValueError, KeyError, OSError) as exc:raise HTTPException(409, str(exc)) from exc


@app.get('/api/run/{rid}/parcels')
def api_run_parcels(rid: int, conf_thr: float = .6):
    try:
        result, _, meta = business_result(rid)
        ledger = S.parcels.load(result.identity['scene'], result.shape)
        return dict(**result.summary(), ledger_revision=ledger['revision'], conf_thr=conf_thr,
                    rows=board_agri.parcel_rows(result, ledger['parcels'], meta['gsd_m'], conf_thr))
    except (ValueError, KeyError, OSError) as exc:raise HTTPException(409, str(exc)) from exc


@app.get('/api/scene/{scene}/annotations')
def api_annotations(scene: str, count: int = 30):
    """Same fixed Train100 selection as finetune_region; no Test leakage/inference."""
    try:
        if scene!='longkou' or type(count) is not int or not 1<=count<=90:raise ValueError('当前只支持LongKou 1～90个训练标注')
        info=E.closed_loop_info(scene)
        if not info:raise ValueError('没有登记的闭环配方')
        hold=info['region']['hold_class'];region=info['region']['region']
        y,x,size=region['row0'],region['col0'],region['size']
        if size!=64:raise ValueError('区域大小不匹配现有微调配方')
        labels,manifest=board_metrics.load_label_set()
        points=np.argwhere(labels['train']==hold)
        if len(points)<count+10:raise ValueError('训练点不足，需另留10个验证点')
        inside=(points[:,0]>=y)&(points[:,0]<y+size)&(points[:,1]>=x)&(points[:,1]<x+size)
        center=np.array([y+size/2,x+size/2])
        order=np.lexsort((np.linalg.norm(points-center,axis=1),~inside))
        selected=points[order][:count]
        return dict(scene=scene,hold_class=hold,count=count,rect=[y,x,size,size],source='OFFICIAL_TRAIN100_NOT_TEST_OR_FIELD_OBSERVATION',
                    points=selected.tolist(),inside_region=int(inside[order][:count].sum()),
                    manifest_sha256=manifest['manifest_sha256'],points_sha256=hashlib.sha256(selected.astype('<u4').tobytes()).hexdigest())
    except (ValueError, KeyError, OSError) as exc:raise HTTPException(409,str(exc)) from exc


@app.post('/api/run/{rid}/report')
def api_agri_report(rid: int, cmd: dict):
    try:
        other = cmd.get('compare')
        if other is not None and (type(other) is not int or other == rid):raise ValueError('请选择不同的真实板任务作对比')
        # Same lock order as compare. Snapshots remain immutable after release.
        with ExitStack() as stack:
            for key in sorted({rid, other} if other is not None else {rid}):
                r = _run(key);stack.enter_context(getattr(r.board_job, 'lock', r.lock))
            result, summary, meta = business_result(rid)
            b = business_result(other)[0] if other is not None else None
        ledger = S.parcels.load(result.identity['scene'], result.shape)
        if type(cmd.get('ledger_revision')) is not int or cmd['ledger_revision'] != ledger['revision']:
            raise ValueError('台账版本已改变或未加载，请重新加载后导出')
        data = board_agri.analyze(result, meta['gsd_m'], cmd.get('conf_thr', .6), cmd.get('min_px', 6))
        try:
            test, manifest = business_labels(result)
            metrics = board_metrics.evaluate(result.pred, result.seen, test, len(result.classes))
            evaluation = dict(available=True, result=metrics, manifest=manifest)
        except (ValueError, KeyError, OSError) as exc:evaluation = dict(available=False, error=str(exc))
        comparison = business_compare(result, b) if b else None
        timing=task_phase_timing(_run(rid).board_job,result.snapshot)
        report, raw = board_agri.report_bundle(result, data, ledger, meta['gsd_m'], meta['palette'], summary, evaluation, comparison,timing)
        job = _run(rid).board_job
        if job.out is None:raise ValueError('任务没有持久证据目录')
        directory = job.out/'reports';directory.mkdir(exist_ok=True)
        report_id = uuid.uuid4().hex
        (directory/(report_id+'.zip')).write_bytes(raw)
        return dict(report=report, download=f'/api/run/{rid}/report/{report_id}.zip')
    except (ValueError, KeyError, OSError) as exc:raise HTTPException(409, str(exc)) from exc


@app.get('/api/run/{rid}/report/{report_id}.zip')
def api_agri_report_zip(rid: int, report_id: str):
    job = _run(rid).board_job
    if not re.fullmatch('[0-9a-f]{32}', report_id) or not job or not job.out:
        raise HTTPException(404, 'No report')
    path = job.out/'reports'/(report_id+'.zip')
    if not path.is_file():raise HTTPException(404, 'No report')
    return FileResponse(path, filename=f'agri_run{rid}_{report_id[:8]}.zip')


@app.get('/api/run/{rid}/metrics')
def api_metrics(rid: int):
    r = _run(rid)
    if r.source == 'board':
        try:
            if r.board_job is None:
                raise ValueError('No board result')
            result = board_metrics.from_snapshot(r.board_job.snapshot())
            result['class_names']=business_metadata(r.scene)['classes']
            if r.board_job.out:
                (r.board_job.out / 'board_metrics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            return result
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
    sc = eng.get_scene(r.scene)
    return analysis.metrics(r.pred, r.done, sc.test_mask, len(sc.classes)) or {}


@app.get('/api/run/{rid}/metrics.csv')
def api_metrics_csv(rid: int):
    report=api_metrics(rid)
    if report.get('source')!='board':raise HTTPException(409,'请选择板卡识别任务')
    return Response('\ufeff'+board_metrics.csv_text(report),media_type='text/csv',
                    headers={'Content-Disposition':f'attachment; filename="metrics_run_{rid}.csv"'})


@app.get('/api/compare')
def api_compare(a: int, b: int):
    try:
        if a == b:raise ValueError('请选择两次不同的板卡任务')
        with ExitStack() as stack:
            for rid in sorted((a, b)):
                r = _run(rid);stack.enter_context(getattr(r.board_job, 'lock', r.lock))
            ra, _, _ = business_result(a);rb, _, _ = business_result(b)
        return business_compare(ra, rb)
    except (ValueError, KeyError, OSError) as exc:raise HTTPException(409, str(exc)) from exc


@app.get('/api/run/{rid}/data')
def api_run_data(rid: int):
    """整次运行的结果（切换历史运行时前端重绘用）：label[H*W] | conf255[H*W]。"""
    r = _run(rid)
    lab = np.where(r.done, r.pred, 0).astype(np.uint8)
    conf = np.where(r.done, np.round(r.conf * 255), 0).astype(np.uint8)
    return Response(lab.tobytes() + conf.tobytes(), media_type='application/octet-stream')


# ---------- 运行控制 ----------

def make_coords(kind, sc, rect):
    if kind == 'scan':
        rr, cc = np.mgrid[0:sc.H, 0:sc.W]
    elif kind == 'region':
        r0, c0, h, w = rect
        rr, cc = np.mgrid[r0:r0 + h, c0:c0 + w]
    elif kind == 'eval':
        return np.argwhere(sc.test_mask > 0)
    else:
        raise ValueError(kind)
    return np.stack([rr.ravel(), cc.ravel()], 1)


def run_callbacks(run):
    rid=run.id
    def on_chunk(c, lab, conf):
        r, cc = c[:, 0], c[:, 1]
        run.pred[r, cc] = lab
        run.conf[r, cc] = conf
        run.done[r, cc] = True
        run.n = int(run.done.sum())
        run.row = int(r[-1])
        n = len(c)
        buf = (CHUNK.pack(1, 0, rid & 0xFFFF, n) + r.astype('<u2').tobytes() + cc.astype('<u2').tobytes()
               + lab.astype(np.uint8).tobytes() + np.round(conf * 255).astype(np.uint8).tobytes())
        if run.source != 'board':
            S.loop.call_soon_threadsafe(S.out.put_nowait, buf)

    def on_done(reason):
        run.status = 'done' if reason == 'done' else ('stopped' if reason == 'stopped' else 'error')
        # Recovery can deliver the terminal status again. Its arrival time is
        # not additional inference time for an already completed task.
        if run.t_end is None:
            run.t_end = time.time()
        emit_json(dict(type='run_end', run=run.summary(), reason=reason))
        log(f'任务 #{rid} {run.kind} 结束：{reason}，{run.n}/{run.total} 像素，用时 {run.t_end - run.t0:.1f} s',
            'error' if reason.startswith('error') else 'info')

    def on_board_update(b):
        if b['status'] in ('running','paused'):
            run.status=b['status']
        emit_json(dict(type='board_update', id=rid, board=b))

    return on_chunk,on_done,on_board_update


def start_run(cmd):
    speed_guard()
    if getattr(S.board_source,'key_executing',False) and getattr(S,'key_thread',None)!=threading.get_ident():
        raise ValueError('板载按键操作尚未确认，请稍候再开始新任务')
    if S.source.name == 'board':
        receipt={} if getattr(S.source,'network_startup',None) else UART.snapshot()
        if receipt.get('error') and receipt.get('boot_id')==S.board_source.describe()['boot_id']:
            raise ValueError('UART reported a failure for this boot; preserve evidence, no START')
        S.source.validate(cmd)  # reject before clamping ROI or changing any run
    if S.run is not None and S.run.status in ('running', 'paused'):
        raise ValueError('请先停止或等待当前任务完成')
    sc = eng.get_scene(cmd['scene'])
    rect = cmd.get('rect')
    if S.source.name=='board' and cmd['kind']=='scan':rect=None
    if rect:
        r0, c0, h, w = [int(x) for x in rect]
        r0, c0 = max(0, min(r0, sc.H - 1)), max(0, min(c0, sc.W - 1))
        rect = [r0, c0, max(1, min(h, sc.H - r0)), max(1, min(w, sc.W - c0))]
    coords = make_coords(cmd['kind'], sc, rect)
    rid = S.next_id
    S.next_id += 1
    run = Run(rid, cmd['kind'], cmd['scene'], cmd['version'], rect, coords, sc.H, sc.W, S.source.name)
    run.origin=cmd.get('origin')
    run.uart_evidence=None if getattr(S.source,'network_startup',None) else UART.snapshot().get('evidence')
    S.run = run
    S.runs[rid] = run

    on_chunk,on_done,on_board_update=run_callbacks(run)

    emit_json(dict(type='run_start', run=run.summary(), alive=list(S.runs)))
    log(f'任务 #{rid} 开始：{cmd["kind"]} · {cmd["scene"]} · 权重 {cmd["version"]} · {len(coords)} 像素 · 源 {S.source.name}')
    try:
        if run.source == 'board':
            S.source.start(run, on_chunk, on_done,
                           on_update=on_board_update)
        else:
            S.source.start(run, on_chunk, on_done, float(cmd.get('pace_rows') or 0))
    except Exception as exc:
        on_done(f'error:{exc}')
        raise
    return run


def set_source(cmd):
    speed_guard()
    if cmd.get('source') != 'board':
        raise ValueError('仅支持板卡任务')
    if (cmd.get('source')=='board' and S.source is S.board_source
        and cmd.get('board_ip','192.168.1.10')=='192.168.1.10'):
        # Reapplying the exact same endpoint is a no-op, not a takeover.
        return
    if UART.snapshot()['active']:
        raise ValueError('End UART capture before changing source; no silent serial takeover')
    if cmd['source'] == 'board' and cmd.get('board_ip', '192.168.1.10') != '192.168.1.10':
        raise ValueError('本轮唯一板端目标192.168.1.10:5010')
    if S.source.name == 'board':
        S.source.close()
    if S.run is not None and S.run.status == 'running':
        S.source.stop()
    S.source = S.board_source
    S.run = None  # do not present old PC/board run as the newly selected source
    emit_json(dict(type='source', source=S.source.describe()))


def upload(cmd):
    speed_guard()
    if S.source is not S.board_source:raise ValueError('仅支持真实板卡模型传输')
    if not isinstance(S.board_source,board_link.BoardSource):raise ValueError('旧App连接不支持新版模型事务')
    receipt={} if S.board_source.network_startup else UART.snapshot()
    if receipt.get('error') and receipt.get('boot_id')==S.board_source.describe()['boot_id']:
        raise ValueError('本启动UART已报告错误，禁止传输掩盖故障')
    return S.board_source.request_models('upload',cmd['scene'],cmd['version'],activate=cmd.get('activate') is True,on_update=model_event)


def model_event(result):
    event=dict(result)
    event['type']='upload_end' if result['state'] in ('done','error') else 'upload'
    event['bytes']=result['total'];event['note']=result['error'] or ('等待当前任务结束后持久化/激活' if result['state']=='waiting_task_end' else result['phase'])
    emit_json(event);emit_json(dict(type='board_gate',source=S.board_source.describe()))


@app.get('/api/board/models')
def api_models():
    # Local catalog + last actual receipt only. HTTP GET never opens UDP/UART.
    entries=S.board_source.describe().get('registry',[])
    candidates=board_models.registry_summary(E.DATA,E.VERSIONS)
    for c in candidates:
        if c.get('available'):c['board_registered']=board_models.registered(c,entries)
    return dict(candidates=candidates,entries=entries,operation=S.board_source.describe().get('model_operation'),
                channels=S.board_source.model_channels(),errors=S.model_catalog_errors)


@app.post('/api/board/models/query')
def api_models_query(cmd:dict):
    try:
        speed_guard()
        if cmd.get('confirmed') is not True:raise ValueError('请明确确认查询已连接板卡的模型目录')
        return S.board_source.request_models('query',on_update=model_event)
    except (ValueError,OSError,KeyError) as exc:raise HTTPException(409,str(exc)) from exc


@app.post('/api/board/models/activate')
def api_models_activate(cmd:dict):
    try:
        speed_guard()
        if cmd.get('confirmed') is not True:raise ValueError('请明确确认安全边界切换模型')
        return S.board_source.request_models('activate',cmd['scene'],cmd['version'],on_update=model_event)
    except (ValueError,OSError,KeyError) as exc:raise HTTPException(409,str(exc)) from exc


@app.post('/api/board/models/recover')
def api_models_recover(cmd:dict):
    try:
        with S.control_lock:
            if cmd.get('confirmed') is not True:raise ValueError('请明确确认恢复此模型连接')
            if S.board_source.describe()['active']:raise ValueError('已有活动连接，不能恢复接管')
            reviewed=board_release.expected_build(gcs_release.audited_elf(loaded_assets=LOADED_RELEASE_ASSETS))
            S.board_source.release_id=reviewed['release_id']
            return S.board_source.recover_models(cmd.get('channel'),cmd.get('confirmed'),model_event)
    except (ValueError,OSError,KeyError,TypeError) as exc:raise HTTPException(409,str(exc)) from exc


def finetune(cmd):
    if cmd.get('scene') != 'longkou':raise ValueError('当前微调配方只登记LongKou，不跨景代跑')
    if S.finetune is not None:
        return log('已有微调在跑', 'warn')
    info = E.closed_loop_info('longkou')
    if not info:
        return log('没有闭环区域数据（先跑 finetune_region.py make-old）', 'error')
    n = cmd.get('annotate', 30)
    if type(n) is not int or not 1 <= n <= 90:raise ValueError('标注数需为1～90整数，保留独立验证样本')
    region=info['region']['region']
    expected=[region['row0'],region['col0'],region['size'],region['size']]
    if cmd.get('base_version')!=f"hold{info['region']['hold_class']}" or cmd.get('rect')!=expected:
        raise ValueError('微调基线/区域与登记配方不一致；不悄悄用另一权重或区域训练')
    tag = time.strftime('live%m%d_%H%M%S')
    args = [sys.executable, '-u', str(ROOT / 'model' / 'finetune_region.py'), 'finetune', '--scene', 'longkou',
            '--hold-class', str(info['region']['hold_class']), '--annotate', str(n),
            '--weights-version', tag, '--run-tag', tag]
    if (E.DATA/'longkou/weights'/tag).exists():raise ValueError('该训练导出标识已存在；不覆盖旧模型')
    # Claim synchronously before the worker starts; rapid UI clicks must not
    # launch two trainers while S.finetune is still None.
    owner=S;owner.finetune=dict(state='queued',tag=tag)

    def work():
        t0=time.time();p=None;created=False
        evidence=ROOT/'build/host/gcs_training'/tag
        try:
            evidence.mkdir(parents=True,exist_ok=False)
            created=True
            board_task.save_json(evidence/'command.json',dict(argv=args,cwd=str(ROOT),scene='longkou',base_version=cmd['base_version'],annotate=n,rect=expected))
            log(f'现场微调开始：{n} 个标注点，标签 {tag}')
            emit_json(dict(type='finetune',state='start',tag=tag,scene='longkou'))
            p=subprocess.Popen(args,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
                               encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            owner.finetune=p;tail=[]
            with (evidence/'training.log').open('w',encoding='utf-8') as raw:
                for line in p.stdout:
                    raw.write(line);raw.flush();tail.append(line.rstrip())
                    if len(tail)>2000:tail.pop(0)
                    if re.match(r'ep\s+\d+',line):emit_json(dict(type='finetune',state='epoch',line=line.rstrip(),t=time.time()-t0,scene='longkou'))
            p.wait()
            if p.returncode:raise RuntimeError('训练/配套导出失败：'+' | '.join(tail[-5:]))
            text='\n'.join(tail);res=json.loads(text[text.index('{'):])
            candidate=board_models.load_candidate(E.DATA,'longkou',tag)
            if candidate['provenance']['checkpoint_sha256']!=res['new_ckpt_sha256']:raise ValueError('训练checkpoint与导出来源不符')
            board_task.save_json(evidence/'candidate.json',candidate)
            E.VERSIONS['longkou'].append(dict(id=tag,label=f'现场微调 {tag[4:]}（{n} 点）',ckpt=Path(res['new_ckpt']),pkg=tag))
            emit_json(dict(type='finetune',state='done',tag=tag,scene='longkou',seconds=time.time()-t0,
                           candidate=dict(version=tag,wcrc=candidate['wcrc'],source='TRAINING_ARTIFACT_NOT_BOARD_RESULT')))
            log(f'现场微调完成：{time.time()-t0:.0f} s，新版本 {tag}；等待上传、切换和真实板任务复测')
        except Exception as exc:
            log('现场微调未完成：'+str(exc),'error');emit_json(dict(type='finetune',state='error',scene='longkou',error=str(exc)))
        finally:
            if p and p.poll() is None:p.communicate() # drain pipe too; no orphan/deadlock on host I/O error
            if created:board_task.save_json(evidence/'exit.json',dict(exit=p.returncode if p else None,seconds=time.time()-t0))
            owner.finetune=None

    try:threading.Thread(target=work,name='gcs-explicit-finetune',daemon=False).start()
    except Exception:owner.finetune=None;raise


@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    S.clients.add(ws)
    await ws.send_text(json.dumps(dict(type='hello', source=S.source.describe(), device=eng.device_name,
                                       run=S.run.summary() if S.run else None), ensure_ascii=False))
    try:
        while True:
            cmd = json.loads(await ws.receive_text())
            c = cmd.get('cmd')
            try:
                if c == 'start':
                    await asyncio.to_thread(controlled, start_run, cmd)
                elif c == 'pause' and S.run:
                    speed_guard()
                    S.source.pause()  # actual board ACK/STATUS, not optimistic UI state
                elif c == 'resume' and S.run:
                    speed_guard()
                    S.source.resume()
                elif c == 'stop' and S.run:
                    if S.speed.busy:S.speed.stop()
                    S.source.stop()
                elif c == 'source':
                    await asyncio.to_thread(controlled, set_source, cmd)
                elif c == 'upload':
                    await asyncio.to_thread(controlled,upload,cmd)
                elif c == 'finetune':
                    await asyncio.to_thread(controlled,finetune,cmd)
            except Exception as e:      # noqa: BLE001
                emit_json(dict(type='command_error',command=c,error=str(e)))
                log(f'命令 {c} 失败：{e}', 'error')
    except WebSocketDisconnect:
        S.clients.discard(ws)


@app.exception_handler(KeyError)
async def key_error(_, exc):
    return JSONResponse(dict(error=str(exc)), status_code=404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    if not a.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{a.port}')).start()
    uvicorn.run(app, host=a.host, port=a.port, log_level='warning')


if __name__ == '__main__':
    main()
