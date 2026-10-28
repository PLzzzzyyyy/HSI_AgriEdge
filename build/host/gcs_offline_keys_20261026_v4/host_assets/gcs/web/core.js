'use strict';
// 地面站前端 · 公共状态、工具函数、景加载、运行数据
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

const S = {
  scene: null, info: null, version: null, H: 0, W: 0, gsd: 1,
  palRGB: [], base: null, gt: null, split: null,
  view: { k: 1, x: 0, y: 0 },
  layers: { base: true, pred: true, conf: false, gt: false, err: false, marks: true, parcels: true },
  opacity: 0.8, tool: 'pan', kind: 'scan', rect: null, drag: null, poly: null,
  runs: {}, runA: null, runB: null, live: null, follow: false, hidden: new Set(),
  patches: [], sampling: [], annotations: [], parcels: [], probe: null, hilite: null,
  rateHist: [], ws: null, source: null, telemetry: null, lastTick: null,
  swipeX: 0.5, diffOnly: false, loop: {}, pendingTag: null,
  ledger: null, lastAnalysis: null, comparison: null,
  viewCleared: false, hiddenThrough: 0,viewGeneration:0,
};
try { S.hiddenThrough=Math.max(0,Number(sessionStorage.getItem('gcs.hiddenThrough.v1'))||0); } catch {}
function rememberClear() {
  S.viewGeneration++;
  S.hiddenThrough=Math.max(S.hiddenThrough,...Object.values(S.runs).map(r=>r.s.id||0));
  S.viewCleared=true;
  try { sessionStorage.setItem('gcs.hiddenThrough.v1',String(S.hiddenThrough)); } catch {}
}
function taskSelectionRect(run) {
  // A point task still has a real 1x1 board ROI, but is represented by a point
  // marker, never a user-selected rectangle.
  const r=run?.rect;
  return r&&!(r[2]===1&&r[3]===1)?r:null;
}

const fmt = {
  n: v => v == null ? '—' : Number(v).toLocaleString('en-US'),
  f: (v, d = 1) => v == null || !isFinite(v) ? '—' : Number(v).toFixed(d),
  pct: (v, d = 1) => v == null ? '—' : (100 * v).toFixed(d) + '%',
  dur: s => {
    if (s == null || !isFinite(s)) return '—';
    s = Math.max(0, Math.round(s));
    const m = Math.floor(s / 60), r = s % 60;
    return m ? `${m}:${String(r).padStart(2, '0')}` : `${r} s`;
  },
  bytes: b => b == null ? '—' : b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(1) + ' KB' :
    b < 1073741824 ? (b / 1048576).toFixed(2) + ' MB' : (b / 1073741824).toFixed(2) + ' GB',
};

function hexRGB(h) { const n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
function clsName(c) { return Number.isInteger(c) && c > 0 && S.info ? (S.info.display_classes?.[c-1] || `类别 ${c-1}`) : '无'; }
function classNames() { return S.info ? S.info.classes.map((_,i)=>clsName(i+1)) : []; }
function clsColor(c) { return S.info ? S.info.palette[c] : '#000'; }
function liveInSelection() {
  const run=S.runs[S.live]?.s;
  return !S.viewCleared && !S.keyScenePreview && (!S.runA||S.runA===S.live) && run?.scene===S.scene && run.version===S.version ? run : null;
}

function toast(msg, ms = 2200) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => t.hidden = true, ms);
}

function logLine(msg, level = 'info', t = null) {
  const el = $('#log'), d = document.createElement('div');
  d.className = level;
  d.innerHTML = `<span class="t">${t || new Date().toLocaleTimeString('zh-CN', { hour12: false })}</span>`;
  d.appendChild(document.createTextNode(msg));
  el.appendChild(d);
  while (el.children.length > 500) el.firstChild.remove();
  el.parentElement.scrollTop = el.parentElement.scrollHeight;
}

function send(o) { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(o)); }

function download(name, text, type = 'application/json') {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

// ---------- 运行数据 ----------
function newRun(summary) {
  const n = S.H * S.W;
  return { s: summary, pred: new Uint8Array(n), conf: summary.source === 'board' ? new Float64Array(n) : new Uint8Array(n),
    words: summary.source === 'board' ? new Uint32Array(n) : null, seen: summary.source === 'board' ? new Uint8Array(n) : null, loaded: true };
}

async function loadRun(id) {
  const r = S.runs[id];
  if (!r || r.loaded) return r;
  const scene=S.scene,H=S.H,W=S.W,current=()=>S.runs[id]===r && S.scene===scene && S.H===H && S.W===W;
  if (r.s.source === 'board') {
    r.pred ||= new Uint8Array(H*W); r.conf ||= new Float64Array(H*W);
    if(r.s.board?.task_lifecycle || r.s.board?.full_scene) {
      const response=await fetch(`/api/run/${id}/board_words`);
      if(!response.ok)throw Error(`板端结果恢复失败 HTTP ${response.status}；不以PC或旧结果补齐`);
      const buf=await response.arrayBuffer(),n=H*W;
      if(!current())return null;
      if(buf.byteLength!==5*n)throw Error('板端结果恢复长度错误');
      const words=new Uint32Array(buf,0,n),seen=new Uint8Array(buf,4*n,n);
      for(let i=0;i<n;i++)if(seen[i]>1 || (seen[i] && ((words[i]&0xff00) || (words[i]&255)>=S.info.classes.length)))throw Error('板端恢复CLASS/掩码非法');
      // The HTTP snapshot may precede a concurrent live ROW. Merge immutable
      // words/masks instead of replacing and losing newly received pixels.
      r.words ||= new Uint32Array(n);r.seen ||= new Uint8Array(n);
      for(let i=0;i<n;i++)if(seen[i]){
        if(r.seen[i] && r.words[i]!==words[i])throw Error('历史快照与实时CLASS冲突');
        r.words[i]=words[i];r.seen[i]=1;r.pred[i]=(words[i]&255)+1;r.conf[i]=(words[i]>>>16)/65536*255;
      }
      r.loaded=true;
      BoardPanel.apply(id,r.s.board);
    } else {
      const response=await fetch(`/api/run/${id}/board`);
      if(!response.ok)throw Error(`板端结果恢复失败 HTTP ${response.status}`);
      const b = await response.json();
      if(!current())return null;
      r.loaded=true;
      BoardPanel.apply(id, b);
    }
    return r;
  }
  const resp = await fetch(`/api/run/${id}/data`);
  if (!resp.ok) { delete S.runs[id]; toast(`任务 #${id} 已被服务端清理（只保留最近 16 次）`); return null; }
  const buf = new Uint8Array(await resp.arrayBuffer());
  const n = S.H * S.W;
  r.pred = buf.slice(0, n); r.conf = buf.slice(n, 2 * n); r.loaded = true;
  return r;
}

function applyChunk(buf) {
  const dv = new DataView(buf);
  const id = dv.getUint16(2, true), n = dv.getUint32(4, true);
  const r = S.runs[id];
  if (!r || !r.loaded) return;
  const rows = new Uint16Array(buf, 8, n), cols = new Uint16Array(buf, 8 + 2 * n, n);
  const lab = new Uint8Array(buf, 8 + 4 * n, n), conf = new Uint8Array(buf, 8 + 5 * n, n);
  const isA = id === S.runA, isB = id === S.runB;
  for (let k = 0; k < n; k++) {
    const i = rows[k] * S.W + cols[k];
    r.pred[i] = lab[k]; r.conf[i] = conf[k];
    if (isA) MapView.paintA(i);
    if (isB) MapView.paintB(i);
  }
  if (n) r.row = rows[n - 1];
  if (isA || isB) { MapView.dirty(); Panels.areaDirty = true; }
}

// ---------- 景 ----------
let sceneGeneration=0;
async function loadScene(name) {
  const generation=++sceneGeneration;
  TimingPanel.select(null,null);
  Panels.clearBusiness?.(); Panels.clearComparison?.();
  if (S.live && S.runs[S.live]?.s.status === 'running' && S.runs[S.live]?.s.source !== 'board') send({ cmd: 'stop' });
  toast(`加载 ${name} …`, 8000);
  const response=await fetch(`/api/scene/${name}`);if(!response.ok)throw Error('场景输入不可用');
  const info = await response.json();if(generation!==sceneGeneration)return;
  if(!Array.isArray(info.display_classes)||info.display_classes.length!==info.classes.length||
      info.display_classes.some(n=>typeof n!=='string'||!/[\u4e00-\u9fff]/.test(n)))throw Error('中文类别词表缺失，请更新配套后台后刷新');
  const [gt, split] = await Promise.all([
    fetch(`/api/scene/${name}/gt`).then(r => r.arrayBuffer()),
    fetch(`/api/scene/${name}/split`).then(r => r.arrayBuffer())]);
  const base = await new Promise((res,reject) => { const im = new Image(); im.onload = () => res(im);im.onerror=()=>reject(Error('场景底图不可用')); im.src = `/api/scene/${name}/rgb`; });
  if(generation!==sceneGeneration)return;
  if(gt.byteLength!==info.H*info.W||split.byteLength!==info.H*info.W)throw Error('场景输入尺寸不一致');
  S.scene = name; S.info = info; S.H = info.H; S.W = info.W; S.gsd = info.mission.gsd_m;
  S.keyScenePreview=false;
  S.palRGB = info.palette.map(hexRGB);S.gt = new Uint8Array(gt); S.split = new Uint8Array(split);S.base=base;
  $('#sel-scene').value=name;
  S.runA = S.runB = null; S.rect = null; S.patches = []; S.sampling = []; S.annotations = []; S.parcels = [];
  $('#swipe').hidden=true;$('#swipe-a').textContent='A';$('#swipe-b').textContent='B';
  S.probe = null; S.hilite = null; S.hidden.clear(); S.loop = {}; S.lib = null; S.loopOld = S.loopNew = S.loopWait = S.loopVersion = null;
  for (const r of Object.values(S.runs)) if (r.s.scene !== name) { r.loaded = false; r.pred = r.conf = r.words = r.seen = null; }
  const sel = $('#sel-version');
  sel.innerHTML = info.versions.map(v => `<option value="${v.id}">${v.label}</option>`).join('');
  S.version = info.versions.some(v=>v.id==='v2')?'v2':info.versions[0].id; sel.value = S.version;
  $('#sel-upload').innerHTML = info.versions.filter(v => v.pkg)
    .map(v => `<option value="${v.id}" ${v.deployable===false?'disabled':''}>${v.label} · ${v.deployable===false?'缺少有效板端包':fmt.bytes(v.pkg_bytes)}</option>`).join('');
  MapView.resetScene();
  Panels.onScene();
  if(typeof SpeedPanel!=='undefined')SpeedPanel.configure();
  await Panels.loadParcels(name);
  if(generation!==sceneGeneration)return;
  Loop.render();
  Cube.onScene();
  const last = !S.viewCleared && Object.values(S.runs).filter(r => r.s.scene === name && r.s.version===S.version && r.s.id === S.live).pop();
  if (last) {
    if(last.s.source==='board'){S.rect=taskSelectionRect(last.s);Panels.setKind(S.rect?'region':'scan');}
    await Panels.setAB(last.s.id, null);
  }
  if(generation!==sceneGeneration)return;
  BoardPanel.selectionChanged?.();
  toast(`${name}：${S.H}×${S.W}×${info.bands}，${info.classes.length} 类，GSD ${S.gsd} m`);
}
