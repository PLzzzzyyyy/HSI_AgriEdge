'use strict';
// 三维高光谱立方体（CSS 3D）：顶面 = 假彩色 + 分类叠加（或剥离后的单波段），四个侧面 = 边缘像素的全部波段
const Cube = (() => {
  const C = { on: false, yaw: -38, pitch: -30, zoom: 1, peel: 0, spin: false, key: null, r: null, src: null, band: null, drag: null };
  const stage = $('#cube-stage'), cube = $('#cube');
  const F = {}; for (const n of ['top', 'front', 'back', 'left', 'right', 'bottom']) F[n] = cube.querySelector('.face.' + n);

  // turbo 色图（Google，多项式近似）
  const LUT = new Uint8Array(256 * 3);
  const TURBO = [[0.13572138, 4.61539260, -42.66032258, 132.13108234, -152.94239396, 59.28637943],
                 [0.09140261, 2.19418839, 4.84296658, -14.18503333, 4.27729857, 2.82956604],
                 [0.10667330, 12.64194608, -60.58204836, 110.36276771, -89.90310912, 27.34824973]];
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    TURBO.forEach((k, ch) => { LUT[3 * i + ch] = 255 * Math.max(0, Math.min(1, k.reduceRight((a, c) => a * t + c, 0))); });
  }
  function colorize(u8, n, rows, flip) {           // u8 行主序 (rows, n) → ImageData；flip 时每行左右翻转
    const im = new ImageData(n, rows), d = im.data;
    for (let b = 0; b < rows; b++) for (let i = 0; i < n; i++) {
      const v = u8[b * n + (flip ? n - 1 - i : i)], o = 4 * (b * n + i);
      d[o] = LUT[3 * v]; d[o + 1] = LUT[3 * v + 1]; d[o + 2] = LUT[3 * v + 2]; d[o + 3] = 255;
    }
    return im;
  }
  function toCanvas(im) { const c = document.createElement('canvas'); c.width = im.width; c.height = im.height; c.getContext('2d').putImageData(im, 0, 0); return c; }

  const rect = () => $('#sel-cube-scope').value === 'rect' && S.rect ? S.rect.slice() : [0, 0, S.H, S.W];
  const query = () => { const [r0, c0, h, w] = C.r; return `r0=${r0}&c0=${c0}&h=${h}&w=${w}`; };

  async function load() {
    if (!S.info) return;
    const r = rect(), key = `${S.scene}:${r}`;
    if (key === C.key) return;
    C.key = key; C.r = r; C.band = null;
    const [, , h, w] = r, B = S.info.bands;
    $('#cube-info').innerHTML = `加载立方体边缘光谱…`;
    const buf = new Uint8Array(await (await fetch(`/api/scene/${S.scene}/cube/edges?${query()}`)).arrayBuffer());
    if (key !== C.key) return;
    let o = 0; const part = n => { const a = buf.subarray(o, o + B * n); o += B * n; return a; };
    // 各面画布的 x 方向与面在世界里的走向一致：后面、右面从外侧看是翻转的
    C.src = { front: toCanvas(colorize(part(w), w, B, false)), back: toCanvas(colorize(part(w), w, B, true)),
              left: toCanvas(colorize(part(h), h, B, false)), right: toCanvas(colorize(part(h), h, B, true)) };
    F.top.width = w; F.top.height = h;
    $('#cube-info').innerHTML = `立方体 <b>${h} × ${w} × ${B}</b> 波段 · float32 ${fmt.bytes(h * w * B * 4)} 留在机上 · 下传分类结果 ${fmt.bytes(h * w * 4)}`;
    layout(); drawSides(); C.peel ? loadBand() : drawTop();
  }

  // ---------- 几何 ----------
  function layout() {
    if (!C.r || !S.info) return;
    const [, , h, w] = C.r, B = S.info.bands, st = stage.getBoundingClientRect();
    const m = Math.max(w, h), u = C.zoom * Math.min(st.width * 0.62 / Math.hypot(w, h), st.height * 0.62 / (0.55 * m + 0.5 * h));
    const W = w * u, D = h * u, Hf = 0.5 * m * u, Hc = Hf * (B - C.peel) / B;
    const size = (el, a, b) => { el.style.width = `${a}px`; el.style.height = `${b}px`; };
    size(F.top, W, D); size(F.bottom, W, D); size(F.front, W, Hc); size(F.back, W, Hc); size(F.left, D, Hc); size(F.right, D, Hc);
    F.top.style.transform = 'rotateX(90deg)';
    F.front.style.transform = `translateZ(${D}px)`;
    F.back.style.transform = `translateX(${W}px) rotateY(180deg)`;
    F.left.style.transform = 'rotateY(-90deg)';
    F.right.style.transform = `translate3d(${W}px, 0, ${D}px) rotateY(90deg)`;
    F.bottom.style.transform = `translate3d(0, ${Hc}px, ${D}px) rotateX(-90deg)`;
    C.geo = { W, D, Hf, Hc };
    orient();
  }
  function orient() {
    if (!C.geo) return;
    const { W, D, Hf, Hc } = C.geo;
    cube.style.transform = `rotateX(${C.pitch}deg) rotateY(${C.yaw}deg) translate3d(${-W / 2}px, ${Hf / 2 - Hc}px, ${-D / 2}px)`;
  }

  // ---------- 贴图 ----------
  function drawSides() {
    if (!C.src) return;
    const B = S.info.bands, rows = B - C.peel;
    for (const n of ['front', 'back', 'left', 'right']) {
      const s = C.src[n], c = F[n];
      c.width = s.width; c.height = rows;
      c.getContext('2d').drawImage(s, 0, C.peel, s.width, rows, 0, 0, s.width, rows);
    }
  }
  function drawTop() {
    if (!C.r || !S.info) return;
    const [r0, c0, h, w] = C.r, x = F.top.getContext('2d');
    if (C.peel) { if (C.band) x.putImageData(C.band, 0, 0); return; }
    x.globalAlpha = 1; x.fillStyle = '#05080c'; x.fillRect(0, 0, w, h);
    if (S.layers.base && S.base) x.drawImage(S.base, c0, r0, w, h, 0, 0, w, h);
    MapView.flush();
    x.globalAlpha = S.opacity;
    for (const k of ['gt', 'pred', 'conf', 'err']) if (S.layers[k] && (k === 'gt' || S.runA)) x.drawImage(MapView.layer(k).c, c0, r0, w, h, 0, 0, w, h);
    x.globalAlpha = 1;
    const lw = Math.max(1, Math.max(w, h) / 300);
    const run = S.runs[S.live];
    if (run && run.s.status === 'running' && run.row != null && run.s.kind !== 'eval' && run.row >= r0 && run.row < r0 + h) {
      x.fillStyle = '#5eead4'; x.fillRect(0, run.row - r0 + 1, w, lw * 1.5);
    }
    if (S.probe && S.probe.row >= r0 && S.probe.row < r0 + h && S.probe.col >= c0 && S.probe.col < c0 + w) {
      x.strokeStyle = '#fff'; x.lineWidth = lw; x.strokeRect(S.probe.col - c0 - 3, S.probe.row - r0 - 3, 7, 7);
    }
  }
  async function loadBand() {
    const b = C.peel;
    if (!b) { drawTop(); return; }
    if (C.bandBusy) return;
    C.bandBusy = true;
    const [, , h, w] = C.r, key = C.key;
    try {
      const u8 = new Uint8Array(await (await fetch(`/api/scene/${S.scene}/cube/band/${b}?${query()}`)).arrayBuffer());
      if (key === C.key && b === C.peel) { C.band = colorize(u8, w, h, false); drawTop(); }
    } finally {
      C.bandBusy = false;
      // Resume the current selection if its request was blocked by this stale one.
      if (key !== C.key || b !== C.peel) loadBand();
    }
  }

  // ---------- 交互 ----------
  function setPeel(v) {
    C.peel = v;
    const wl = S.info.wavelengths[v];
    $('#txt-peel').textContent = v ? `顶面：波段 ${v + 1} · ≈${fmt.f(wl, 0)} nm` : '顶面：假彩色 + 分类';
    layout(); drawSides(); loadBand();
  }
  $('#rng-peel').oninput = e => setPeel(+e.target.value);
  $('#chk-spin').onchange = e => { C.spin = e.target.checked; };
  $('#btn-cube-reset').onclick = () => { C.yaw = -38; C.pitch = -30; C.zoom = 1; $('#rng-peel').value = 0; setPeel(0); };
  $('#sel-cube-scope').onchange = e => {
    if (e.target.value === 'rect' && !S.rect) { e.target.value = 'scene'; toast('先用"框选区域"在二维地图上框一块'); return; }
    load();
  };

  stage.addEventListener('pointerdown', e => {
    stage.setPointerCapture(e.pointerId);
    C.drag = { x: e.clientX, y: e.clientY, yaw: C.yaw, pitch: C.pitch, moved: false, top: e.target === F.top, ox: e.offsetX, oy: e.offsetY };
  });
  stage.addEventListener('pointermove', e => {
    const d = C.drag; if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (Math.hypot(dx, dy) > 3) d.moved = true;
    if (!d.moved) return;
    C.yaw = d.yaw + dx * 0.35; C.pitch = Math.max(-89, Math.min(89, d.pitch - dy * 0.35)); orient();
  });
  stage.addEventListener('pointerup', () => {
    const d = C.drag; C.drag = null;
    if (!d || d.moved || !d.top || !C.geo) return;
    const [r0, c0, h, w] = C.r;
    const col = c0 + Math.floor(d.ox / C.geo.W * w), row = r0 + Math.floor(d.oy / C.geo.D * h);
    if (row >= r0 && row < r0 + h && col >= c0 && col < c0 + w) Panels.probe(row, col);
  });
  stage.addEventListener('wheel', e => {
    e.preventDefault();
    C.zoom = Math.min(4, Math.max(0.3, C.zoom * Math.exp(-e.deltaY * 0.0012))); layout();
  }, { passive: false });
  new ResizeObserver(() => C.on && layout()).observe(stage);

  let lastTop = 0;
  (function loop(t) {
    if (C.on) {
      if (C.spin && !C.drag) { C.yaw += 0.12; orient(); }
      if (t - lastTop > 250 && !C.peel) { lastTop = t; drawTop(); }
    }
    requestAnimationFrame(loop);
  })(0);

  // ---------- 视图切换 ----------
  function show(on) {
    C.on = on;
    $('#cube-wrap').hidden = !on;
    $('#map-wrap').classList.toggle('mode3d', on);
    $$('#seg-view button').forEach(b => b.classList.toggle('on', (b.dataset.view === '3d') === on));
    if (on) { load(); layout(); } else MapView.dirty();
  }
  $$('#seg-view button').forEach(b => b.onclick = () => show(b.dataset.view === '3d'));
  window.addEventListener('keydown', e => {
    if (['INPUT', 'SELECT'].includes(e.target.tagName) || e.target.isContentEditable) return;
    if (e.key.toLowerCase() === 'c') show(!C.on);
  });

  return {
    onScene() {
      C.key = null; C.src = null; C.band = null; C.peel = 0;
      $('#rng-peel').max = S.info.bands - 1; $('#rng-peel').value = 0; $('#txt-peel').textContent = '顶面：假彩色 + 分类';
      $('#sel-cube-scope').value = 'scene';
      if (C.on) load();
    },
    onRect() { if (C.on && $('#sel-cube-scope').value === 'rect') load(); },
    show,
  };
})();
