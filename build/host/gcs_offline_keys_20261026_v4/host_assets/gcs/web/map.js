'use strict';
// 地图：离屏图层、视图变换、推扫无人机、交互（平移 / 探查 / 框选 / 地块）
const MapView = (() => {
  const cv = $('#map'), ctx = cv.getContext('2d');
  let dpr = 1, cw = 0, ch = 0, needDraw = true;
  const L = {};              // 离屏画布与 ImageData：pred / conf / err / gt / predB / diff
  const mk = () => { const c = document.createElement('canvas'); c.width = S.W; c.height = S.H; return { c, x: c.getContext('2d'), d: null, dirty: false }; };

  function confRGBA(v) {           // 低置信亮（红→橙），高置信暗蓝半透明
    const t = v / 255;
    if (t < 0.5) return [255, 45 + 150 * (t / 0.5), 60, 235];
    if (t < 0.8) return [255 - 200 * ((t - 0.5) / 0.3), 195, 60 + 120 * ((t - 0.5) / 0.3), 200];
    return [20, 110, 200, 110];
  }

  function resetScene() {
    for (const k of ['pred', 'conf', 'err', 'gt', 'predB', 'diff']) {
      L[k] = mk(); L[k].d = L[k].x.createImageData(S.W, S.H);
    }
    const g = L.gt.d.data;
    for (let i = 0; i < S.gt.length; i++) {
      const c = S.gt[i]; if (!c) continue;
      const p = S.palRGB[c]; g[4 * i] = p[0]; g[4 * i + 1] = p[1]; g[4 * i + 2] = p[2]; g[4 * i + 3] = 255;
    }
    L.gt.x.putImageData(L.gt.d, 0, 0);
    fit(); dirty();
  }

  function setPx(d, i, rgba) { d[4 * i] = rgba[0]; d[4 * i + 1] = rgba[1]; d[4 * i + 2] = rgba[2]; d[4 * i + 3] = rgba[3]; }
  const CLEAR = [0, 0, 0, 0];

  function paintA(i) {
    const r = S.runs[S.runA], c = r.s.source === 'board' && !r.seen?.[i] ? 0 : r.pred[i];
    if (!c) { setPx(L.pred.d.data, i, CLEAR); setPx(L.conf.d.data, i, CLEAR); setPx(L.err.d.data, i, CLEAR); }
    else {
      const p = S.palRGB[c];
      setPx(L.pred.d.data, i, S.hidden.has(c) ? CLEAR : [p[0], p[1], p[2], 255]);
      setPx(L.conf.d.data, i, confRGBA(r.conf[i]));
      const g = S.gt[i];
      setPx(L.err.d.data, i, !g ? CLEAR : g !== c ? [255, 30, 90, 255] : [30, 200, 120, 70]);
    }
    L.pred.dirty = L.conf.dirty = L.err.dirty = true;
    if (S.runB) paintDiff(i);
  }
  function paintB(i) {
    const r = S.runs[S.runB], c = r.s.source === 'board' && !r.seen?.[i] ? 0 : r.pred[i];
    const p = S.palRGB[c] || [0, 0, 0];
    setPx(L.predB.d.data, i, !c || S.hidden.has(c) ? CLEAR : [p[0], p[1], p[2], 255]);
    L.predB.dirty = true;
    paintDiff(i);
  }
  function paintDiff(i) {
    const a = S.runs[S.runA], b = S.runs[S.runB];
    const ch = a && b && (a.s.source!=='board'||a.seen?.[i]) && (b.s.source!=='board'||b.seen?.[i]) && a.pred[i] && b.pred[i] && a.pred[i] !== b.pred[i];
    setPx(L.diff.d.data, i, ch ? [255, 0, 220, 255] : CLEAR);
    L.diff.dirty = true;
  }
  function repaintAll() {
    for (const k of ['pred', 'conf', 'err', 'predB', 'diff']) L[k].d.data.fill(0);
    const n = S.H * S.W;
    if (S.runA && S.runs[S.runA]?.loaded) for (let i = 0; i < n; i++) paintA(i);
    if (S.runB && S.runs[S.runB]?.loaded) for (let i = 0; i < n; i++) paintB(i);
    for (const k of ['pred', 'conf', 'err', 'predB', 'diff']) L[k].dirty = true;
    dirty();
  }

  // ---------- 视图 ----------
  function resize() {
    dpr = window.devicePixelRatio || 1;
    const r = cv.getBoundingClientRect(); cw = r.width; ch = r.height;
    cv.width = Math.round(cw * dpr); cv.height = Math.round(ch * dpr);
    dirty();
  }
  function fit() {
    if (!S.W) return;
    const pad = 40, k = Math.min((cw - 2 * pad) / S.W, (ch - 2 * pad) / S.H);
    S.view.k = Math.max(k, 0.1); S.view.x = (cw - S.W * S.view.k) / 2; S.view.y = (ch - S.H * S.view.k) / 2;
    dirty();
  }
  function flyTo(row, col, k = null) {
    const v = S.view; if (k) v.k = k;
    v.x = cw / 2 - (col + 0.5) * v.k; v.y = ch / 2 - (row + 0.5) * v.k; dirty();
  }
  const toImg = (sx, sy) => [(sx - S.view.x) / S.view.k, (sy - S.view.y) / S.view.k];
  const toScr = (x, y) => [S.view.x + x * S.view.k, S.view.y + y * S.view.k];
  function dirty() { needDraw = true; }

  // ---------- 绘制 ----------
  function flush() {
    for (const k in L) if (L[k].dirty) { L[k].x.putImageData(L[k].d, 0, 0); L[k].dirty = false; }
  }

  function drawDrone(sx, sy, t, scale = 1) {
    ctx.save(); ctx.translate(sx, sy); ctx.scale(scale, scale);
    ctx.shadowColor = 'rgba(45,212,191,.8)'; ctx.shadowBlur = 12;
    ctx.strokeStyle = '#e6fffb'; ctx.lineWidth = 2.2;
    ctx.beginPath(); ctx.moveTo(-11, -11); ctx.lineTo(11, 11); ctx.moveTo(11, -11); ctx.lineTo(-11, 11); ctx.stroke();
    for (const [dx, dy] of [[-11, -11], [11, -11], [-11, 11], [11, 11]]) {
      ctx.beginPath(); ctx.arc(dx, dy, 7, 0, Math.PI * 2); ctx.strokeStyle = 'rgba(45,212,191,.9)'; ctx.lineWidth = 1.2; ctx.stroke();
      const a = t * 0.03 + dx; ctx.beginPath();
      ctx.moveTo(dx + 6 * Math.cos(a), dy + 6 * Math.sin(a)); ctx.lineTo(dx - 6 * Math.cos(a), dy - 6 * Math.sin(a));
      ctx.strokeStyle = 'rgba(230,255,251,.7)'; ctx.stroke();
    }
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#0f3a33'; ctx.strokeStyle = '#2dd4bf'; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.roundRect(-6, -7, 12, 14, 3); ctx.fill(); ctx.stroke();
    ctx.fillStyle = '#2dd4bf'; ctx.beginPath(); ctx.moveTo(0, 12); ctx.lineTo(-4, 7); ctx.lineTo(4, 7); ctx.fill();   // 航向（沿行增加方向）
    ctx.restore();
  }

  function draw(t) {
    flush();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cw, ch);
    if (!S.W) return;
    const v = S.view;
    ctx.save(); ctx.translate(v.x, v.y); ctx.scale(v.k, v.k);
    ctx.imageSmoothingEnabled = false;
    ctx.shadowColor = 'rgba(0,0,0,.6)'; ctx.shadowBlur = 20 / v.k;
    ctx.fillStyle = '#05080c'; ctx.fillRect(0, 0, S.W, S.H); ctx.shadowBlur = 0;
    if (S.layers.base && S.base) ctx.drawImage(S.base, 0, 0, S.W, S.H);
    if (S.layers.gt) { ctx.globalAlpha = S.opacity; ctx.drawImage(L.gt.c, 0, 0); ctx.globalAlpha = 1; }

    const overlayA = () => {
      ctx.globalAlpha = S.opacity;
      if (S.diffOnly && S.runB) ctx.drawImage(L.diff.c, 0, 0);
      else {
        if (S.layers.pred) ctx.drawImage(L.pred.c, 0, 0);
        if (S.layers.conf) ctx.drawImage(L.conf.c, 0, 0);
        if (S.layers.err) ctx.drawImage(L.err.c, 0, 0);
      }
      ctx.globalAlpha = 1;
    };
    if (S.runB && !S.diffOnly) {
      const [xs] = toImg(S.swipeX * cw, 0);
      ctx.save(); ctx.beginPath(); ctx.rect(0, 0, Math.max(0, xs), S.H); ctx.clip(); overlayA(); ctx.restore();
      ctx.save(); ctx.beginPath(); ctx.rect(xs, 0, S.W, S.H); ctx.clip();
      ctx.globalAlpha = S.opacity; if (S.layers.pred) ctx.drawImage(L.predB.c, 0, 0); ctx.globalAlpha = 1; ctx.restore();
    } else overlayA();

    const lw = 1 / v.k;
    ctx.strokeStyle = '#2a3b50'; ctx.lineWidth = lw; ctx.strokeRect(0, 0, S.W, S.H);

    // 地块
    if (S.layers.parcels) {
      S.parcels.forEach((p, k) => {
        ctx.beginPath(); p.pts.forEach(([x, y], j) => j ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.closePath();
        ctx.fillStyle = 'rgba(56,189,248,.10)'; ctx.fill();
        ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 2 * lw; ctx.setLineDash([]); ctx.stroke();
        const cx = p.pts.reduce((s, q) => s + q[0], 0) / p.pts.length, cy = p.pts.reduce((s, q) => s + q[1], 0) / p.pts.length;
        label(p.name, cx, cy, '#38bdf8');
      });
    }
    if (S.poly && S.poly.length) {
      ctx.beginPath(); S.poly.forEach(([x, y], j) => j ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
      if (S.polyHover) ctx.lineTo(...S.polyHover);
      ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 2 * lw; ctx.setLineDash([6 * lw, 4 * lw]); ctx.stroke(); ctx.setLineDash([]);
    }
    // 斑块 / 采样 / 标注
    if (S.layers.marks) {
      S.patches.forEach((p, k) => {
        const [r0, c0, r1, c1] = p.bbox;
        ctx.strokeStyle = p.kind === '低置信' ? '#f59e0b' : '#38bdf8';
        ctx.lineWidth = (S.hilite === k ? 3 : 1.5) * lw;
        ctx.strokeRect(c0 - 0.5, r0 - 0.5, c1 - c0 + 2, r1 - r0 + 2);
      });
      S.sampling.forEach((s, k) => pin(s.col + 0.5, s.row + 0.5, `S${k + 1}`, '#f43f5e'));
      S.annotations.forEach(([r, c]) => {
        ctx.fillStyle = '#ffff00'; ctx.strokeStyle = '#000'; ctx.lineWidth = lw;
        ctx.beginPath(); ctx.arc(c + 0.5, r + 0.5, Math.max(0.7, 3.5 * lw), 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      });
    }
    // 选框与运行区域
    const rect = S.drag?.rect || S.rect;
    if (rect) {
      const [r0, c0, h, w] = rect;
      ctx.strokeStyle = '#2dd4bf'; ctx.lineWidth = 2 * lw; ctx.setLineDash([6 * lw, 4 * lw]);
      ctx.strokeRect(c0, r0, w, h); ctx.setLineDash([]);
      label(`${h}×${w} · ${fmt.f(h * w * S.gsd * S.gsd, 0)} m²`, c0 + w / 2, r0 - 8 * lw, '#2dd4bf');
    }
    // 探查点
    if (S.probe) {
      const { row, col } = S.probe;
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5 * lw;
      ctx.strokeRect(col - 3, row - 3, 7, 7);
      ctx.beginPath(); ctx.moveTo(col + 0.5, row - 8); ctx.lineTo(col + 0.5, row - 3); ctx.moveTo(col + 0.5, row + 4); ctx.lineTo(col + 0.5, row + 9);
      ctx.moveTo(col - 8, row + 0.5); ctx.lineTo(col - 3, row + 0.5); ctx.moveTo(col + 4, row + 0.5); ctx.lineTo(col + 9, row + 0.5); ctx.stroke();
    }
    ctx.restore();

    // 推扫线 + 无人机（屏幕坐标）
    const run = !S.viewCleared&&S.runA===S.live?S.runs[S.live]:null;
    if (run && run.s.kind !== 'eval' && ['running', 'paused'].includes(run.s.status) && run.row != null) {
      const [r0, c0, h, w] = run.s.rect || [0, 0, S.H, S.W];
      const [x0, y] = toScr(c0, run.row + 1), [x1] = toScr(c0 + w, 0);
      const g = ctx.createLinearGradient(0, y - 40, 0, y + 2);
      g.addColorStop(0, 'rgba(45,212,191,0)'); g.addColorStop(1, 'rgba(45,212,191,.35)');
      ctx.fillStyle = g; ctx.fillRect(x0, y - 40, x1 - x0, 42);
      ctx.strokeStyle = '#5eead4'; ctx.lineWidth = 2; ctx.shadowColor = '#2dd4bf'; ctx.shadowBlur = 10;
      ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke(); ctx.shadowBlur = 0;
      ctx.strokeStyle = 'rgba(94,234,212,.35)'; ctx.setLineDash([4, 5]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo((x0 + x1) / 2, y); ctx.lineTo((x0 + x1) / 2, toScr(0, r0 + h)[1]); ctx.stroke(); ctx.setLineDash([]);
      drawDrone((x0 + x1) / 2, y + 16, t);
      if (S.follow) { const [, yy] = toScr(0, run.row); if (yy < ch * 0.3 || yy > ch * 0.7) { S.view.y += ch / 2 - yy; } }
    }

    function label(txt, x, y, color) {
      const [sx, sy] = [x, y];
      ctx.save(); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const [px, py] = toScr(sx, sy);
      ctx.font = '12px "Segoe UI", "Microsoft YaHei"'; const w = ctx.measureText(txt).width + 10;
      ctx.fillStyle = 'rgba(11,16,22,.85)'; ctx.fillRect(px - w / 2, py - 9, w, 18);
      ctx.fillStyle = color; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(txt, px, py);
      ctx.restore();
    }
    function pin(x, y, txt, color) {
      ctx.save(); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const [px, py] = toScr(x, y);
      ctx.fillStyle = color; ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(px, py - 14, 9, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(px - 4, py - 7); ctx.lineTo(px, py); ctx.lineTo(px + 4, py - 7); ctx.fill();
      ctx.fillStyle = '#fff'; ctx.font = 'bold 9px Consolas'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(txt, px, py - 14); ctx.restore();
    }
    scaleBar();
  }

  function scaleBar() {
    const pxPerM = S.view.k / S.gsd, target = 90 / pxPerM;
    const p = Math.pow(10, Math.floor(Math.log10(target))), m = [1, 2, 5, 10].map(x => x * p).filter(x => x <= target).pop() || p;
    $('#scalebar-bar').style.width = `${m * pxPerM}px`;
    $('#scalebar-txt').textContent = m >= 1000 ? `${m / 1000} km` : `${m} m`;
  }

  function loop(t) {
    const run = !S.viewCleared&&S.runA===S.live?S.runs[S.live]:null;
    const anim = run && ['running', 'paused'].includes(run.s.status);
    if (needDraw || anim) { needDraw = false; draw(t); }
    requestAnimationFrame(loop);
  }

  // ---------- 交互 ----------
  function pixelAt(e) {
    const r = cv.getBoundingClientRect(), [x, y] = toImg(e.clientX - r.left, e.clientY - r.top);
    return [Math.floor(y), Math.floor(x), x, y];
  }
  const inside = (row, col) => row >= 0 && col >= 0 && row < S.H && col < S.W;

  cv.addEventListener('wheel', e => {
    e.preventDefault();
    const r = cv.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
    const k0 = S.view.k, k = Math.min(60, Math.max(0.2, k0 * Math.exp(-e.deltaY * 0.0015)));
    S.view.x = sx - (sx - S.view.x) * k / k0; S.view.y = sy - (sy - S.view.y) * k / k0; S.view.k = k; dirty();
  }, { passive: false });

  cv.addEventListener('pointerdown', e => {
    if (!S.W) return;
    cv.setPointerCapture(e.pointerId);
    const [row, col, x, y] = pixelAt(e);
    S.drag = { sx: e.clientX, sy: e.clientY, vx: S.view.x, vy: S.view.y, row, col, moved: false,
               pan: S.tool === 'pan' || e.button === 1 || e.button === 2 };
  });
  cv.addEventListener('pointermove', e => {
    const [row, col, x, y] = pixelAt(e);
    Panels.cursor(row, col, inside(row, col));
    if (S.tool === 'poly' && S.poly) { S.polyHover = [x, y]; dirty(); }
    const d = S.drag; if (!d) return;
    if (Math.hypot(e.clientX - d.sx, e.clientY - d.sy) > 3) d.moved = true;
    if (d.pan) { S.view.x = d.vx + e.clientX - d.sx; S.view.y = d.vy + e.clientY - d.sy; dirty(); }
    else if (S.tool === 'box' && d.moved) {
      const r0 = Math.max(0, Math.min(d.row, row)), c0 = Math.max(0, Math.min(d.col, col));
      const r1 = Math.min(S.H - 1, Math.max(d.row, row)), c1 = Math.min(S.W - 1, Math.max(d.col, col));
      d.rect = [r0, c0, r1 - r0 + 1, c1 - c0 + 1]; dirty();
    }
  });
  cv.addEventListener('pointerup', e => {
    const d = S.drag; S.drag = null; if (!d) return;
    const [row, col, x, y] = pixelAt(e);
    if (S.tool === 'box' && d.rect) { Panels.setRect(d.rect); }
    else if (!d.moved && (S.tool === 'pan'||S.tool === 'box') && e.button===0 && inside(row, col)) Panels.probe(row, col);
    else if (!d.moved && S.tool === 'poly' && inside(row, col)) { (S.poly = S.poly || []).push([x, y]); }
    dirty();
  });
  cv.addEventListener('dblclick', () => {
    if (S.tool !== 'poly' || !S.poly) return;
    const pts = S.poly.slice(0, -1);          // 双击的第二下会多压一个点
    S.poly = null; S.polyHover = null;
    if (pts.length >= 3) { Panels.addParcel(pts); Panels.showTab('parcel'); }
    dirty();
  });
  cv.addEventListener('contextmenu', e => e.preventDefault());
  window.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    const k = e.key.toLowerCase();
    if (k === 'escape') { S.poly = null; S.polyHover = null; dirty(); }
    else if (k === 'f') fit();
    else if (k === 'v') Panels.setTool('pan');
    else if (k === 'b') Panels.setTool('box');
    else if (k === 'p') Panels.setTool('poly');
  });

  // 滑动对比条
  const sw = $('#swipe');
  sw.addEventListener('pointerdown', e => {
    sw.setPointerCapture(e.pointerId);
    const move = ev => { const r = cv.getBoundingClientRect(); S.swipeX = Math.min(0.98, Math.max(0.02, (ev.clientX - r.left) / r.width)); sw.style.left = `${S.swipeX * 100}%`; dirty(); };
    const up = () => { sw.removeEventListener('pointermove', move); sw.removeEventListener('pointerup', up); };
    sw.addEventListener('pointermove', move); sw.addEventListener('pointerup', up);
  });

  new ResizeObserver(resize).observe(cv);
  requestAnimationFrame(loop);
  return { resetScene, paintA, paintB, repaintAll, fit, flyTo, dirty, resize, flush, layer: k => L[k] };
})();
