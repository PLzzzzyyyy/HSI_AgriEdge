'use strict';
// 入口：WebSocket 事件分发、时钟、启动
(() => {
  let reconnecting=false;
  let keyUi=Promise.resolve();
  async function showKeyAction(m,{replay=false}={}) {
    if(m.state==='error'){toast(`按键操作失败：${m.error}`,5000);return;}
    if(m.state==='preparing'){
      $('#physical-key-state').hidden=false;
      $('#physical-key-state').textContent='正在安全停止原任务并切换场景，请稍候…';return;
    }
    if(m.run && ((replay&&!['running','paused'].includes(m.run.status)) || (S.viewCleared&&m.run.id<=S.hiddenThrough)))return;
    if(S.ledger?.dirty || S.ledger?.saving){
      toast('板卡按键已执行；当前有未保存地块，保留编辑内容，请保存后查看新任务。',6000);return;
    }
    if(m.scene!==S.scene)await loadScene(m.scene);
    S.version=m.version;$('#sel-version').value=m.version;
    if(m.action==='scene'){
      S.keyScenePreview=true;S.runA=S.runB=null;S.rect=null;S.probe=null;S.viewCleared=false;
      Panels.setKind('scan');Panels.areaDirty=true;
      Panels.runState(null);$('#progress-bar').style.width='0%';$('#progress-txt').textContent='等待新场景任务';
      BoardPanel.selectionChanged();
    }
    if(m.run){
      S.keyScenePreview=false;
      const id=m.run.id;
      S.viewCleared=false;
      S.runs[id] ||= {s:m.run,pred:null,conf:null,loaded:false};
      S.runs[id].s=m.run;S.live=id;S.runA=id;S.runB=null;
      S.rect=taskSelectionRect(m.run);Panels.setKind(S.rect?'region':'scan');
      await loadRun(id);
      const response=await fetch(`/api/run/${id}/board`);
      if(response.ok)BoardPanel.apply(id,await response.json());
      Panels.runState(m.run);Panels.runsTable();
    }
    if(m.action==='point')BoardPanel.probe(m.row,m.col,{auto:!replay});
    if(m.action==='parcel'){
      $('#rng-conf').value=Math.round(m.threshold*100);$('#txt-conf').textContent=m.threshold.toFixed(2);
      await Panels.loadParcels(m.scene);Panels.showTab('parcel');
    }
    MapView.repaintAll();
    toast(m.action==='scene'?`已选中 ${m.scene}；首次识别时加载数据`:`KEY${m.event.key} 已启动${m.action==='point'?'单点探查':m.action==='scan'?'整景巡检':m.action==='parcel'?'随机地块识别':'随机区域识别'}`);
  }
  async function restoreAfterDisconnect() {
    const st=await(await fetch('/api/state')).json();
    const previousA=S.runA,wasCleared=S.viewCleared;
    for(const id of Object.keys(S.runs))delete S.runs[id];
    for(const summary of st.runs)S.runs[summary.id]={s:summary,pred:null,conf:null,loaded:false};
    S.live=st.run?.id || null;
    S.runA=!wasCleared&&S.runs[previousA]?.s.scene===S.scene?previousA:null;
    if(!S.runA&&st.run?.scene===S.scene&&st.run.id>S.hiddenThrough&&['running','paused'].includes(st.run.status)){
      S.viewCleared=false;S.runA=st.run.id;
    }
    S.runB=null;$('#swipe').hidden=true;Panels.clearMetrics();Panels.clearBusiness();Panels.clearComparison();
    await BoardPanel.source(st.source);BoardPanel.gate(st.board_gate);ConnectionPanel.apply(st);
    for(const item of st.history_errors || [])logLine(`历史记录读取失败：${item.error}`,'error');
    if(S.runA)await loadRun(S.runA);
    if(st.key_context)await showKeyAction(st.key_context,{replay:true});
    MapView.repaintAll();Panels.runsTable();
    logLine('已只读恢复服务历史；板卡连接不会自动接管。');
  }
  function connect() {
    const ws = new WebSocket(`ws://${location.host}/ws`);
    ws.binaryType = 'arraybuffer';
    S.ws = ws;
    ws.onopen = () => {
      logLine('已连接地面站服务');
      if(reconnecting)restoreAfterDisconnect().catch(e=>logLine(`历史恢复失败：${e.message}`,'error'));
      reconnecting=false;
    };
    ws.onclose = () => {
      reconnecting=true;
      ConnectionPanel.offline();
      Panels.sourcePill({ label: '服务断开，重连中…', link: 'down' });
      setTimeout(connect, 1500);
    };
    ws.onmessage = e => {
      if (typeof e.data !== 'string') return applyChunk(e.data);
      const m = JSON.parse(e.data);
      switch (m.type) {
        case 'key_action':
          keyUi=keyUi.then(()=>showKeyAction(m)).catch(err=>toast(`按键页面同步失败：${err.message}`,5000));break;
        case 'hello':
          Panels.sourcePill(m.source); BoardPanel.source(m.source); break;
        case 'tick': SpeedPanel.update(m.speed_compare); Panels.tick(m); BoardPanel.tick(m); ConnectionPanel.apply(m); break;
        case 'board_gate': BoardPanel.gate(m.source); break;
        case 'board_update': BoardPanel.apply(m.id, m.board); break;
        case 'command_error': BoardPanel.rejected(m.command); Loop.onCommandError(m.command); break;
        case 'run_start': {
          Loop.onRunStart(m.run);
          const s = m.run;
          // 服务端只保留最近若干次运行，已被清掉的从历史表里去掉
          if (m.alive) for (const id of Object.keys(S.runs)) if (!m.alive.includes(+id)) delete S.runs[id];
          if (s.scene !== S.scene) break;
          S.runs[s.id] = newRun(s); S.live = s.id;
          if(BoardPanel.allowRunDisplay?.()===false||!SpeedPanel.allowRun(s)){rememberClear();break;}
          if(s.id<=S.hiddenThrough&&S.viewCleared)break;
          S.viewCleared=false;S.keyScenePreview=false;S.rateHist = [];
          S.runA = s.id; S.runB = null; $('#swipe').hidden = true; S.patches = []; S.sampling = [];
          S.rect=taskSelectionRect(s);Panels.rectText();
          if(s.origin?.startsWith('speed:')){S.version=s.version;$('#sel-version').value=s.version;Panels.setKind('region');Panels.showTab('speed');}
          Panels.clearMetrics();
          Panels.clearBusiness();Panels.clearComparison();
          MapView.repaintAll(); Panels.runState(s); Panels.areaDirty = true;
          if (s.kind === 'scan') S.follow && MapView.fit();
          if (s.kind === 'eval'||s.origin==='evaluation') Panels.showTab('eval');
          break;
        }
        case 'run_state': case 'run_end': {
          const r = S.runs[m.run.id];
          if (r) Object.assign(r.s, m.run);
          if(!S.viewCleared && m.run.id===S.runA && !S.keyScenePreview && m.run.scene===S.scene)Panels.runState(m.run);
          Panels.areaDirty = true;
          if (m.type === 'run_end') {
            MapView.dirty(); Panels.runsTable(); Loop.onRunEnd(m.run);
            if (m.run.id===S.runA&&!S.viewCleared&&(m.run.kind==='eval'||m.run.origin==='evaluation')) { Panels.showTab('eval'); Panels.metrics(m.run.id); }
            else if (m.run.status === 'done' && m.run.kind !== 'eval' && m.run.source !== 'board') Panels.analyze();
          }
          break;
        }
        case 'source': Panels.sourcePill(m.source); BoardPanel.source(m.source, true); ConnectionPanel.source(m.source); toast(m.source.label); break;
        case 'upload': case 'upload_end': Panels.upload(m); break;
        case 'finetune': Loop.onFinetune(m); break;
        case 'log': logLine(m.msg, m.level, m.t); if (m.level === 'error') toast(m.msg, 4000); break;
      }
    };
  }

  setInterval(() => $('#pill-clock').textContent = new Date().toLocaleTimeString('zh-CN', { hour12: false }), 1000);

  (async () => {
    const st = await (await fetch('/api/state')).json();
    S.source = st.source;
    ConnectionPanel.apply(st);
    for(const item of st.history_errors || [])logLine(`历史记录读取失败：${item.error}`,'error');
    $('#sel-scene').innerHTML = st.scenes.map(s => `<option value="${s}">${s}</option>`).join('');
    // 页面刷新后恢复服务端已有的运行（结果按需拉取）
    for (const s of st.runs) S.runs[s.id] = { s, pred: null, conf: null, loaded: false };
    if (st.run) S.live = st.run.id;
    // Opening/reloading a page does not select completed history or replay a
    // physical point command. Only an active new task is restored automatically.
    S.viewCleared=!(st.run&&st.run.id>S.hiddenThrough&&['running','paused'].includes(st.run.status));
    await loadScene(st.run ? st.run.scene : st.scenes[0]);
    $('#sel-scene').value = S.scene;
    BoardPanel.source(st.source);
    BoardPanel.gate(st.board_gate);
    if(st.key_context)await showKeyAction(st.key_context,{replay:true});
    SpeedPanel.update(st.speed_compare);
    connect();
  })();
})();
