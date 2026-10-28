'use strict';
// 右栏与抽屉面板（一）：任务控制、遥测、种植结构、单点探查、页签
const Panels = (() => {
  const P = { areaDirty: true, charts: {} };
  const AX = { axisLine: { lineStyle: { color: '#2a3b50' } }, axisLabel: { color: '#7b8ea3', fontSize: 10 }, splitLine: { lineStyle: { color: '#16212d' } } };
  const TT = { backgroundColor: 'rgba(14,21,30,.95)', borderColor: '#2a3b50', textStyle: { color: '#d6e2ee', fontSize: 12 } };
  P.AX = AX; P.TT = TT;

  P.chart = id => {
    if (!P.charts[id]) P.charts[id] = echarts.init(document.getElementById(id), null, { renderer: 'canvas' });
    return P.charts[id];
  };
  window.addEventListener('resize', () => Object.values(P.charts).forEach(c => c.resize()));

  // ---------- 页签 ----------
  P.showTab = name => {
    $$('#tabs [data-tab]').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    $$('.tab-body').forEach(b => b.hidden = b.dataset.body !== name);
    $('.layout').classList.remove('drawer-min');
    P.tab = name;
    if(name!=='speed')$('.layout').classList.remove('speed-focus');
    setTimeout(() => { Object.values(P.charts).forEach(c => c.resize()); MapView.resize(); }, 0);
    if (name === 'parcel') P.parcels();
    if (name === 'runs') P.runsTable();
    if (name === 'loop') Loop.render();
    if (name === 'eval') P.evalTasks?.();
    if(name==='speed'&&typeof SpeedPanel!=='undefined'){SpeedPanel.render();SpeedPanel.history().catch(e=>toast(e.message));}
  };
  $$('#tabs [data-tab]').forEach(b => b.onclick = () => {
    if(b.dataset.tab==='probe')P.setTool('pan');
    P.showTab(b.dataset.tab);
  });
  $('#btn-drawer').onclick = () => { $('.layout').classList.toggle('drawer-min'); setTimeout(() => { MapView.resize(); Object.values(P.charts).forEach(c => c.resize()); }, 0); };

  // ---------- 工具与图层 ----------
  P.setTool = t => {
    S.tool = t; S.poly = null;
    $$('.rail [data-tool]').forEach(b => b.classList.toggle('active', b.dataset.tool === t));
    MapView.dirty();
  };
  $$('.rail [data-tool]').forEach(b => b.onclick = () => P.setTool(b.dataset.tool));
  $('#btn-fit').onclick = () => MapView.fit();
  $('#btn-follow').onclick = e => { S.follow = !S.follow; e.currentTarget.classList.toggle('active', S.follow); };
  $$('[data-layer]').forEach(c => c.onchange = () => { S.layers[c.dataset.layer] = c.checked; MapView.dirty(); });
  $('#rng-opacity').oninput = e => { S.opacity = e.target.value / 100; MapView.dirty(); };
  $$('.panel-title.fold').forEach(t => t.onclick = () => t.parentElement.classList.toggle('folded'));
  const compactMap = window.matchMedia('(max-width: 1200px)');
  const foldMapPanels = () => $$('.layers, .legend').forEach(el => el.classList.toggle('folded', compactMap.matches));
  compactMap.addEventListener('change', foldMapPanels);
  foldMapPanels();

  P.legend = () => {
    if (!S.info) return;
    $('#legend').innerHTML = S.info.classes.map((_, k) => { const n = clsName(k + 1); return (
      `<div class="legend-item ${S.hidden.has(k + 1) ? 'off' : ''}" data-c="${k + 1}" title="${n}"><span class="sw" style="background:${S.info.palette[k + 1]}"></span>${n}</div>`); }).join('');
    $$('#legend .legend-item').forEach(el => el.onclick = () => {
      const c = +el.dataset.c; S.hidden.has(c) ? S.hidden.delete(c) : S.hidden.add(c);
      P.legend(); MapView.repaintAll();
    });
  };

  // ---------- 任务控制 ----------
  $$('#seg-kind button').forEach(b => b.onclick = () => P.setKind(b.dataset.kind));
  P.setKind = k => {
    S.kind = k;
    $$('#seg-kind button').forEach(b => b.classList.toggle('on', b.dataset.kind === k));
    if (k === 'region' && !S.rect) P.setTool('box');
    P.rectText();
    if(k==='eval')P.showTab('eval');
    if(typeof BoardPanel!=='undefined')BoardPanel.controls();
  };
  P.rectText = () => {
    const r = S.rect;
    $('#rect-row').textContent = S.kind === 'eval' ? `评测：官方 Test100 共 ${fmt.n(S.info?.test_pixels)} 像素` :
      S.kind === 'scan' ? `整景：${S.H}×${S.W} = ${fmt.n(S.H * S.W)} 像素，逐行推扫` :
      r ? `区域：行 ${r[0]}～${r[0] + r[2] - 1}，列 ${r[1]}～${r[1] + r[3] - 1}（${fmt.n(r[2] * r[3])} 像素，${fmt.f(r[2] * r[3] * S.gsd * S.gsd, 0)} m²）` :
      '区域：未框选（工具栏"框选区域"，在地图上拖动）';
    $('#btn-rect-clear').hidden = !S.rect;
  };
  P.setRect = r => { S.rect = r; P.setKind('region'); MapView.dirty(); Cube.onRect(); };
  $('#btn-rect-clear').onclick = () => {
    S.rect = null;
    if (S.kind === 'region') P.setKind('scan'); else P.rectText();
    const sc = $('#sel-cube-scope');
    if (sc.value === 'rect') { sc.value = 'scene'; sc.dispatchEvent(new Event('change')); }
    MapView.dirty();
  };
  P.start = (over = {}) => {
    if((over.kind||S.kind)==='eval')return P.metrics();
    if (S.source?.source === 'board') return BoardPanel.start(over);
    const kind = over.kind || S.kind;
    if (kind === 'region' && !(over.rect || S.rect)) return toast('先在地图上框选区域');
    send({ cmd: 'start', kind, scene: S.scene, version: over.version || S.version, rect: kind === 'region' ? (over.rect || S.rect) : null,
           pace_rows: +$('#sel-pace').value });
  };
  $('#btn-start').onclick = () => P.start();
  $('#btn-pause').onclick = () => {
    const r = S.runs[S.live]; if (!r) return;
    send({ cmd: r.s.status === 'paused' ? 'resume' : 'pause' });
  };
  $('#btn-stop').onclick = () => send({ cmd: 'stop' });
  $('#sel-scene').onchange = e => loadScene(e.target.value).catch(err=>toast(`场景加载失败：${err.message}`));
  $('#sel-version').onchange = e => { S.version = e.target.value; BoardPanel.selectionChanged(); };

  P.runState = s => {
    s = s || {}; // source switch clears the selected run
    const st = s?.status || 'idle';
    const b = $('#run-badge');
    b.className = 'badge ' + st;
    b.textContent = { idle: '空闲', running: `#${s.id} 运行中`, paused: `#${s.id} 已暂停`, done: `#${s.id} 完成`, stopped: `#${s.id} 已停止`, error: `#${s.id} 出错` }[st];
    const active = st === 'running' || st === 'paused';
    $('#btn-pause').disabled = !active; $('#btn-stop').disabled = !active;
    $('#btn-pause').textContent = st === 'paused' ? '▶ 继续' : '❚❚ 暂停';
  };
  P.clearTaskState = () => {
    for(const id of ['t-rate','t-mspx','t-elapsed','t-row','t-jpx','t-bytes','t-energy'])$('#'+id).textContent='—';
    $('#t-energy-detail').textContent='等待本场景板卡任务的能耗记录';
    $('#t-done').textContent='0';P.runState(null);
    $('#progress-bar').style.width='0%';$('#progress-txt').textContent='等待本场景任务';
    $('#board-first-result').hidden=true;
  };

  // ---------- 遥测 ----------
  P.tick = m => {
    S.telemetry = m.telemetry; S.source = m.source;
    const t=m.telemetry||{},selected=!S.viewCleared?S.runs[S.runA]?.s:null;
    const r=selected?.scene===S.scene?(m.run?.id===S.runA?m.run:selected):null;
    const key=m.source?.physical_keys?.last,notice=$('#physical-key-state');
    notice.hidden=!key;
    if(key)notice.textContent=key.state===2?(key.code===12?'正在安全停止原任务并切换场景…':'正在准备按键任务；新场景首次加载约 15～40 秒，请等待板卡结果。'):
      key.state===4?`KEY${key.key} 操作未执行，请查看日志中的原因。`:
      key.code===10?'场景已选中，等待任务；首次识别时才加载数据，原任务结果保留在历史记录。':`KEY${key.key} 操作已执行。`;
    P.sourcePill(m.source);
    $('#telem-src').textContent = t.device || '';
    $('#t-power').textContent = t.power_est_state==='valid'?fmt.f(t.power_est_w,2):t.power_est_state==='stale'?'已过期':'未获取';
    const pe=t.power_estimate;
    $('#t-power-detail').textContent=pe?(pe.temperature_valid?'板端更新 · 芯片 PS＋PL':'温度暂不可用 · 板端数据更新中'):'等待板端数据';
    $('#t-temp').textContent = t.temp_state==='valid'?fmt.f(t.temp_c, 1):t.temp_state==='stale'?'已过期':'未测';
    $('#t-temp-detail').textContent=t.temp_state==='valid'?`启动峰值 ${fmt.f(t.temp_peak_c,1)}°C · SYSMON`:'等待有效板端温度';
    const dp=t.display||{};
    if(dp.state==='synced')$('#dp-parcel-state').textContent=`DP 已同步 · 台账版本 ${dp.revision} · ${dp.parcel_id?'地块统计':'任务统计'}`;
    else if(dp.state==='error')$('#dp-parcel-state').textContent=`DP 同步未完成：${dp.error}`;
    else if(dp.state==='queued')$('#dp-parcel-state').textContent='正在等待 DP 同步确认…';
    if (r) {
      const loc = S.runs[r.id]; if (loc) Object.assign(loc.s, r);
      const cr = r.board_ms_per_px ? 1000 / r.board_ms_per_px : r.compute_rate;
      $('#t-rate').textContent = cr ? fmt.n(Math.round(cr)) : '—';
      $('#t-mspx').textContent = r.board_ms_per_px ? fmt.f(r.board_ms_per_px, 3) : cr ? fmt.f(1000 / cr, 3) : '—';
      $('#t-done').textContent = fmt.n(r.done);
      $('#t-elapsed').textContent = fmt.dur(r.elapsed);
      $('#t-row').textContent = r.kind === 'eval' ? '—' : r.row;
      const rate = r.rate;
      const energy=r.power_estimate;
      $('#t-jpx').textContent=energy?.energy_est_mj_per_px!=null?fmt.f(energy.energy_est_mj_per_px,2):'—';
      $('#t-energy').textContent=energy?.energy_est_j!=null?fmt.f(energy.energy_est_j,2):'—';
      $('#t-energy-detail').textContent=energy?
        `板端任务 #${energy.task} · ${energy.active?'累计中':'已冻结'} · ${fmt.f(energy.duration_s,2)} s；含准备和暂停，不含后续单点探查。`+
        (energy.fallback_s>0?` ${fmt.f(energy.fallback_s,1)} s 使用参考温度。`:''):
        '本任务尚无能耗记录；历史无数据不补算。';
      const nb = r.done * 4;
      $('#t-bytes').textContent = fmt.bytes(nb);
      if(r.source==='board')$('#t-elapsed').textContent=`${fmt.f(r.elapsed,2)} s`;
      $('#progress-bar').style.width = `${100 * r.done / Math.max(1, r.total)}%`;
      $('#progress-txt').textContent = `${fmt.n(r.done)} / ${fmt.n(r.total)}  (${fmt.pct(r.done / Math.max(1, r.total))})`;
      P.runState(r);
      if (r.status === 'running' && r.source !== 'board') { S.rateHist.push(Math.round(rate)); if (S.rateHist.length > 240) S.rateHist.shift(); P.spark(); }
    } else P.clearTaskState();
    P.link(m);
    P.liveMetrics(r);
    if (P.areaDirty) { P.areaDirty = false; P.area(); }
  };
  P.sourcePill = src => {
    if (!src) return;
    $('#txt-source').textContent = src.label;
    $('#dot-link').className = 'dot ' + (src.link === 'local' ? 'local' : src.link);
  };
  $('#pill-source').onclick = () => P.showTab('link');
  P.spark = () => {
    P.chart('chart-rate').setOption({
      grid: { left: 2, right: 2, top: 4, bottom: 2 }, xAxis: { type: 'category', show: false, data: S.rateHist.map((_, i) => i) },
      yAxis: { type: 'value', show: false, min: 0 }, animation: false,
      series: [{ type: 'line', data: S.rateHist, symbol: 'none', smooth: true, lineStyle: { color: '#2dd4bf', width: 1.5 },
                 areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(45,212,191,.35)' }, { offset: 1, color: 'rgba(45,212,191,0)' }]) } }],
    });
  };

  // ---------- 种植结构（按 A 运行实时统计） ----------
  P.stats = () => {
    const r = S.runs[S.runA]; const nc = S.info.classes.length;
    const cnt = new Array(nc + 1).fill(0), cs = new Array(nc + 1).fill(0);
    if (r?.loaded && !r.s.board?.error && !r.s.board?.integrity_error) for (let i = 0; i < r.pred.length; i++) {
      const c = r.pred[i]; if (c && c<=nc && (r.s.source!=='board'||r.seen?.[i])) { cnt[c]++; cs[c] += r.conf[i]; }
    }
    const total = cnt.reduce((a, b) => a + b, 0);
    return { cnt, total, meanConf: cs.map((s, c) => cnt[c] ? s / cnt[c] / 255 : null) };
  };
  P.area = () => {
    if (!S.info) return;
    const { cnt, total, meanConf } = P.stats(), g2 = S.gsd * S.gsd;
    const items = S.info.classes.map((n, k) => ({ n: clsName(k + 1), c: k + 1, px: cnt[k + 1] })).filter(x => x.px).sort((a, b) => b.px - a.px);
    $('#area-sub').textContent = total ? `${fmt.n(total)} 像素 · ${fmt.f(total * g2 / 666.67, 1)} 亩` : '—';
    const top = items.length ? items[0].px : 1;
    $('#area-list').innerHTML = items.map(x => {
      const m2 = x.px * g2, share = x.px / total;
      return `<div class="arow" title="${x.n}：${fmt.f(m2, 0)} m²（${fmt.f(m2 / 666.67, 2)} 亩）· ${fmt.n(x.px)} 像素 · 均置信 ${fmt.f(meanConf[x.c], 3)}">
        <span class="sw" style="background:${clsColor(x.c)}"></span><span class="aname">${x.n}</span>
        <span class="aval mono">${m2 >= 1e4 ? fmt.f(m2 / 1e4, 2) + ' ha' : fmt.f(m2, 0) + ' m²'}</span><span class="apct mono">${fmt.pct(share)}</span>
        <div class="abar"><i style="width:${100 * x.px / top}%;background:${clsColor(x.c)}"></i></div></div>`;
    }).join('') || '<div class="empty">开始巡检或框选识别后在这里统计</div>';
    $('#tbl-area tbody').innerHTML = items.map(x => `<tr><td><span class="sw" style="display:inline-block;vertical-align:-2px;background:${clsColor(x.c)}"></span> ${x.n}</td>
      <td class="num">${fmt.n(x.px)}</td><td class="num">${fmt.f(x.px * g2, 0)}</td><td class="num">${fmt.pct(x.px / total)}</td><td class="num">${fmt.f(meanConf[x.c], 3)}</td></tr>`).join('');
    if (P.tab === 'parcel') P.parcels();
    P.businessControls?.();
  };

  // ---------- 光标 ----------
  P.cursor = (row, col, ok) => {
    if (!ok) { $('#cursor').textContent = '行 — 列 —'; return; }
    const i = row * S.W + col, r = S.runs[S.runA];
    const p = r?.loaded ? r.pred[i] : 0;
    $('#cursor').textContent = `行 ${row} 列 ${col} · ${fmt.f(col * S.gsd, 1)} m, ${fmt.f(row * S.gsd, 1)} m` +
      (p ? ` · ${clsName(p)} ${fmt.f(r.conf[i] / 255, 2)}` : '') + (S.layers.gt && S.gt[i] ? ` · 真值 ${clsName(S.gt[i])}` : '');
  };

  // ---------- 飞行任务卡 ----------
  P.mission = () => {
    const m = S.info.mission;
    $('#mission').innerHTML = [['地点', m.site], ['天气', m.weather], ['时间', m.date, 1], ['平台', m.platform, 1], ['传感器', m.sensor, 1],
      ['航高', `${m.altitude_m} m`], ['GSD', `${m.gsd_m} m`], ['影像', `${S.H}×${S.W}×${S.info.bands}`], ['覆盖', `${fmt.f(S.H * S.W * m.gsd_m ** 2 / 1e4, 2)} ha`]]
      .map(([k, v, full]) => `<div>${k}</div><div class="${full ? 'full' : ''}" title="${v}">${v}</div>`).join('');
  };

  P.onScene = () => {
    P.clearMetrics?.();
    P.clearBusiness?.(); P.clearComparison?.();
    P.legend(); P.mission(); P.setKind(S.kind); P.area(); P.runsTable(); P.clearProbe();
    $('#tbl-patches tbody').innerHTML = ''; $('#tbl-sampling tbody').innerHTML = '';
  };

  // ---------- 单点探查 ----------
  P.clearProbe = () => { $('#probe-head').textContent = '单击地图上的像素查看模型输入与输出'; $('#probe-kv').innerHTML = ''; };
  P.probe = async (row, col) => {
    if (S.source?.source === 'board') return BoardPanel.probe(row, col);
    S.probe = { row, col }; MapView.dirty();
    if (P.tab !== 'probe') P.showTab('probe');
    const ver = S.runs[S.runA]?.s.version || S.version;      // 与地图上显示的结果同一权重
    const p = await (await fetch(`/api/probe?scene=${S.scene}&version=${ver}&r=${row}&c=${col}`)).json();
    S.probe = p;
    $('#probe-head').innerHTML = `<b style="color:${clsColor(p.label)}">■</b> ${clsName(p.label)} <span class="mono">· 置信 ${fmt.f(p.conf, 3)}</span>`;
    $('#probe-kv').innerHTML = [['位置', `行 ${row} 列 ${col}`], ['地面', `${fmt.f(col * S.gsd, 1)} m, ${fmt.f(row * S.gsd, 1)} m`],
      ['权重', ver], ['推理', `${fmt.f(p.ms, 1)} ms（PC 单像素，含传输）`],
      ['真值', p.gt ? `${clsName(p.gt)}${p.gt === p.label ? ' ✓' : ' ✗'}（仅评测）` : '无标注'],
      ['划分', p.split === 'train' ? '官方 Train100' : p.split === 'test' ? '官方 Test100' : '—']]
      .map(([k, v]) => `<div>${k}</div><div>${v}</div>`).join('');
    drawPatches(row, col, p.nbr);
    const lib = S.lib || (S.lib = await (await fetch(`/api/scene/${S.scene}/library`)).json());
    const wl = lib.wavelengths;
    const ser = [{ name: '该像素', type: 'line', data: p.spectrum.map((v, i) => [wl[i], v]), symbol: 'none', lineStyle: { width: 2, color: '#fff' } }];
    const addLib = (c, dash) => lib.library[c - 1] && ser.push({ name: `${clsName(c)}（训练样本均值）`, type: 'line', symbol: 'none',
      data: lib.library[c - 1].map((v, i) => [wl[i], v]), lineStyle: { width: 1.5, color: clsColor(c), type: dash } });
    addLib(p.label, 'solid');
    if (p.gt && p.gt !== p.label) addLib(p.gt, 'dashed');
    P.chart('chart-spectrum').setOption({
      title: { text: '光谱（预处理后，400–1000 nm）', textStyle: { color: '#7b8ea3', fontSize: 11, fontWeight: 'normal' }, left: 0, top: 0 },
      grid: { left: 40, right: 10, top: 26, bottom: 40 }, tooltip: { ...TT, trigger: 'axis' }, animation: false,
      legend: { bottom: 0, textStyle: { color: '#b8c7d6', fontSize: 10 }, itemHeight: 6 },
      xAxis: { type: 'value', min: 400, max: 1000, name: 'nm', nameTextStyle: { color: '#7b8ea3' }, ...AX },
      yAxis: { type: 'value', scale: true, ...AX }, series: ser,
    }, true);
    const probs = p.prob.map((v, k) => ({ v, c: k + 1 }));
    P.chart('chart-prob').setOption({
      title: { text: 'softmax 概率', textStyle: { color: '#7b8ea3', fontSize: 11, fontWeight: 'normal' }, left: 0, top: 0 },
      grid: { left: 110, right: 40, top: 24, bottom: 6 }, animation: false,
      tooltip: { ...TT, formatter: q => `${q.name}<br>p ${q.value.toFixed(4)}<br>logit ${p.logits[q.dataIndex].toFixed(3)}` },
      xAxis: { type: 'value', max: 1, show: false }, yAxis: { type: 'category', inverse: true, data: classNames(), ...AX, axisLabel: { color: '#b8c7d6', fontSize: 10, width: 100, overflow: 'truncate' } },
      series: [{ type: 'bar', data: probs.map(x => ({ value: x.v, itemStyle: { color: clsColor(x.c), opacity: x.c === p.label ? 1 : 0.55 } })),
                 label: { show: true, position: 'right', color: '#d6e2ee', fontSize: 10, formatter: q => q.value >= 0.001 ? q.value.toFixed(3) : '' } }],
    }, true);
    P.attn();
  };
  function drawPatches(row, col, nbr) {
    for (const [id, fn] of [['patch-rgb', (x) => x.drawImage(S.base, col - 3, row - 3, 7, 7, 0, 0, 140, 140)], ['patch-pred', x => {
      for (let k = 0; k < 49; k++) {
        const c = nbr[k];
        x.fillStyle = c ? clsColor(c) : '#0a1017'; x.fillRect(k % 7 * 20, Math.floor(k / 7) * 20, 20, 20);
      }
    }]]) {
      const x = $('#' + id).getContext('2d'); x.imageSmoothingEnabled = false; x.fillStyle = '#000'; x.fillRect(0, 0, 140, 140); fn(x);
      x.strokeStyle = '#fff'; x.lineWidth = 2; x.strokeRect(60, 60, 20, 20);
    }
  }
  P.attn = () => {
    const p = S.probe; if (!p?.attn) return;
    const l = +$('#rng-layer').value - 1; $('#txt-layer').textContent = l + 1;
    const a = p.attn[l], tok = ['cls', '子张量1', '子张量2', '子张量3', '子张量4', '子张量5'], data = [];
    a.forEach((row, i) => row.forEach((v, j) => data.push([j, i, v])));
    P.chart('chart-attn').setOption({
      title: { text: `注意力 第 ${l + 1} 层（查询 → 键）`, textStyle: { color: '#7b8ea3', fontSize: 11, fontWeight: 'normal' }, left: 0, top: 0 },
      grid: { left: 56, right: 6, top: 24, bottom: 42 }, animation: false, tooltip: { ...TT, formatter: q => `${tok[q.value[1]]} → ${tok[q.value[0]]}：${q.value[2].toFixed(3)}` },
      xAxis: { type: 'category', data: tok, ...AX, axisLabel: { color: '#7b8ea3', fontSize: 9, rotate: 40 } },
      yAxis: { type: 'category', data: tok, inverse: true, ...AX, axisLabel: { color: '#7b8ea3', fontSize: 9 } },
      visualMap: { show: false, min: 0, max: 1, inRange: { color: ['#0b1016', '#0e4f5c', '#2dd4bf', '#fef08a'] } },
      series: [{ type: 'heatmap', data, label: { show: true, color: '#fff', fontSize: 9, formatter: q => q.value[2] >= 0.1 ? q.value[2].toFixed(2) : '' } }],
    }, true);
  };
  $('#rng-layer').oninput = P.attn;

  return P;
})();
