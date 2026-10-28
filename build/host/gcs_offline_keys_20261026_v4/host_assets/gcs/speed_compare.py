"""Two sequential real board runs over the same ROI, with recorded progress."""
import copy
import json
from pathlib import Path
import re
import threading
import time
import uuid


class Comparison:
    def __init__(self, root):
        self.root=Path(root)
        self.lock=threading.RLock()
        self.cancel=threading.Event()
        self.current=None
        self.thread=None
        self.thread_id=None

    @property
    def busy(self):
        with self.lock:return bool(self.current and self.current['state'] in ('queued','running'))

    def snapshot(self):
        with self.lock:return copy.deepcopy(self.current)

    def history(self):
        if not self.root.exists():return []
        result=[]
        for p in sorted(self.root.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:30]:
            try:
                data=json.loads(p.read_text(encoding='utf-8'))
                result.append({k:data[k] for k in ('id','scene','versions','state','created')})
            except (OSError,ValueError,KeyError):continue
        return result

    def load(self, name):
        if not isinstance(name,str) or not re.fullmatch('[0-9a-f]{32}',name):raise ValueError('无效对比编号')
        return json.loads((self.root/(name+'.json')).read_text(encoding='utf-8'))

    def start(self, scene, versions, rect, start_run, stop_run, check):
        if not isinstance(versions,list) or len(versions)!=2 or any(not isinstance(v,str) for v in versions) or len(set(versions))!=2:
            raise ValueError('请选择两个不同权重')
        if not isinstance(rect,list) or len(rect)!=4 or any(type(x)is not int for x in rect) or min(rect)<0 or min(rect[2:])<1 or rect[2]*rect[3]>16384:
            raise ValueError('请框选 1～16,384 像素的相同对比区域')
        with self.lock:
            if self.busy:raise ValueError('已有速度对比正在运行')
            check()
            self.cancel.clear()
            self.current=dict(id=uuid.uuid4().hex,created=time.strftime('%Y-%m-%d %H:%M:%S'),scene=scene,
                              versions=list(versions),rect=list(rect),state='queued',phase=0,error=None,items=[],
                              scope='Same board and ROI; sequential real runs; compute time excludes preparation; traces preserve wall time')
            self.thread=threading.Thread(target=self._work,args=(start_run,stop_run,check),daemon=True,name='board-speed-compare')
            self.thread.start()
            return self.snapshot()

    def stop(self):
        self.cancel.set()

    def _save(self):
        self.root.mkdir(parents=True,exist_ok=True)
        data=self.snapshot();path=self.root/(data['id']+'.json')
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)

    def _work(self, start_run, stop_run, check):
        self.thread_id=threading.get_ident()
        run=None
        try:
            with self.lock:self.current['state']='running'
            for phase,version in enumerate(self.current['versions']):
                check()
                if self.cancel.is_set():break
                with self.lock:self.current['phase']=phase
                run=start_run(version,self.current['id'])
                started=time.monotonic()
                item=dict(version=version,run_id=run.id,status='running',done=0,total=run.total,elapsed_s=0,
                          ms_per_pixel=None,compute_ms=None,rate=None,trace=[dict(t_ms=0,done=0,compute_ms=0)])
                with self.lock:self.current['items'].append(item)
                last=-1;deadline=started+1800;stop_sent=False
                while True:
                    check()
                    if self.cancel.is_set() and run.status in ('running','paused') and not stop_sent:
                        stop_run(run);stop_sent=True
                    summary=run.summary();done=summary['done'];ms=summary.get('board_ms_per_px')
                    perf=(summary.get('board') or {}).get('performance') or {}
                    seconds=perf.get('cumulative_seconds_from_wire')
                    compute_ms=seconds*1000 if seconds is not None else done*ms if ms else None
                    elapsed=time.monotonic()-started
                    with self.lock:
                        item.update(status=summary['status'],done=done,elapsed_s=elapsed,
                                    ms_per_pixel=ms,rate=1000/ms if ms and ms>0 else None,compute_ms=compute_ms)
                        if done!=last or summary['status'] not in ('running','paused'):
                            item['trace'].append(dict(t_ms=round(elapsed*1000,3),done=done,compute_ms=compute_ms));last=done
                    if summary['status'] not in ('running','paused'):break
                    if time.monotonic()>deadline:raise ValueError('对比任务超过 30 分钟，请检查板卡状态')
                    time.sleep(.08)
                with self.lock:
                    board=summary.get('board') or {}
                    item['identity']={k:board.get(k) for k in ('boot_id','session','task','scene','model','wcrc')}
                self._save()
                if self.cancel.is_set():break
                if summary['status']!='done' or done!=run.total:raise ValueError('对比任务未完整完成：'+str(board.get('error') or summary['status']))
            with self.lock:self.current['state']='cancelled' if self.cancel.is_set() else 'done'
        except Exception as exc:
            # Do not silently abandon a task owned by this comparison.
            if run is not None and run.status in ('running','paused'):
                try:stop_run(run)
                except Exception:pass
            with self.lock:self.current.update(state='error',error=str(exc))
        finally:
            self.thread_id=None
            self._save()
