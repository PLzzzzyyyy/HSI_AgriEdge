'use strict';
// 闭环更新面板（PLAN §15.2）：旧模型巡检 → 地面分析 → 人工核查标注 → 模型更新 → 权重下发 → 复测对比
const Loop = (() => {
  const L = { ft: [] };
  const P = Panels;

  function cl() { return S.info?.closed_loop; }
  function rect() { const g = cl().region.region; return [g.row0, g.col0, g.size, g.size]; }
  function oldVersion(){return `hold${cl().region.hold_class}`;}

  const STEPS = [
    ['旧模型巡检', '按该场景登记的闭环前权重识别固定核查区域', 'run_old', '运行'],
    ['地面分析', '低置信 / 碎斑待核查列表', 'analyze', '分析'],
    ['人工核查标注', '农艺师在区域内标注真实类别（取自官方 Train100，不碰 Test）', 'annotate', '显示标注点'],
    ['模型更新', '用标注点微调，更新后进行板卡复测', 'finetune', '现场微调'],
    ['权重下发', '下发并校验新权重', 'upload', '下发'],
    ['复测对比', '新权重重跑同一区域，与旧结果滑动对比', 'run_new', '复测'],
  ];

  L.render = () => {
    const box = $('#loop-steps');
    if (!cl()) { box.innerHTML = '<div class="note">闭环演示数据只做了 LongKou（model/finetune_region.py）。切到 longkou 景查看。</div>'; $('#tbl-loop tbody').innerHTML = ''; return; }
    const info = cl(), hold = info.region.hold_class;
    box.innerHTML = `<div class="note">核查目标 <b style="color:${clsColor(hold)}">${clsName(hold)}</b>；旧权重 ${oldVersion()}，新权重 ${S.loopVersion||'待微调'}；区域 ${info.region.region.size}×${info.region.region.size}，起点 (${info.region.region.row0}, ${info.region.region.col0})。只用实际板任务验证效果。</div>` +
      `<div class="ctl-row small">训练标注数 <input type="number" id="loop-annotate" min="1" max="90" value="${S.loopAnnotate??30}">（官方 Train100，余留验证样本）</div>`+
      STEPS.map(([t, d, act, btn], k) => `<div class="step ${S.loop[act] ? 'done' : ''}"><div class="n">${k + 1}</div>
        <div class="d">${t}<small>${d}</small>${act === 'finetune' ? '<small id="ft-line" class="mono"></small>' : ''}</div>
        <div class="acts">${act==='run_old'?'<button class="btn" data-act="upload_old">上传基线</button>':''}<button class="btn ${k === 0 ? 'primary' : ''}" data-act="${act}">${btn}</button></div></div>`).join('');
    $$('#loop-steps [data-act]').forEach(b => b.onclick = () => act(b.dataset.act));
    $('#loop-annotate').onchange=e=>{S.loopAnnotate=+e.target.value;};
    L.gate();
    table();
  };
  L.gate=()=>{
    const ready=S.source?.capabilities?.models===true;
    $$('#loop-steps [data-act]').filter(b=>['run_old','run_new','upload','upload_old'].includes(b.dataset.act)).forEach(b=>b.disabled=!ready);
    $('#loop-model-state').textContent=ready?'':'多模型上传与安全切换尚未接通；这些步骤不会发送任务。已有真实任务可在历史页对比。';
  };

  let tableGeneration=0;
  async function table() {
    const generation=++tableGeneration,a=S.loopOld,b=S.loopNew,scene=S.scene;
    const current=()=>generation===tableGeneration&&a===S.loopOld&&b===S.loopNew&&scene===S.scene;
    $('#tbl-loop tbody').innerHTML='<tr><td colspan="3">等待更新前后板卡任务的实测比较</td></tr>';
    $('#loop-compare-state').textContent='';
    if(P.charts['chart-loop'])P.charts['chart-loop'].clear();
    if(!a||!b)return;
    try {
      const response=await fetch(`/api/compare?a=${a}&b=${b}`),c=await response.json();
      if(!current())return;
      if(!response.ok)throw Error(c.detail||response.statusText);
      const rows=[['共同已接收像素',fmt.n(c.common),fmt.n(c.common)],['分类变化像素','—',fmt.n(c.changed)],
        ['共同 Test100 像素',fmt.n(c.labeled),fmt.n(c.labeled)],['共同 Test100 OA',fmt.pct(c.acc_a,2),fmt.pct(c.acc_b,2)],
        ['共同 Test100 AA',fmt.pct(c.metrics_a?.AA,2),fmt.pct(c.metrics_b?.AA,2)],['共同 Test100 Kappa',fmt.f(c.metrics_a?.Kappa,4),fmt.f(c.metrics_b?.Kappa,4)]];
      $('#tbl-loop tbody').innerHTML=rows.map(r=>`<tr><td>${r[0]}</td><td class="num">${r[1]}</td><td class="num">${r[2]}</td></tr>`).join('');
      $('#loop-compare-state').textContent=`${c.complete_task_coverage?'两任务完整覆盖':'部分覆盖'} · ${c.same_roi?'同一ROI':'不同ROI，仅统计共同像素'} · 对比快照`;
      if(!c.evaluation?.available)$('#loop-compare-state').textContent+='；固定标签评测不可用，不填训练成绩';
      if(!c.metrics_a||!c.metrics_b)return;
      P.chart('chart-loop').setOption({animation:false,tooltip:{...P.TT,trigger:'axis'},legend:{textStyle:{color:'#b8c7d6'}},
        grid:{left:36,right:8,top:30,bottom:70},xAxis:{type:'category',data:classNames(),...P.AX,axisLabel:{rotate:35,color:'#7b8ea3',fontSize:9}},
        yAxis:{type:'value',min:0,max:1,...P.AX},series:[{name:'更新前板测',type:'bar',data:c.metrics_a.per_class,itemStyle:{color:'#475569'}},
        {name:'更新后板测',type:'bar',data:c.metrics_b.per_class,itemStyle:{color:'#2dd4bf'}}]},true);
    } catch(e) {if(current()){$('#tbl-loop tbody').innerHTML='';$('#loop-compare-state').textContent=`对比不可用：${e.message}；不显示旧成绩`;}}
  }
  L.table=table;

  function done(a) { S.loop[a] = true; L.render(); }

  async function act(a) {
    if(a==='upload_old') {
      $('#sel-upload').value=oldVersion();send({cmd:'upload',scene:S.scene,version:oldVersion(),activate:true});
    } else if (a === 'run_old') {
      S.loopWait = { step: 'run_old', version: oldVersion(), scene:S.scene, rect:rect(), rid:null };
      P.setRect(rect()); MapView.flyTo(rect()[0] + 32, rect()[1] + 32, Math.min(8, S.view.k * 2.5));
      if(!P.start({ kind: 'region', rect: rect(), version: oldVersion() }))S.loopWait=null;
    } else if (a === 'analyze') {
      if(S.loopOld)await P.setAB(S.loopOld,null);
      if(await P.analyze())done(a); P.showTab('loop');
    } else if (a === 'annotate') {
      const scene=S.scene,n=S.loopAnnotate??30;
      if(!Number.isInteger(n)||n<1||n>90)return toast('标注数需为1～90的整数');
      try {
        const response=await fetch(`/api/scene/${scene}/annotations?count=${n}`),ann=await response.json();
        if(scene!==S.scene||n!==(S.loopAnnotate??30))return;
        if(!response.ok)throw Error(ann.detail||response.statusText);
        S.annotations=ann.points;S.layers.marks=true;MapView.dirty();
        logLine(`显示 ${ann.count} 个官方 Train100 核查标注（${ann.inside_region} 个在区域内；不使用Test，不冒充现场采样）`);done(a);
      }catch(e){toast(`标注加载失败：${e.message}`);}
    } else if (a === 'finetune') {
      const n=S.loopAnnotate??30;if(!Number.isInteger(n)||n<1||n>90)return toast('标注数需为1～90的整数');
      L.ft = []; send({ cmd: 'finetune', scene:S.scene, base_version:oldVersion(), rect:rect(), annotate:n });
    } else if (a === 'upload') {
      const v = S.loopVersion;if(!v)return toast('请先完成模型更新');
      $('#sel-upload').value = v; send({ cmd: 'upload', scene: S.scene, version: v,activate:true });
    } else if (a === 'run_new') {
      if(!S.loopVersion||!S.loopOld||!S.loop.upload)return toast('请先完成更新前任务、模型更新以及上传/激活确认');
      S.loopWait = { step: 'run_new', version: S.loopVersion, scene:S.scene, rect:rect(), rid:null };
      P.setRect(rect()); if(!P.start({ kind: 'region', rect: rect(), version: S.loopVersion }))S.loopWait=null;
    }
  }

  L.onRunStart=r=>{const w=S.loopWait;if(w&&r.source==='board'&&r.scene===w.scene&&r.version===w.version&&JSON.stringify(r.rect)===JSON.stringify(w.rect))w.rid=r.id;};
  L.onCommandError=c=>{if(c==='start')S.loopWait=null;};

  L.onRunEnd = r => {
    const w = S.loopWait;
    if (!w || r.id!==w.rid || r.source!=='board' || r.scene!==w.scene || r.kind !== 'region' || r.version !== w.version || JSON.stringify(r.rect)!==JSON.stringify(w.rect)) return;
    S.loopWait = null;
    if(r.status!=='done'||r.done!==r.total||r.board?.error)return toast('闭环任务未完整完成，不记为复测成功');
    if (w.step === 'run_old') { S.loopOld = r.id; done('run_old'); }
    else {
      S.loopNew=r.id;
      done('run_new');
      if (S.loopOld && S.runs[S.loopOld]) { P.showTab('runs'); P.setAB(r.id, S.loopOld); toast('左：更新后　右：更新前（拖动中线对比）', 4000); }
    }
  };
  L.onUpload = m => { if (m.ok && m.source==='board' && m.persisted===true && m.activated===true && m.scene===S.scene && m.version === S.loopVersion) done('upload'); };

  L.onFinetune = async m => {
    if(m.scene && m.scene!==S.scene)return;
    const el = $('#ft-line');
    if (m.state === 'start') { if (el) el.textContent = '启动中…（加载整景约 1 分钟）'; }
    else if (m.state === 'epoch') { if (el) el.textContent = `${m.line}  · ${fmt.f(m.t, 0)} s`; }
    else if (m.state === 'error') { if (el) el.textContent = '失败，见日志'; }
    else if (m.state === 'done') {
      S.loopVersion = m.tag;
      const info = await (await fetch(`/api/scene/${S.scene}`)).json();
      S.info.versions = info.versions;
      $('#sel-version').innerHTML = info.versions.map(v => `<option value="${v.id}">${v.label}</option>`).join('');
      $('#sel-version').value = S.version;
      $('#sel-upload').innerHTML = info.versions.filter(v => v.pkg).map(v => `<option value="${v.id}">${v.label} · ${fmt.bytes(v.pkg_bytes)}</option>`).join('');
      done('finetune'); table();
      toast(`现场微调完成：${fmt.f(m.seconds, 0)} s，新版本 ${m.tag}`, 4000);
    }
  };
  return L;
})();
