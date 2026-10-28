# -*- coding: utf-8 -*-
"""浏览器版小地面站：打开 http://127.0.0.1:8770 就能下发任务、看分类图与统计。

为什么有这个：原版地面站（`gcs_roi.py serve`，127.0.0.1:8765）在本树起不来——
`/api/board/connect` 要求发布包里带 `approved_elf.json` + `sync.json`，这棵树没有（见手册 7.2）。
本工具只用标准库，直接讲 UDP 协议（docs/protocol.md），不经过地面站的发布审查。

    D:\\Anaconda\\python.exe tools\\gcs_web.py
    D:\\Anaconda\\python.exe tools\\gcs_web.py --port 8770 --no-browser

页面里：三张卡片（龙口 / 洪湖 / 汉川），每张可以单独「开始 / 停止 / 保存」，
也可以「依次跑三景」；左边分类图随板卡逐行刷新，右边是进度与类别统计。
板卡一次只跑一个任务，所以多个请求会排队依次下发。

    D:\\Anaconda\\python.exe tools\\gcs_web.py --no-board     # 只看页面，不碰板卡

速度：实测 4.42 ms/像素（int16 引擎）。整幅龙口 400×550 约 16 分钟，64×64 约 18 秒。
"""

import argparse
import csv
import json
import math
import queue
import struct
import sys
import threading
import time
import webbrowser
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gcs_mini import Link, build_scenes, decode_info  # noqa: E402  复用已上板验证过的协议实现

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WCRC = 0x27231983
STATE_ZH = {0: "空闲", 1: "运行中", 2: "暂停", 3: "已完成"}
SCENE_ORDER = ["longkou", "honghu", "hanchuan"]


def png_bytes(width, height, rgb):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    stride = width * 3
    raw = b"".join(b"\x00" + bytes(rgb[y * stride:(y + 1) * stride]) for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


class Backend:
    def __init__(self, args):
        self.args = args
        self.scenes = build_scenes()
        self.lock = threading.Lock()
        self.q = queue.Queue()
        self.log = []
        self.boot = 0
        self.session = int(args.session, 16)
        self.wcrc = 0
        self.models = []
        self.link = None if args.no_board else Link(args.board, args.port, self.session, self.q)
        self.pending = []
        self.busy = None            # 正在跑的场景 key
        self.last_status = None
        self.probe = None            # 最近一次单点探查结果
        self.result = {}            # key -> dict(grid, counts, done, total, task, region, ms, rev, state)
        for key in SCENE_ORDER:
            self.result[key] = dict(state="idle", done=0, total=0, task=0, region="",
                                    grid=None, counts=None, rev=0, ms=None)
        self.used_tasks = set()
        if self.link:
            self.link.start()
        threading.Thread(target=self._loop, daemon=True).start()

    # ---------- 内部
    def note(self, text):
        self.log.append("%s %s" % (time.strftime("%H:%M:%S"), text))
        del self.log[:-200]

    def _loop(self):
        while True:
            self._pump()
            time.sleep(0.03)

    def _pump(self):
        while True:
            try:
                ev = self.q.get_nowait()
            except queue.Empty:
                break
            kind = ev["kind"]
            if kind == "info":
                with self.lock:
                    self.boot = ev["boot"]
                    if ev["session"]:
                        self.session = ev["session"]
                    self.models = [m for m in ev["models"] if m["kind"] == 1]
                self.note("INFO：boot=%08x，SD 上登记 %d 个权重包" % (ev["boot"], ev["n"]))
            elif kind == "status":
                self._on_status(ev)
            elif kind == "row":
                key = self.busy
                if key:
                    self._paint(key, ev)
            elif kind == "ack":
                names = {0x01: "START", 0x02: "STOP", 0x13: "WACT", 0x05: "PING", 0x09: "PROBE"}
                self.note("ACK %s code=%d value=%s"
                          % (names.get(ev["typ"], hex(ev["typ"])), ev["code"], ev["value"]))
                if ev["typ"] == 0x01 and ev["code"] != 0:
                    with self.lock:
                        if self.busy:
                            self.result[self.busy]["state"] = "failed"
                            self.busy = None
                    self.note("板卡拒绝任务：5=没有该权重 8=参数越界 9=任务号重复/板卡在忙")
                    self._advance()
            elif kind == "logits":
                sc = self.scenes[SCENE_ORDER[ev["scene"]]] if ev["scene"] < len(SCENE_ORDER) else None
                word = ev["word"]
                self.probe = dict(state="done", row=ev["row"], col=ev["col"], scene=ev["scene"],
                                  key=sc["key"] if sc else None, wcrc="%08x" % ev["wcrc"],
                                  cls=word & 0xFF, conf=(word >> 16) / 65536.0,
                                  word="%08X" % word,
                                  logits=[dict(cls=i, q16=v) for i, v in enumerate(ev["logits"])],
                                  at=time.time())
                self.note("单点探查 (%d,%d) → 类别 %d，置信度 %.3f"
                          % (ev["row"], ev["col"], word & 0xFF, (word >> 16) / 65536.0))
            elif kind == "probe_failed":
                with self.lock:
                    if self.probe and self.probe.get("state") == "pending":
                        self.probe.update(state="error", error=ev["text"])
                self.note("探查失败：%s" % ev["text"])
            elif kind == "log":
                self.note(ev["text"])
            elif kind == "error":
                self.note("协议异常：%s" % ev["text"])
            elif kind == "started":
                self.note("已下发 task=%d" % ev["task"])

    def _on_status(self, ev):
        finished = None
        with self.lock:
            self.boot = ev["boot"]
            self.wcrc = ev["wcrc"]
            if ev["session"]:
                self.session = ev["session"]
            self.last_status = ev
            key = self.busy
            if not key:
                return
            res = self.result[key]
            if ev["total"]:
                res["total"] = ev["total"]
            res["done"] = ev["done"]
            if math.isfinite(ev["ms"]):
                res["ms"] = ev["ms"]
            if ev["state"] == 3 and res["state"] == "running":
                res["state"] = "done"
                res["rev"] += 1              # 让页面把最后几行也刷出来
                self.busy = None
                finished = (key, ev["done"], ev["total"])
        if finished:
            self.note("%s 完成 done=%d/%d" % (self.scenes[finished[0]]["label"], finished[1], finished[2]))
            self._advance()

    def _paint(self, key, ev):
        sc = self.scenes[key]
        res = self.result[key]
        grid = res["grid"]
        if grid is None:
            return
        w = sc["w"] if res["region"] == "full" else res["w"]
        counts = res["counts"]
        for i, word in enumerate(ev["words"]):
            cls = word & 0xFF
            if cls >= sc["classes"]:
                cls = 0
            x = ev["col"] + i
            idx = ev["row"] * w + x
            if x >= w or idx >= len(grid):
                break
            if grid[idx] == 0xFF:
                counts[cls] += 1
            grid[idx] = cls
            r, g, b = sc["rgb"][cls]
            res["rgb"][idx * 3:idx * 3 + 3] = bytes((r, g, b))
        res["rows"] = max(res.get("rows", 0), ev["row"] + 1)
        if ev["row"] % 16 == 0:
            res["rev"] += 1

    # ---------- 外部调用
    def start(self, key, region):
        if self.link is None:
            return False, "服务以 --no-board 启动，不连板卡"
        sc = self.scenes[key]
        if region == "full":
            w, h, mode = sc["w"], sc["h"], 0
        else:
            head, _, tail = region.partition("x")
            w, h, mode = min(int(head), sc["w"]), min(int(tail or head), sc["h"]), 1
        task = int(time.time() * 1000) % 32767 + 1
        while task in self.used_tasks:
            task = task % 32767 + 1
        self.used_tasks.add(task)
        spec = dict(scene_idx=sc["idx"], label=sc["label"], mode=mode, x=0, y=0, w=w, h=h,
                    wcrc=None, task=task)
        with self.lock:
            res = self.result[key]
            res.update(state="queued", task=task, region=region, w=w, h=h, rows=0, rev=0,
                       done=0, total=w * h, ms=None,
                       grid=bytearray(b"\xff") * (w * h),
                       rgb=bytearray(w * h * 3), counts=[0] * sc["classes"])
        self.pending.append((key, spec))
        self.note("排队：%s %s（task=%d）" % (sc["label"], "整幅" if region == "full" else region, task))
        self._advance()
        return True, ""

    def _advance(self):
        with self.lock:
            if self.busy or not self.pending or self.link is None:
                return
            key, spec = self.pending.pop(0)
            self.busy = key
            self.result[key]["state"] = "running"
        self.link.start_task(spec)

    def probe_at(self, key, row, col):
        """单点探查：板卡在当前这次计算结束后插算一个像素，回 LOGITS（类别 + 各类 Q.16 logits）。"""
        if self.link is None:
            return False, "服务以 --no-board 启动，不连板卡"
        sc = self.scenes[key]
        if not (0 <= row < sc["h"] and 0 <= col < sc["w"]):
            return False, "坐标越界：%s 是 %d×%d" % (sc["label"], sc["w"], sc["h"])
        with self.lock:
            task = (self.last_status or {}).get("task", 0)
        if not task:
            return False, "板卡上还没有任务：先在任意卡片点一次「开始」"
        with self.lock:
            self.probe = dict(state="pending", row=row, col=col, scene=sc["idx"], key=key,
                              at=time.time())
        self.link.probe(row, col, sc["idx"], task=task)
        return True, ""

    def stop(self):
        if self.link is None:
            return
        with self.lock:
            task = self.result[self.busy]["task"] if self.busy else (self.last_status or {}).get("task", 0)
            state = (self.last_status or {}).get("state", 0)
        if not task or state not in (1, 2):
            self.note("板卡当前没有在跑的任务，无需停止")
            return
        # 直接按「板卡上正在跑的那个任务号」发 STOP：本页面没在收的任务也能停
        self.link.send(0x02, b"", task=task)
        self.link.mode = "idle"
        self.note("已请求停止 task=%d（当前行算完生效）" % task)

    def state_json(self):
        with self.lock:
            scenes = []
            for key in SCENE_ORDER:
                sc = self.scenes[key]
                res = self.result[key]
                counts = res["counts"] or [0] * sc["classes"]
                scenes.append(dict(
                    key=key, label=sc["label"], w=sc["w"], h=sc["h"], classes=sc["classes"],
                    map_w=(sc["w"] if res["region"] in ("", "full") else res.get("w", sc["w"])),
                    map_h=(sc["h"] if res["region"] in ("", "full") else res.get("h", sc["h"])),
                    state=res["state"], done=res["done"], total=res["total"], rows=res.get("rows", 0),
                    task=res["task"], region=res["region"], ms=res["ms"], rev=res["rev"],
                    has_map=res["grid"] is not None,
                    names=[dict(id=i, zh=sc["zh"][i], en=sc["en"][i], color="#%02x%02x%02x" % sc["rgb"][i],
                                pixels=counts[i]) for i in range(sc["classes"])]))
            return dict(connected=self.link is not None, boot="%08x" % self.boot,
                        session="%08x" % self.session, wcrc="%08x" % self.wcrc,
                        models=[m["tag"] for m in self.models], busy=self.busy,
                        board_task=(self.last_status or {}).get("task", 0),
                        board_state=(self.last_status or {}).get("state", 0),
                        queued=[k for k, _ in self.pending], probe=self.probe,
                        region_hint=dict(w=self.scenes["longkou"]["w"], h=self.scenes["longkou"]["h"]),
                        log=self.log[-12:], scenes=scenes)

    def map_png(self, key):
        with self.lock:
            res = self.result[key]
            sc = self.scenes[key]
            if res["grid"] is None:
                return None
            w = sc["w"] if res["region"] == "full" else res["w"]
            h = sc["h"] if res["region"] == "full" else res["h"]
            rgb = res["rgb"]
        return png_bytes(w, h, rgb)

    def save(self, key):
        with self.lock:
            res = self.result[key]
            if res["grid"] is None:
                return None
            sc = self.scenes[key]
            w = sc["w"] if res["region"] == "full" else res["w"]
            h = sc["h"] if res["region"] == "full" else res["h"]
            rgb, counts = res["rgb"], list(res["counts"])
            meta = dict(scene=key, label=sc["label"], region=res["region"], w=w, h=h,
                        task=res["task"], wcrc="%08x" % (self.wcrc or DEFAULT_WCRC), boot="%08x" % self.boot,
                        session="%08x" % self.session, done=res["done"], total=res["total"],
                        ms_per_px=res["ms"])
        d = ROOT / "build/host" / time.strftime("gcs_web_%Y%m%d_%H%M%S")
        d.mkdir(parents=True, exist_ok=True)
        (d / ("class_map_%s.png" % key)).write_bytes(png_bytes(w, h, rgb))
        total = sum(counts) or 1
        with (d / ("class_stats_%s.csv" % key)).open("w", newline="", encoding="utf-8-sig") as fh:
            wr = csv.writer(fh)
            wr.writerow(["class_id", "name_zh", "name_en", "pixels", "ratio"])
            for i, n in enumerate(counts):
                if n:
                    wr.writerow([i, sc["zh"][i], sc["en"][i], n, "%.6f" % (n / total)])
        meta["classes"] = [dict(id=i, name_zh=sc["zh"][i], name_en=sc["en"][i], pixels=counts[i])
                           for i in range(sc["classes"])]
        meta["note"] = "模型预测类别，非地面真值；温度/功率未测"
        (d / ("summary_%s.json" % key)).write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                                                   encoding="utf-8")
        self.note("已保存 %s" % d)
        return str(d)


PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>农情分析 · 板卡小地面站</title>
<style>
body{margin:0;font:14px/1.5 "Microsoft YaHei",system-ui,sans-serif;background:#0d1117;color:#c9d1d9}
header{display:flex;gap:14px;align-items:center;padding:10px 16px;background:#161b22;border-bottom:1px solid #30363d;flex-wrap:wrap}
h1{font-size:16px;margin:0 12px 0 0;font-weight:600;color:#58a6ff}
.pill{padding:2px 8px;border-radius:10px;background:#21262d;border:1px solid #30363d;font-size:12px}
.ok{color:#3fb950}.bad{color:#f85149}
main{display:flex;gap:10px;padding:10px;align-items:flex-start;flex-wrap:wrap}
.card{flex:1 1 320px;min-width:300px;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px}
.card h2{font-size:14px;margin:0 0 6px;color:#e6edf3;font-weight:600}
.mapbox{background:#0b0f14;border:1px solid #21262d;border-radius:6px;display:flex;justify-content:center;align-items:center;min-height:260px;max-height:420px;overflow:hidden}
.mapbox img{max-width:100%;max-height:420px;image-rendering:pixelated}
.empty{color:#8b949e;font-size:12px;text-align:center;padding:0 14px;line-height:1.7}
.probe{margin-top:6px;font-size:12px;color:#8b949e;background:#0b0f14;border:1px solid #21262d;
       border-radius:6px;padding:6px 8px;min-height:34px;line-height:1.6}
.probe b{color:#e6edf3}
.probe .lg{display:flex;gap:5px;flex-wrap:wrap;margin-top:4px}
.probe .lg span{background:#161b22;border:1px solid #21262d;border-radius:4px;padding:1px 5px}
.bar{height:8px;background:#21262d;border-radius:4px;overflow:hidden;margin:8px 0 4px}
.bar>div{height:100%;width:0;background:#2ea043;transition:width .3s}
.row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:13px}
button:hover{background:#30363d}button:disabled{opacity:.45;cursor:not-allowed}
select{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:4px}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}
th,td{padding:2px 4px;border-bottom:1px solid #21262d;text-align:left}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
#log{margin:0 10px 16px;background:#0b0f14;border:1px solid #21262d;border-radius:6px;padding:8px;
     font:12px/1.45 Consolas,monospace;color:#8b949e;white-space:pre-wrap;max-height:150px;overflow:auto}
small{color:#8b949e}
</style></head><body>
<header>
  <h1>农情分析 · 板卡小地面站</h1>
  <span class="pill" id="conn">连接中…</span>
  <span class="pill" id="ident">—</span>
  <span class="pill">区域
    <select id="region">
      <option value="full">整幅</option><option value="256x256">256×256</option>
      <option value="128x128">128×128</option><option value="64x64" selected>64×64</option>
      <option value="5x3">5×3（验收用）</option>
    </select>
  </span>
  <button id="all">依次跑三景</button>
  <button id="stop">停止</button>
  <span class="pill"><small id="hint"></small></span>
</header>
<main id="cards"></main>
<div id="log"></div>
<script>
const ORDER=[["longkou","LongKou 龙口"],["honghu","HongHu 洪湖"],["hanchuan","HanChuan 汉川"]];
let S=null, revs={}, SZ={};
function el(t,c,x){const e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=x;return e;}
function buildCards(){
  const host=document.getElementById('cards');
  for(const [k,label] of ORDER){
    const c=el('div','card');c.id='card-'+k;
    c.innerHTML=`<h2>${label} <small id="sz-${k}"></small></h2>
      <div class="mapbox"><img id="img-${k}" alt="还没有结果"><span id="empty-${k}" class="empty">先在上面选「区域」，再点下面的「开始」<br>（整幅 LongKou 约 16 分钟，先用 64×64 试一下）</span></div>
      <div class="bar"><div id="bar-${k}"></div></div>
      <div class="row" style="justify-content:space-between">
        <small id="prog-${k}">等待任务</small>
        <span>
          <button data-start="${k}">开始</button>
          <button data-save="${k}">保存</button>
        </span>
      </div>
      <div class="probe" id="probe-${k}"><small>点地图上的任意一点即可单点探查（要先跑过任务）</small></div>
      <table><thead><tr><th>类别</th><th style="text-align:right">像素</th><th style="text-align:right">占比</th></tr></thead>
      <tbody id="stats-${k}"></tbody></table>`;
    host.appendChild(c);
  }
  host.addEventListener('click',async e=>{
    const b=e.target.closest('button');if(!b)return;
    const region=document.getElementById('region').value;
    if(b.dataset.start){const r=await fetch(`/api/start?s=${b.dataset.start}&region=${region}`,{method:'POST'});
      const j=await r.json(); if(!j.ok) alert('没有开始：'+(j.error||'未知原因'));}
    if(b.dataset.save){const r=await fetch(`/api/save?s=${b.dataset.save}`,{method:'POST'});
      const j=await r.json(); alert(j.ok?('已保存到：'+j.dir):('保存失败：'+(j.error||'')));}
  });
  document.getElementById('all').onclick=async()=>{
    const region=document.getElementById('region').value;
    for(const [k] of ORDER){await fetch(`/api/start?s=${k}&region=${region}`,{method:'POST'});}
  };
  document.getElementById('stop').onclick=()=>fetch('/api/stop',{method:'POST'});
  host.querySelectorAll('img').forEach(img=>{
    img.style.cursor='crosshair';
    img.addEventListener('click',async e=>{
      const k=img.id.replace('img-','');
      const sz=SZ[k];
      if(!sz||!sz.w){alert('还没有图可点：先跑一个任务');return;}
      const r=img.getBoundingClientRect();
      const col=Math.floor((e.clientX-r.left)/r.width*sz.w);
      const row=Math.floor((e.clientY-r.top)/r.height*sz.h);
      const resp=await fetch(`/api/probe?s=${k}&row=${row}&col=${col}`,{method:'POST'});
      const j=await resp.json();
      if(!j.ok)alert('单点探查失败：'+(j.error||'未知原因'));
    });
  });
}
async function tick(){
  let S2=null;
  try{
    const r=await fetch('/api/state',{cache:'no-store'});
    S2=await r.json();S=S2;
  }catch(e){
    const conn=document.getElementById('conn');
    conn.textContent='服务未连（会自动重试）';conn.className='pill bad';
    document.getElementById('hint').textContent='一直这样的话：看 logs\\gcs_web.err，或重新运行 START_DEMO.bat';
  }
  if(!S2){setTimeout(tick,900);return;}
  const conn=document.getElementById('conn');
  conn.textContent=S.connected?('已连接会话 '+S.session):'服务在，但板卡没回包';
  conn.className='pill '+(S.connected?'ok':'bad');
  document.getElementById('ident').textContent='boot '+S.boot+' · 模型 '+S.wcrc+(S.models.length?(' · '+S.models.slice(0,2).join(' ')):'');
  document.getElementById('hint').textContent=S.busy?('正在跑 '+S.busy)
      :(S.queued.length?('排队 '+S.queued.join(','))
      :((S.board_state===1||S.board_state===2)?('板卡在跑 task '+S.board_task+'（本页面没在收）'):'空闲'));
  for(const sc of S.scenes){
    const k=sc.key;
    SZ[k]={w:sc.map_w||sc.w,h:sc.map_h||sc.h};
    document.getElementById('sz-'+k).textContent=`${sc.w}×${sc.h} · ${sc.classes} 类`;
    const img=document.getElementById('img-'+k), empty=document.getElementById('empty-'+k);
    if(sc.has_map){
      if(revs[k]!==sc.rev){img.src=`/api/map?s=${k}&v=${sc.rev}`;revs[k]=sc.rev;}
      img.style.display='block';empty.style.display='none';
    }else{img.style.display='none';empty.style.display='block';}
    const pct=sc.total?Math.min(100,100*sc.done/sc.total):0;
    document.getElementById('bar-'+k).style.width=pct+'%';
    const st={idle:'等待任务',queued:'排队中',running:'运行中',done:'已完成',failed:'板卡拒绝'}[sc.state]||sc.state;
    const eta=(sc.ms&&sc.total>sc.done)?` · 剩余约 ${Math.round((sc.total-sc.done)*sc.ms/1000)} s`:'';
    document.getElementById('prog-'+k).textContent=
      `${st} · ${sc.done}/${sc.total} 像素 · ${sc.rows} 行${sc.ms?` · ${sc.ms.toFixed(2)} ms/px`:''}${eta}`;
    const tb=document.getElementById('stats-'+k);const tot=sc.names.reduce((a,b)=>a+b.pixels,0)||1;
    tb.innerHTML=sc.names.filter(n=>n.pixels).sort((a,b)=>b.pixels-a.pixels).map(n=>
      `<tr><td><span class="sw" style="background:${n.color}"></span>${n.zh}</td>
       <td class="n">${n.pixels}</td><td class="n">${(100*n.pixels/tot).toFixed(2)}%</td></tr>`).join('')
      ||'<tr><td colspan="3"><small>还没有像素</small></td></tr>';
    const pbox=document.getElementById('probe-'+k), pr=S.probe;
    if(pr && pr.key===k){
      if(pr.state==='pending'){
        pbox.innerHTML='<small>探查中…（板卡算完当前这次计算后回结果）</small>';
      }else if(pr.state==='error'){
        pbox.innerHTML='<small>探查失败：'+(pr.error||'未知原因')+'</small>';
      }else{
        pbox.innerHTML=`<b>行 ${pr.row} · 列 ${pr.col}</b> 类别 <b>${pr.cls}</b> · 置信度 <b>${(100*pr.conf).toFixed(2)}%</b> · 字 ${pr.word}`
          +`<div class="lg">${(pr.logits||[]).map(l=>`<span>类${l.cls}: ${(l.q16/65536).toFixed(3)}</span>`).join('')}</div>`;
      }
    }
  }
  document.getElementById('log').textContent=(S.log||[]).join('\\n');
  setTimeout(tick,700);
}
buildCards();tick();
</script></body></html>"""


def make_server(args, backend):
    class Server(ThreadingHTTPServer):
        daemon_threads = True
        # Windows 上 SO_REUSEADDR 等于「允许别的进程抢同一个端口」，
        # 会出现两个服务同时 PING 板卡（板卡只认一个 peer），所以关掉。
        allow_reuse_address = False

        def server_bind(self):
            # 跳过 HTTPServer.server_bind 里的 socket.getfqdn 反向解析（个别网络环境下会卡住）
            from socketserver import TCPServer
            TCPServer.server_bind(self)
            host, port = self.server_address[:2]
            self.server_name = str(host)
            self.server_port = port

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path in ("/", "/index.html"):
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path == "/api/state":
                self._json(backend.state_json())
            elif u.path == "/api/map":
                key = (q.get("s") or [""])[0]
                blob = backend.map_png(key) if key in backend.scenes else None
                if blob is None:
                    self._send(404, b"no map", "text/plain; charset=utf-8")
                else:
                    self._send(200, blob, "image/png")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/api/start":
                key = (q.get("s") or [""])[0]
                region = (q.get("region") or ["64x64"])[0]
                if key not in backend.scenes:
                    return self._json(dict(ok=False, error="没有这个场景"), 400)
                try:
                    ok, err = backend.start(key, region)
                except Exception as exc:                      # noqa: BLE001
                    return self._json(dict(ok=False, error=str(exc)), 400)
                return self._json(dict(ok=ok, error=err))
            if u.path == "/api/probe":
                key = (q.get("s") or [""])[0]
                if key not in backend.scenes:
                    return self._json(dict(ok=False, error="没有这个场景"), 400)
                try:
                    row = int((q.get("row") or ["0"])[0])
                    col = int((q.get("col") or ["0"])[0])
                    ok, err = backend.probe_at(key, row, col)
                except Exception as exc:                      # noqa: BLE001
                    return self._json(dict(ok=False, error=str(exc)), 400)
                return self._json(dict(ok=ok, error=err))
            if u.path == "/api/stop":
                backend.stop()
                return self._json(dict(ok=True))
            if u.path == "/api/save":
                key = (q.get("s") or [""])[0]
                if key not in backend.scenes:
                    return self._json(dict(ok=False, error="没有这个场景"), 400)
                d = backend.save(key)
                return self._json(dict(ok=bool(d), dir=d, error="" if d else "还没有结果"))
            return self._json(dict(ok=False, error="未知接口"), 404)

    return Server((args.host, args.web_port), Handler)


def check_page_script():
    """用 node --check 验一遍页面里的内联 JS。

    页面脚本一旦有语法错误，整段 JS 都不会执行：顶栏永远停在“连接中…”、卡片也不出现，
    而且刷新没用（服务器吐出来的还是坏的那份）。构建/启动时验一下最省事。
    返回 (ok, 错误文本) 或 None（没装 node）。
    """
    import re
    import shutil
    import subprocess
    import tempfile
    node = shutil.which("node")
    if not node:
        return None
    m = re.search(r"<script>(.*)</script>", PAGE, re.S)
    if not m:
        return (False, "PAGE 里找不到 <script> 段")
    path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
            fh.write(m.group(1))
            path = fh.name
        out = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=20)
        return (out.returncode == 0, (out.stderr or "")[:600])
    except Exception as exc:                      # noqa: BLE001
        return (False, "调用 node 失败：%s" % exc)
    finally:
        if path:
            try:
                Path(path).unlink()
            except OSError:
                pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="浏览器版小地面站")
    ap.add_argument("--board", default="192.168.1.10")
    ap.add_argument("--port", type=int, default=5010)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--web-port", type=int, default=8770)
    ap.add_argument("--session", default="5a5a0001")
    ap.add_argument("--no-board", action="store_true", help="只看页面，不连板卡")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    backend = Backend(args)
    try:
        httpd = make_server(args, backend)
    except OSError as exc:
        print("起不来：端口 %d 已被占用（%s）。" % (args.web_port, exc))
        print("要么先关掉已经在跑的那个，要么换端口：--web-port 8771")
        return 2
    url = "http://%s:%d/" % (args.host, args.web_port)
    print("小地面站：%s   （Ctrl+C 结束）" % url)
    chk = check_page_script()
    if chk is not None:
        if chk[0]:
            print("页面脚本语法：OK")
        else:
            print("!! 页面脚本有语法错误——网页会一直停在「连接中…」，先修 PAGE 里的 JS：")
            print(chk[1])
    if not args.no_board:
        print("板卡：%s:%d  会话 %s" % (args.board, args.port, args.session))
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n再见")
    finally:
        httpd.server_close()
        if backend.link:
            backend.link.stop_evt.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
