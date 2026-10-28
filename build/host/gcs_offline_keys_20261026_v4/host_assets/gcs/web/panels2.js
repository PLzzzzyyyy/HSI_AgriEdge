'use strict';
// 抽屉面板（二）：农情分析、地块台账、评测、链路与下发、历史对比
Object.assign(Panels, (() => {
  const P = Panels, { AX, TT } = Panels;
  const X = {};

  // 农情分析与持久台账由 agri.js 接入，原布局不变。

  // 评测由 evaluation.js 接入。

  // ---------- 链路与下发 ----------
  $('#btn-upload').onclick = () => {
    const vid = $('#sel-upload').value; if (!vid) return;
    $('#upload-bar').style.width = '0%'; $('#upload-txt').textContent = '下发中…';
    send({ cmd: 'upload', scene: S.scene, version: vid,activate:true });
  };
  $('#btn-model-query').onclick=()=>modelCommand('query',{confirmed:true});
  $('#btn-model-activate').onclick=()=>modelCommand('activate',{confirmed:true,scene:S.scene,version:$('#sel-upload').value});
  $('#btn-model-recover').onclick=()=>modelCommand('recover',{confirmed:true,channel:$('#sel-model-channel').value});
  $('#sel-model-channel').onchange=()=>BoardPanel.controls();
  $('#btn-model-channels').onclick=async()=>{
    try{const response=await fetch('/api/board/models'),data=await response.json();if(!response.ok)throw Error(data.detail||response.statusText);
      const select=$('#sel-model-channel');select.replaceChildren();
      for(const item of data.channels || []){const option=document.createElement('option');option.value=item.channel;option.disabled=!item.recoverable;
        option.textContent=`${item.channel} ${item.recoverable?item.boot_id:item.error}`;select.append(option);}
      $('#btn-model-recover').disabled=!select.value || S.source?.active || !!select.selectedOptions[0]?.disabled;
    }catch(e){$('#model-state').textContent=`本地模型记录不可用：${e.message}`;}
  };
  async function modelCommand(action,body){
    try{const response=await fetch(`/api/board/models/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const data=await response.json();if(!response.ok)throw Error(data.detail||response.statusText);$('#model-state').textContent='已提交，等待真实板卡回执';
    }catch(e){$('#model-state').textContent=`模型操作未确认：${e.message}`;}
  }
  X.upload = m => {
    if(m.scene && m.scene!==S.scene)return;
    if (m.type === 'upload') { $('#upload-bar').style.width = `${100 * m.done / Math.max(1, m.total)}%`; $('#upload-txt').textContent = `${fmt.bytes(m.done)} / ${fmt.bytes(m.total)}`; }
    else {
      $('#upload-txt').textContent = m.ok ? `${m.action==='query'?'目录已查询':m.activated===true?'已激活':m.persisted===true?'已持久化，未激活':'操作已确认'} · ${fmt.bytes(m.bytes)} · ${m.note || ''}` : `失败或未确认：${m.note || m.error}`;
      if (m.ok && m.activated===true && m.version) { S.version = m.version; $('#sel-version').value = m.version; toast(`权重 ${m.version} 已收到激活回执；仍需真实任务复测`); }
      Loop.onUpload(m);
    }
  };
  let lastLink = 0;
  X.link = m => {
    if (P.tab !== 'link' || Date.now() - lastLink < 700) return;
    lastLink = Date.now();
    const t = m.telemetry || {}, src = m.source || {}, r = m.run;
    const kv = [['数据源', src.label], ['链路', src.link === 'local' ? '本机' : src.link === 'up' ? '在线' : src.link === 'unknown' ? 'PHY未测；不据此判断线' : '断开'], ['板卡地址', src.board_ip || '—']];
    if (src.source === 'board') kv.push(['收', `${fmt.n(t.rx_pkts)} 包 / ${fmt.bytes(t.rx_bytes)}`], ['发', `${fmt.n(t.tx_pkts)} 包 / ${fmt.bytes(t.tx_bytes)}`], ['丢包（序号缺口）', fmt.n(t.lost)]);
    else kv.push(['GPU 利用率', t.util == null ? '—' : `${t.util}%`]);
    $('#link-kv').innerHTML = kv.map(([k, v]) => `<div>${k}</div><div>${v}</div>`).join('');
    const done = r?.done || 0, pkg = S.info?.versions.find(v => v.id === S.version)?.pkg_bytes || 0;
    const bars = [['原始立方体 int16（270 波段）', done * 270 * 2, '#64748b'], ['分类结果（4 B/像素）', done * 4, '#2dd4bf'], ['权重包（一次）', pkg, '#38bdf8']];
    if (src.source === 'board') bars.push(['实收 UDP 字节', t.rx_bytes || 0, '#f59e0b']);
    P.chart('chart-bytes').setOption({
      title: { text: `链路字节对比 · 已处理 ${fmt.n(done)} 像素（压缩比 ${done ? '270×2 : 4 = 135 : 1' : '—'}）`, textStyle: { color: '#7b8ea3', fontSize: 11, fontWeight: 'normal' } },
      grid: { left: 170, right: 80, top: 30, bottom: 10 }, animation: false,
      xAxis: { type: 'log', show: false, min: 1 }, yAxis: { type: 'category', inverse: true, data: bars.map(b => b[0]), ...AX, axisLabel: { color: '#b8c7d6', fontSize: 11 } },
      series: [{ type: 'bar', data: bars.map(b => ({ value: Math.max(1, b[1]), itemStyle: { color: b[2], borderRadius: [0, 3, 3, 0] } })),
                 label: { show: true, position: 'right', color: '#d6e2ee', formatter: q => fmt.bytes(bars[q.dataIndex][1]) } }],
    }, true);
  };

  // ---------- 历史对比 ----------
  let compareGeneration=0;
  X.clearComparison=()=>{compareGeneration++;S.comparison=null;$('#cmp-txt').textContent='';};
  X.runsTable = () => {
    P.evalTasks?.();
    const rows = Object.values(S.runs).filter(r => r.s.scene === S.scene).reverse();
    const kinds = { scan: '整景', region: '区域', eval: '评测' };
    $('#tbl-runs tbody').innerHTML = rows.map(r => { const s = r.s; return `<tr><td>${s.id}</td><td>${kinds[s.kind]}</td><td>${s.scene}</td><td>${s.version}</td><td>${s.source}</td>
      <td class="num">${fmt.n(s.done)}</td><td>${s.status}</td><td class="num">${fmt.f(s.elapsed, 1)}</td><td class="num">${s.source==='board' ? fmt.f(s.board?.performance?.pixels_per_second,1) : s.compute_s ? fmt.n(Math.round(s.done / s.compute_s)) : '—'}</td>
      <td><input type="radio" name="runA" value="${s.id}" ${S.runA === s.id ? 'checked' : ''}></td>
      <td><input type="radio" name="runB" value="${s.id}" ${S.runB === s.id ? 'checked' : ''}></td></tr>`; }).join('') +
      `<tr><td colspan="10" class="note">B = 无</td><td><input type="radio" name="runB" value="" ${S.runB ? '' : 'checked'}></td></tr>`;
    $$('#tbl-runs input[name=runA]').forEach(i => i.onchange = () => X.setAB(+i.value, S.runB));
    $$('#tbl-runs input[name=runB]').forEach(i => i.onchange = () => X.setAB(S.runA, i.value ? +i.value : null));
  };
  X.setAB = async (a, b) => {
    if([a,b].some(id=>id && (S.runs[id]?.s.source!=='board'||S.runs[id]?.s.scene!==S.scene)))return toast('请选择同一场景的板卡任务');
    if(!a)b=null; if(a===b)b=null;
    const changed=a!==S.runA,scene=S.scene;
    X.clearComparison();const generation=compareGeneration,current=()=>generation===compareGeneration && scene===S.scene && a===S.runA;
    S.runA=a;S.runB=null;$('#swipe').hidden=true;
    if(a){S.viewCleared=false;S.rect=taskSelectionRect(S.runs[a].s);if(S.kind!=='eval')P.setKind(S.rect?'region':'scan');}
    if(changed){P.clearMetrics();P.clearBusiness?.();}
    MapView.repaintAll();P.area();X.runsTable();
    try {
      if(a)await loadRun(a);if(b)await loadRun(b);
      if(!current())return;
      if(a&&!S.runs[a]?.loaded||b&&!S.runs[b]?.loaded)throw Error('原始结果尚未完整加载');
      S.runB=b;$('#swipe').hidden=!b;
      if(a && S.runs[a]?.s.board)BoardPanel.apply(a,S.runs[a].s.board);
      MapView.repaintAll();P.areaDirty=true;P.area();X.runsTable();
      if(!b)return;
      $('#swipe-a').textContent=`A #${a} ${S.runs[a].s.version}`;$('#swipe-b').textContent=`B #${b} ${S.runs[b].s.version}`;
      $('#cmp-txt').textContent='正在核对两次板任务的共同已接收像素…';
      const response=await fetch(`/api/compare?a=${a}&b=${b}`),c=await response.json();
      if(!current())return;
      if(!response.ok)throw Error(c.detail||response.statusText);
      S.comparison=c;
      $('#cmp-txt').textContent=c.common ? `对比快照 · 公共像素 ${fmt.n(c.common)} · 变化 ${fmt.n(c.changed)}（${fmt.pct(1-c.agree,2)}） · ${c.complete_task_coverage?'两任务完整覆盖':'部分覆盖'}${c.same_roi?'':' · 不同ROI，仅统计交集'} · 固定Test100公共像素 ${fmt.n(c.labeled)} · A OA ${fmt.pct(c.acc_a,2)} / B OA ${fmt.pct(c.acc_b,2)}` : '两任务没有共同已接收像素，不能生成对比成绩';
      if(!c.evaluation?.available)$('#cmp-txt').textContent+=` · 评测不可用：${c.evaluation?.error||'无固定标签'}`;
    } catch(e) {
      if(current()){$('#cmp-txt').textContent=`对比不可用：${e.message}；不显示旧成绩`;S.comparison=null;MapView.repaintAll();P.area();}
    }
  };
  $('#btn-compare-refresh').onclick=()=>X.setAB(S.runA,S.runB);
  $('#chk-diff').onchange = e => { S.diffOnly = e.target.checked; MapView.dirty(); };
  X.clearView = () => {
    rememberClear();
    S.runA=S.runB=null;S.rect=S.drag=S.poly=S.probe=S.hilite=null;
    S.patches=[];S.sampling=[];S.annotations=[];S.rateHist=[];
    S.loop={};S.lib=null;S.loopOld=S.loopNew=S.loopWait=S.loopVersion=null;
    for(const name of ['conf','gt','err','parcels']){
      S.layers[name]=false;const checkbox=$(`[data-layer="${name}"]`);if(checkbox)checkbox.checked=false;
    }
    P.clearBusiness?.();P.clearMetrics();X.clearComparison();
    P.clearTaskState();P.charts['chart-rate']?.clear();
    $('#swipe').hidden=true;$('#swipe-a').textContent='A';$('#swipe-b').textContent='B';
    $('#cursor').textContent='行 — 列 —';$('#board-acceptance-state').textContent='';
    // Keep the current task mode, drawer and tool. Clear every offscreen
    // overlay as well as the selection; a redraw alone retains old pixels.
    MapView.repaintAll();MapView.flush();MapView.dirty();
    P.rectText();BoardPanel.clearView();
    if(typeof SpeedPanel!=='undefined')SpeedPanel.clear();
    P.areaDirty=true;P.area();X.runsTable();Cube.onRect();
    toast(['running','paused'].includes(S.runs[S.live]?.s.status)?'当前显示已清空；任务仍在后台，历史记录保留':'当前显示已清空；历史记录和已保存地块保留');
  };
  $('#btn-clear-map').onclick=X.clearView;

  return X;
})());
