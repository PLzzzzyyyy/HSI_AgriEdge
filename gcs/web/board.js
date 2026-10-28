'use strict';
// Exact Q0.16 results are JSON; the legacy binary PC stream is never used here.
const BoardPanel = (() => {
  let gate = null, pending = false, shown = null, shownId = null;
  let inputGeneration=0,inputAbort=null;
  let probeRequest=null,recoveryPending=false;
  let startGeneration=0;
  const mappingReady=fetch('/web/longkou_v2_classes.json').then(r=>r.json()).then(m=>{
    if(m.scene==='longkou' && m.model==='v2' && m.wcrc==='27231983')S.boardClasses=m.classes;
  });
  const active = () => S.source?.source === 'board';
  function render(b = null, id = S.runA || liveInSelection()?.id || null) {
    shownId=id;
    shown = b;
    TimingPanel.select(id,b);
    const full=b?.task_lifecycle || b?.full_scene || (!b && gate?.task_lifecycle) || (!b && S.kind==='scan'),total=b?.total || (S.kind==='region'&&S.rect?S.rect[2]*S.rect[3]:(S.H*S.W || 220000));
    const name=b?.scene || S.scene || 'longkou',model=b?.model || S.version || '待选择';
    $('#board-shape').textContent=b?.task_lifecycle?`${name} / ${model} · (${b.roi.x},${b.roi.y}) · ${b.roi.width} × ${b.roi.height}`:`${name} / ${model} · ${full?`整景 ${S.W || 400} × ${S.H || 550}`:'原点 (0,0) · 宽5 × 高3'}`;
    $('#board-status').dataset.state = b?.status || 'idle';
    $('#board-status').textContent = b ? ({ running:'运行中', paused:'已暂停', stopped:'已停止', done:`完成（${total}/${total}）`, error:'任务失败' }[b.status] || b.status) : gate?.authorized ? '已就绪，待开始' : gate?.used ? '本次连接任务已结束' : '等待连接板卡';
    $('#board-identity').textContent = b ? `任务 #${b.task}` : '尚无任务';
    $('#board-progress').textContent = `已接收 ${b?.received_pixels || 0} / ${total}`;
    if(b?.command)$('#board-status').textContent+=' · 等待指令确认';
    const waitingFirst=!!((b?.task_lifecycle || b?.full_scene) && b.status==='running' && (b.ack || b.accepted_via_info) && !b.command && !b.received_pixels);
    if(id===S.live)$('#board-first-result').hidden=!waitingFirst;
    if(waitingFirst){
      $('#board-status').textContent+=' · 等待首批结果';
      $('#board-progress').textContent+=' · 新场景首次加载约15～40秒，实际时间以板卡回传为准';
    }
    $('#board-progress-bar').max=total;
    $('#board-progress-bar').value = b?.received_pixels || 0;
    $('#board-error').textContent = b?.error || '';
    $('#task-error').textContent=liveInSelection()?.board?.error || '';
    $('#task-error').hidden=!$('#task-error').textContent;
    const interaction=b?.interaction;
    $('#board-session').textContent=interaction ? (interaction.state==='open' ? '可选点探查（完成后5分钟内）。' : `探查连接已关闭：${interaction.reason}；结果仍可查看和导出。`) : '完成后5分钟内可选点探查。';
    $('#board-session-close').disabled=interaction?.state!=='open';
    $('#board-acceptance').disabled=!((b?.task_lifecycle || b?.full_scene) && ['done','stopped'].includes(b.status) && !b.error && !b.recovering);
    $('#board-recover').disabled=!(b?.task_lifecycle && b.start_seq!=null && interaction?.state==='closed' && !b.integrity_error && !gate?.active);
    if(b?.recovering)$('#board-status').textContent+=' · 正在核对恢复身份';
    const visible=full?sampleCells():b?.cells||[];
    const cells = new Map(visible.map(c => [`${c.x},${c.y}`, c]));
    const grid = $('#board-grid'); grid.replaceChildren();
    for (let y=0;y<3;y++) for (let x=0;x<5;x++) {
      const c = cells.get(`${x},${y}`), el = document.createElement('div');
      el.className = `board-cell${c ? '' : ' missing'}`;
      el.dataset.x=x; el.dataset.y=y;
      el.append(document.createTextNode(`(${x},${y})`));
      const label = document.createElement('strong'); label.textContent = c ? `${clsName(c.class_id+1)}（类别 ${c.class_id}）` : '未收到'; el.append(label);
      if (c) {
        el.dataset.word=c.class_word; el.dataset.classId=c.class_id; el.dataset.q16=c.confidence_q16; el.dataset.confidence=c.confidence;
        el.style.borderTopColor = clsColor(c.class_id+1);
        const word=document.createElement('span'); word.className='word'; word.textContent=c.class_word; el.append(word);
        const conf=document.createElement('span'); conf.className='confidence'; conf.textContent=String(c.confidence); el.append(conf);
        el.title=`CLASS ${c.class_word}; Q0.16=${c.confidence_q16}/65536; confidence=${c.confidence}`;
        el.tabIndex=0; el.setAttribute('role','button');
        el.setAttribute('aria-label',`查看像素 ${x},${y} 的本次板端结果`);
        el.onclick=()=>probe(y,x); el.onkeydown=e=>{if(e.key==='Enter')probe(y,x);};
      }
      grid.append(el);
    }
    $('#board-export-json').disabled = !b;
    $('#board-export-csv').disabled = !b;
    probeState();
  }
  function controls() {
    if (!active()) return;
    const speedBusy=['queued','running'].includes(S.speedComparison?.state);
    const status=S.runs[S.live]?.s.status,taskBusy=['running','paused'].includes(status),busy=taskBusy||!!probeRequest||speedBusy,command=S.runs[S.live]?.s.board?.command;
    const modelBusy=gate?.model_operation && !['done','error'].includes(gate.model_operation.state);
    const current=S.runs[S.live]?.s,b=current?.board;
    const reason=speedBusy?'速度对比正在运行，请在速度对比页停止':recoveryPending||b?.recovering?'正在核对原任务连接，请等待':pending?'正在提交任务，请等待确认':
      probeRequest?'单点探查尚未结束，请等待':taskBusy?'当前任务尚未结束，请先停止或等待完成':
      modelBusy?'模型操作尚未完成，请等待':!gate?.authorized?'板卡会话未连接，请恢复原任务连接或连接新启动':
      S.kind==='region'&&!S.rect?'请先在地图上框选矩形区域':'';
    const evaluation=S.kind==='eval',canEvaluate=!!S.runA&&S.runs[S.runA]?.s.done>0;
    $('#btn-start').disabled=evaluation?!canEvaluate:!!reason;
    $('#btn-start').textContent=evaluation?'计算评测':'▶ 开始';
    $('#btn-start').title=evaluation?'读取已收到的板卡分类结果计算指标':reason||'开始识别当前选定范围';
    $('#btn-eval-scan').disabled=!!reason&&!(S.kind==='region'&&!S.rect&&gate?.authorized&&!busy&&!pending&&!modelBusy);
    const canRecover=!!b?.task_lifecycle&&b.start_seq!=null&&b.interaction?.state==='closed'&&!b.integrity_error&&!gate?.active&&!recoveryPending;
    $('#task-recover').hidden=!!gate?.authorized||!b;
    $('#task-recover').disabled=!canRecover;
    $('#task-connection-state').textContent=evaluation?(canEvaluate?'评测只读取现有分类结果，不下发推理任务':'请选择已识别的历史任务，或开始整景巡检'):reason||'板卡已就绪，可以开始；原连接仍在，无需恢复';
    $('#task-recover').title=canRecover?'只恢复原会话，保留结果，不自动开始推理':recoveryPending?'正在恢复连接':b?.integrity_error?'数据核验失败，不能恢复此任务':'当前连接正常或尚无可恢复任务';
    for(const id of ['btn-pause','btn-stop'])$('#'+id).disabled=!gate?.task_lifecycle || !taskBusy || !!command;
    if(speedBusy)$('#btn-pause').disabled=true;
    $('#btn-pause').textContent=status==='paused'?'▶ 继续':'❚❚ 暂停';
    for(const id of ['sel-scene','sel-version'])$('#'+id).disabled=!gate?.capabilities?.models || pending || busy || !!modelBusy;
    $('#sel-pace').disabled=true;
    for(const id of ['btn-upload','btn-model-activate'])$('#'+id).disabled=!gate?.capabilities?.models || !gate?.authorized || pending || !!modelBusy || !$('#sel-upload').value;
    $('#btn-model-query').disabled=!gate?.capabilities?.models || !gate?.authorized || pending || !!modelBusy;
    const channel=$('#sel-model-channel');$('#btn-model-recover').disabled=!!gate?.active || !channel.value || !!channel.selectedOptions[0]?.disabled;
    $('#model-state').textContent=modelBusy?`模型事务：${gate.model_operation.state==='waiting_task_end'?'等待任务结束，不在行中切换':gate.model_operation.phase}`:
      gate?.model_operation?.error?`模型操作失败：${gate.model_operation.error}`:`板端登记 ${gate?.registry?.length ?? 0} 个包；登记、持久化、激活和任务验收分别核对。`;
    $('#btn-rect-clear').disabled=!gate?.task_lifecycle || busy;
    $$('#seg-kind button').forEach(b=>b.disabled=b.dataset.kind==='eval'?false:pending||busy);
    // Live telemetry is owned by Panels.tick. Button refresh must not replace
    // a valid temperature or show the previous scene's inference performance.
    if(typeof Loop!=='undefined')Loop.gate();
  }
  async function source(src, reset=false) {
    if(reset||S.source?.source!==src.source)Panels.clearMetrics?.();
    inputGeneration++;inputAbort?.abort();
    S.source=src;
    const isBoard=active(); $('#board-roi').hidden=!isBoard;
    if(!isBoard)$('#board-first-result').hidden=true;
    $('#board-probe-run').hidden=true;$('#board-probe-state').hidden=!isBoard;
    $('#rng-layer').disabled=isBoard;
    $('#chart-attn').dataset.empty='12层注意力暂不可用';
    $('#chart-spectrum').dataset.empty='选择位置查看输入光谱';
    $('#patch-rgb').nextElementSibling.textContent=isBoard?'7×7 本地输入（假彩色）':'7×7 输入窗（假彩色）';
    if (reset) {
      S.live=null; S.runA=null; S.runB=null; pending=false; render();
      S.patches=[]; S.sampling=[]; S.probe=null;
      $('#swipe').hidden=true; MapView.repaintAll(); Panels.runState(null);
      $('#progress-bar').style.width='0%'; $('#progress-txt').textContent=`0 / ${fmt.n(S.H*S.W)}`;
      for(const id of ['t-done','t-elapsed','t-row','t-bytes'])$('#'+id).textContent='—';
    }
    if (isBoard) {
      gate=src;
      await mappingReady;
      if(!S.scene)await loadScene('longkou');
      if(!src.task_lifecycle)S.rect=[0,0,3,5]; Panels.setKind(S.runs[S.runA]?.s.kind || 'scan');
      $('#txt-board-ip').value='192.168.1.10'; $('#txt-board-ip').readOnly=true;
      render(liveInSelection()?.board || null); controls();
      clearUnavailable();
    } else {
      for (const id of ['btn-start','btn-upload','sel-scene','sel-version','sel-pace','btn-rect-clear']) $('#'+id).disabled=false;
      $$('#seg-kind button').forEach(b => b.disabled=false);
      $('#txt-board-ip').readOnly=false;
    }
    Panels.legend(); Panels.area(); MapView.resize(); MapView.fit();
  }
  function apply(id, b) {
    const r=S.runs[id];
    if (!r || r.s.source !== 'board' || r.s.scene !== S.scene) return;
    const speedObserved=S.speedComparison?.scene===S.scene&&S.speedComparison.items?.some(item=>item.run_id===id);
    if(r.s.version!==S.version && id!==S.runA&&!speedObserved)return;
    const old=r.s.board;
    if(b.model_lifecycle && (b.scene!==r.s.scene || b.shape?.[0]!==S.H || b.shape?.[1]!==S.W || b.classes!==S.info.classes.length ||
      old?.model_lifecycle && ['boot_id','session','task','scene','model','wcrc'].some(k=>old[k]!==b[k]))) {
      r.integrityError='页面任务模型身份冲突；不覆盖旧结果';
      r.s.board={...(old || b),error:r.integrityError,integrity_error:true,status:'error'};r.s.status='error';if(!S.viewCleared&&id===S.runA)render(r.s.board,id);return;
    }
    r.s.board={...b};delete r.s.board.chunk;
    // Streaming into a history entry must not mark its HTTP hydration complete.
    r.pred ||= new Uint8Array(S.H*S.W); r.conf ||= new Float64Array(S.H*S.W);
    const incoming=b.chunk || b.cells || [];
    if(!r.words){r.words=new Uint32Array(S.H*S.W);r.seen=new Uint8Array(S.H*S.W);}
    for(const c of incoming){
      const i=c.y*S.W+c.x,w=parseInt(c.class_word,16);
      if(!Number.isInteger(c.x)||!Number.isInteger(c.y)||c.x<0||c.x>=S.W||c.y<0||c.y>=S.H||
        !/^[0-9a-f]{8}$/i.test(c.class_word)||w&0xff00||(w&255)>=S.info.classes.length||c.class_id!==(w&255)||
        c.confidence!==(w>>>16)/65536||(r.seen[i]&&r.words[i]!==w)){
        r.integrityError='页面原始CLASS/坐标/置信度冲突；保留已核对像素';break;
      }
    }
    if(r.integrityError){r.s.board.error=r.integrityError;r.s.board.integrity_error=true;r.s.board.status='error';r.s.status='error';
      if(id===S.runA)render(r.s.board,id);Panels.businessControls?.();return;}
    for (const c of incoming) {
      const i=c.y*S.W+c.x; r.pred[i]=c.class_id+1; r.conf[i]=c.confidence*255;
      r.words[i]=parseInt(c.class_word,16);r.seen[i]=1;
      if(id===S.runA)MapView.paintA(i);
      if(id===S.runB)MapView.paintB(i);
    }
    r.s.done=b.received_pixels; r.s.status=b.status;
    if (!S.viewCleared && (id===S.runA || (!S.runA&&id===S.live))) {
      render(r.s.board,id); MapView.dirty(); Panels.areaDirty=true;
    }
    pending=false;
    controls();Panels.businessControls?.();
  }
  function tick(m) {
    if (!active()) return;
    gate=m.source;
    if(m.run&&S.runs[m.run.id])Object.assign(S.runs[m.run.id].s,m.run);
    if (!S.viewCleared&&S.runA===m.run?.id && m.run?.source==='board' && m.run.board) apply(m.run.id,m.run.board);
    else if(!S.viewCleared&&S.runA && S.runs[S.runA]?.s.scene===S.scene)render(S.runs[S.runA].s.board || null,S.runA);
    else render(null,null);
    controls();
  }
  function selectionChanged() {
    if(!active())return;
    const selected=!S.viewCleared&&S.runs[S.runA]?.s;
    if(selected?.scene===S.scene){render(selected.board||null,S.runA);controls();return;}
    if(!liveInSelection()){
      S.runA=S.runB=null;S.rect=null;S.probe=null;
      clearUnavailable();render(null,null);Panels.clearTaskState();Panels.areaDirty=true;
      MapView.repaintAll();
    }else render(liveInSelection().board || null,S.live);
    controls();
  }
  function start(over={}) {
    if((over.kind||S.kind)==='eval')return Panels.metrics();
    if (!active() || !gate?.authorized || pending || probeRequest) return toast('请先连接板卡并等待当前请求完成');
    const kind=over.kind || S.kind,rect=over.rect || S.rect;
    if(kind==='region'&&!rect)return toast('请先框选区域');
    pending=true;startGeneration=S.viewGeneration;render();controls();
    send({cmd:'start',kind,scene:S.scene,version:over.version || S.version,rect:kind==='scan'?null:rect,pace_rows:0,origin:over.origin});
    return true;
  }
  function currentCell(x,y) {
    const r=S.runs[shownId],i=y*S.W+x;
    if(shown?.task_lifecycle || shown?.full_scene){if(!r?.seen?.[i])return null;const w=r.words[i];return {x,y,class_word:w.toString(16).padStart(8,'0').toUpperCase(),class_id:w&255,confidence_q16:w>>>16,confidence:(w>>>16)/65536};}
    return shown?.cells?.find(c=>c.x===x&&c.y===y);
  }
  function sampleCells(){const cells=[];for(let y=0;y<3;y++)for(let x=0;x<5;x++){const c=currentCell(x,y);if(c)cells.push(c);}return cells;}
  function clearUnavailable() {
    inputGeneration++;inputAbort?.abort();
    for(const id of ['chart-spectrum','chart-prob','chart-attn'])
      if(Panels.charts[id]) Panels.charts[id].clear();
    Panels.clearProbe();
    $('#probe-head').textContent='选择位置查看分类结果';
    for(const id of ['patch-rgb','patch-pred']) {
      const cv=$('#'+id),ctx=cv.getContext('2d');ctx.fillStyle='#0b1016';ctx.fillRect(0,0,cv.width,cv.height);
    }
  }
  function probe(row,col,{auto=true}={}) {
    if(!active())return;
    if(auto && (probeRequest || reusableProbe()&&['queued','running'].includes(shown?.interaction?.probe?.state))){
      toast('上一点仍在处理中，请等待结果后再选点');return;
    }
    clearUnavailable(); Panels.showTab('probe');
    const c=currentCell(col,row);
    S.probe={row,col,board:true,run:shownId};MapView.dirty();
    $('#probe-head').textContent=c?`${clsName(c.class_id+1)} · 置信度 ${(100*c.confidence).toFixed(2)}%`:'该像素尚未收到';
    const kv=[['位置',`行 ${row} 列 ${col}`],['任务',shown?`#${shown.task}`:'无本次任务'],
      ['模型',`${shown?.scene || S.scene} / ${shown?.model || S.version}`],['推理性能','未测'],['邻域','未接收像素留空；单点结果仅更新中心预览'],
      ['类别概率','单点探查后显示'],['12层注意力','暂不可用']];
    $('#probe-kv').replaceChildren();
    for(const pair of kv) pair.forEach((value,i)=>{const d=document.createElement('div');d.textContent=value;if(pair[0]==='12层注意力'&&i===1)d.dataset.attentionState='1';$('#probe-kv').append(d);});
    const ctx=$('#patch-pred').getContext('2d');
    const neighbors=[];for(let y=Math.max(0,row-3);y<=Math.min(S.H-1,row+3);y++)for(let x=Math.max(0,col-3);x<=Math.min(S.W-1,col+3);x++){const p=currentCell(x,y);if(p)neighbors.push(p);}
    for(const p of neighbors) {
      const x=p.x-col+3,y=p.y-row+3;
      if(x>=0 && x<7 && y>=0 && y<7){ctx.fillStyle=clsColor(p.class_id+1);ctx.fillRect(x*20,y*20,20,20);}
    }
    ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.strokeRect(60,60,20,20);
    probeState();
    const input=loadInput(row,col);
    // Submit immediately; downloading the local input preview must not delay PL.
    if(auto && !$('#board-probe-run').disabled)return Promise.allSettled([input,runPoint()]);
    return input;
  }
  async function loadInput(row,col) {
    const generation=inputGeneration,scene=S.scene,rid=S.live;
    const label=document.createElement('div'),value=document.createElement('div');
    label.textContent='输入来源';value.dataset.boardInputSource='';value.dataset.row=row;
    value.textContent='正在读取输入光谱……';$('#probe-kv').append(label,value);
    const controller=new AbortController();inputAbort=controller;
    const current=()=>generation===inputGeneration&&active()&&S.scene===scene&&S.live===rid;
    try {
      const response=await fetch(`/api/scene/${scene}/input-point?r=${row}&c=${col}`,{signal:controller.signal});
      if(!response.ok){let detail=`HTTP ${response.status}`;try{detail=(await response.json()).detail||detail;}catch{}throw Error(detail);}
      const p=await response.json();if(!current())return;
      if(p.scene!==scene||p.row!==row||p.col!==col||p.board_returned!==false||p.pc_model_inference!==false)
        throw Error('输入来源或坐标不匹配');
      value.textContent='预处理输入光谱';
      value.dataset.boardInputSource=JSON.stringify(p.source);
      Panels.chart('chart-spectrum').setOption({animation:false,
        title:{text:'预处理输入光谱',textStyle:{color:'#7b8ea3',fontSize:11},top:0},
        grid:{left:45,right:30,top:32,bottom:38},tooltip:{trigger:'axis'},
        xAxis:{type:'value',min:0,max:p.band_indices.length-1,name:'波段',nameTextStyle:{color:'#7b8ea3'}},
        yAxis:{type:'value',scale:true},series:[{name:'预处理输入值',type:'line',showSymbol:false,
          data:p.spectrum.map((v,i)=>[p.band_indices[i],v]),lineStyle:{color:'#00cec9'}}]},true);
      const ctx=$('#patch-rgb').getContext('2d');ctx.imageSmoothingEnabled=false;
      for(let y=0;y<7;y++)for(let x=0;x<7;x++){
        ctx.fillStyle=p.patch_valid[y][x]?`rgb(${p.patch_rgb[y][x].join(',')})`:'#000';ctx.fillRect(x*20,y*20,20,20);
      }
      ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.strokeRect(60,60,20,20);
    } catch(e) {
      if(!current()||e.name==='AbortError')return;
      value.textContent=`输入不可用：${e.message}`;
    }
  }
  function reusableProbe() {
    return shown && shownId===S.live && shown.scene===S.scene && S.runs[shownId]?.s.version===S.version &&
      shown.interaction?.state==='open' && !shown.error && !shown.integrity_error && !shown.preflight_rejected &&
      shown.start_seq!=null && (shown.ack||shown.accepted_via_info) && !shown.recovering && !shown.command;
  }
  function probeDisabledReason(point,p) {
    if(!active())return '请先选择板卡来源';
    if(['queued','running'].includes(S.speedComparison?.state))return '速度对比正在运行，请等待或先停止对比';
    if(probeRequest)return '正在提交单点探查请求，请等待服务回执';
    if(!point?.board || point.run!==shownId)return '请先在当前任务地图上选择一个像素';
    if(gate?.model_operation && !['done','error'].includes(gate.model_operation.state))return '模型操作尚未完成，请等待后再探查';
    // Host version IDs (v3) and board package tags (v3_board) are separate
    // namespaces. Reuse the validated host run binding, never compare tags.
    if(!reusableProbe()){
      if(['running','paused'].includes(S.runs[S.live]?.s.status))return '另一场景或模型的任务尚未结束，请先停止或等待完成';
      return gate?.authorized && gate?.active && gate?.channel_ready?'':'请先在“链路与下发”连接板卡';
    }
    if(gate?.active===false)return '板卡连接尚未就绪，请查看连接状态';
    if(['queued','running'].includes(p?.state))return `单点探查${p.state==='queued'?'排队中':'运行中'}，请等待完整回传`;
    return '';
  }
  function probeError(point,message) {
    if(point.probeError===message)return;
    point.probeError=message;
    const text=`单点探查失败（行 ${point.row} 列 ${point.col}）：${message}`;
    toast(text,5000);logLine(text,'error');
  }
  function probeCenter(point,result=null) {
    const ctx=$('#patch-pred').getContext('2d'),cell=currentCell(point.col,point.row);
    const compatible=!result?.identity?.scene || result.identity.scene===S.scene;
    ctx.fillStyle=result && compatible?clsColor(result.class_id+1):cell?clsColor(cell.class_id+1):'#0b1016';
    ctx.fillRect(60,60,20,20);ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.strokeRect(60,60,20,20);
    $('#patch-pred').nextElementSibling.textContent=result?'邻域分类 · 中心为本次单点探查':'邻域分类';
  }
  function probeState() {
    const s=shown?.interaction,p=s?.probe,point=S.probe;
    const selected=point?.board && point.run===shownId;
    const matches=selected && p?.row===point.row && p?.col===point.col;
    const requesting=!!probeRequest && probeRequest.point===point && (probeRequest.standalone || probeRequest.rid===shownId);
    if(matches && !requesting && p.state==='error' && !point.probeError)probeError(point,p.error || '板卡未完整返回探查结果');
    const same=matches && !point.probeError && !requesting;
    const button=$('#board-probe-run'),reason=probeDisabledReason(point,p),text=$('#board-probe-state');
    button.hidden=true;
    button.disabled=!!reason;button.title=reason || '在地图上单击像素，自动发起板端探查';
    button.textContent=requesting?'正在请求探查…':same && p.state==='queued'?'探查排队中…':same && p.state==='running'?'板端探查中…':'重新探查此点';
    button.setAttribute('aria-busy',String(requesting || ['queued','running'].includes(p?.state)));
    text.textContent=requesting?(probeRequest.standalone?'已自动发起本场景单点任务；首次加载约15～40秒，请等待板卡回传。':'已自动提交单点探查，等待板端完整回传。'):same ? `单点探查 ${{queued:'排队中',running:'运行中',done:'完成',error:'失败'}[p.state]||p.state}${p.error?' · '+p.error:''}` : reason || '在地图上单击像素即可自动探查；拖动或框选不会触发。';
    if(selected && (requesting || same && ['queued','running'].includes(p.state)))$('#probe-head').textContent=`${requesting?'正在请求单点探查':p.state==='queued'?'单点探查排队中':'板端正在探查'} · 行 ${point.row} 列 ${point.col}`;
    if(!same || p.state!=='done'){
      if(Panels.charts['chart-prob'])Panels.charts['chart-prob'].clear();
      if(Panels.charts['chart-attn'])Panels.charts['chart-attn'].clear();
      if(point)delete point.attn;
      $('#rng-layer').disabled=true;
      const attentionState=$('#probe-kv [data-attention-state]');if(attentionState)attentionState.textContent='暂不可用；等待本次完整回传';
      if(selected){
        probeCenter(point);
        if(point.probeError){text.textContent=`探查失败：${point.probeError}${reason?' · '+reason:''}`;$('#probe-head').textContent=`单点探查失败 · 行 ${point.row} 列 ${point.col}`;}
      }
      $$('#probe-kv [data-probe-logits]').forEach(el=>el.remove());return;
    }
    const label=i=>p.identity?.scene && p.identity.scene!==S.scene?`类别 ${i}`:clsName(i+1);
    if(p.identity)text.textContent+=` · ${p.identity.scene} / ${p.identity.model || p.identity.wcrc}`;
    text.textContent+=` · ${label(p.class_id)} · 置信度 ${(100*p.confidence_q16/65536).toFixed(2)}%`;
    $('#probe-head').textContent=`${label(p.class_id)} · 置信度 ${(100*p.confidence_q16/65536).toFixed(2)}% · 本次单点探查`;
    probeCenter(point,p);
    const kv=$('#probe-kv');
    let line=kv.querySelector('[data-probe-logits="value"]');
    if(!line){const label=document.createElement('div');label.textContent='板端 LOGITS (Q16)';label.dataset.probeLogits='label';line=document.createElement('div');line.dataset.probeLogits='value';kv.append(label,line);}
    line.textContent=p.logits_q16.join(', ');line.hidden=true;kv.querySelector('[data-probe-logits="label"]').hidden=true;
    const raw=p.attention_q24;
    const validAttention=Array.isArray(raw)&&raw.length===432&&JSON.stringify(p.attention_shape)==='[12,6,6]'&&raw.every(v=>Number.isInteger(v)&&v>=0&&v<=16777216);
    $('#rng-layer').disabled=!validAttention;
    if(validAttention){
      point.attn=Array.from({length:12},(_,l)=>Array.from({length:6},(_,r)=>raw.slice(l*36+r*6,l*36+r*6+6).map(v=>v/16777216)));
      Panels.attn();text.textContent+=` · PL 12×6×6 Q0.24 / CRC ${p.attention_crc32}`;
    }else{delete point.attn;if(Panels.charts['chart-attn'])Panels.charts['chart-attn'].clear();text.textContent+=' · 注意力未测/不完整';}
    const attentionState=$('#probe-kv [data-attention-state]');if(attentionState)attentionState.textContent=validAttention?`PL原字 · 12×6×6 · CRC ${p.attention_crc32}`:'暂不可用；未测或不完整';
    Panels.chart('chart-prob').setOption({animation:false,grid:{left:90,right:20,top:12,bottom:24},
      xAxis:{type:'value',min:0,max:1},yAxis:{type:'category',data:p.probabilities.map((_,i)=>label(i))},
      series:[{type:'bar',data:p.probabilities}]},true);
  }
  async function runPoint(){
    const point=S.probe,rid=S.live,reason=probeDisabledReason(point,shown?.interaction?.probe);
    if(reason){toast(reason);return;}
    const standalone=!reusableProbe(),scene=S.scene,version=S.version;
    const request={point,rid,standalone,viewGeneration:S.viewGeneration,previousSeq:shown?.interaction?.probe?.req_seq};probeRequest=request;
    delete point.probeError;delete point.attn;
    probeState();controls();
    // Clear previous result before the request, so an error never looks like success.
    if(Panels.charts['chart-prob'])Panels.charts['chart-prob'].clear();
    if(Panels.charts['chart-attn'])Panels.charts['chart-attn'].clear();$('#rng-layer').disabled=true;
    $$('#probe-kv [data-probe-logits]').forEach(el=>el.remove());
    try {
      const url=standalone?'/api/board/point-probe':`/api/run/${rid}/board/probe`;
      const body={row:point.row,col:point.col,...(standalone?{scene,version,confirmed:true}:{})};
      const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const value=await response.json();if(!response.ok)throw Error(value.detail||response.statusText);
      if(standalone){
        const id=value.run.id;
        if(S.probe===point && S.scene===scene && S.version===version && (!S.live || S.live===rid || S.live===id)){
          S.runs[id] ||= {s:value.run,pred:null,conf:null,loaded:false};
          S.viewCleared=false;S.keyScenePreview=false;S.live=id;S.runA=id;S.rect=null;point.run=id;request.rid=id;request.standalone=false;
          const latest=await(await fetch(`/api/run/${id}/board`)).json();
          apply(id,latest);await loadRun(id);
          await probe(point.row,point.col,{auto:false});
          Panels.runState(S.runs[id].s);MapView.repaintAll();Panels.areaDirty=true;
        }
      }else if(shown && shownId===rid && S.live===rid&&S.probe===point){
        const current=shown.interaction.probe;
        // A WebSocket result may arrive before this HTTP acknowledgement.
        const progressed=current?.row===point.row && current?.col===point.col && current.req_seq!=null && current.req_seq!==request.previousSeq;
        if(!progressed)shown.interaction.probe=value;
      }
    } catch(e){probeError(point,e.message);}
    finally{if(probeRequest===request)probeRequest=null;probeState();controls();}
  }
  $('#board-probe-run').onclick=runPoint;
  $('#board-session-close').onclick=async()=>{
    const r=await fetch('/api/board/session/close',{method:'POST'});if(!r.ok)toast((await r.json()).detail);
  };
  async function recoverTask(rid,b){
    if(!b?.task_lifecycle || !confirm(`恢复任务 #${b.task} 的连接和缺失结果？不会发新任务或自动恢复暂停的计算。`))return;
    recoveryPending=true;$('#board-recover').disabled=true;controls();
    try {
      const response=await fetch(`/api/run/${rid}/board/recover`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({boot_id:b.boot_id,session:b.session,task:b.task,wcrc:b.wcrc,confirmed:true})});
      const value=await response.json();if(!response.ok)throw Error(value.detail||response.statusText);
      S.live=rid;apply(rid,value);
    }catch(e){toast(`未恢复：${e.message}`);render(b,rid);}
    finally{recoveryPending=false;controls();}
  }
  $('#board-recover').onclick=()=>recoverTask(shownId,shown);
  $('#task-recover').onclick=()=>recoverTask(S.live,S.runs[S.live]?.s.board);
  $('#board-acceptance').onclick=async()=>{
    const rid=shownId,r=S.runs[rid],b=r?.s.board,label=$('#board-acceptance-state');
    if(!(b?.task_lifecycle || b?.full_scene) || !['done','stopped'].includes(b.status) || !r.words || !r.seen)return;
    $('#board-acceptance').disabled=true;label.textContent='正在只读核验并整理证据，不发推理命令……';
    try {
      const bytes=new Uint8Array(5*S.H*S.W);bytes.set(new Uint8Array(r.words.buffer),0);bytes.set(r.seen,4*S.H*S.W);
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
      const response=await fetch(`/api/run/${rid}/board/acceptance`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({boot_id:b.boot_id,session:b.session,task:b.task,browser_words_sha256:digest})});
      const result=await response.json();if(!response.ok)throw Error(result.detail||response.statusText);
      label.textContent=`任务数据核验通过${b.status==='stopped'?'（已停止，仅核验实际完成部分）':''}；运行中通信 ${result.report.s3?.passed?'通过':'未通过/缺证据'}；单点核验 ${result.report.probe?.passed?'通过':'未通过/尚未探查'}。不代表全部功能验收；正在下载记录。`;
      const a=document.createElement('a');a.href=result.download;a.click();
    }catch(e){label.textContent=`核验未通过或缺材料：${e.message}。保留本次结果，不自动重跑。`;}
    finally{$('#board-acceptance').disabled=false;}
  };
  $('#board-export-json').onclick=async()=>{ if(shown){const b=(shown.task_lifecycle || shown.full_scene)?await(await fetch(`/api/run/${shownId}/board`)).json():shown;download(`board_${b.boot_id}_${b.task}.json`,JSON.stringify(b,null,2));} };
  $('#board-export-csv').onclick=()=>{ if(shown && shownId) { const a=document.createElement('a'); a.href=`/api/run/${shownId}/board.csv`; a.click(); } };
  render();
  return {source, apply, tick, start, probe,controls,selectionChanged,
    allowRunDisplay:()=>!(pending&&startGeneration!==S.viewGeneration)&&!(probeRequest?.standalone&&probeRequest.viewGeneration!==S.viewGeneration),
    clearView:()=>{clearUnavailable();render(null,null);controls();},
    rejected: c=>{if(c==='start')pending=false;controls();},gate: g=>{gate=g;if(active()){S.source=g;render(shown);controls();}}};
})();
