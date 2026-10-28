'use strict';
// Read-only evaluation of the selected real board result, including history.
Object.assign(Panels, (() => {
  const P=Panels,X={}, {AX,TT}=P;
  let generation=0,last=null,liveBusy=false,lastLive=0,lastSignature='';
  const escape=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  X.clearMetrics=()=>{
    generation++;last=null;lastSignature='';
    for(const id of ['btn-metrics-export','btn-metrics-csv'])$('#'+id).disabled=true;
    for(const id of ['m-oa','m-aa','m-kappa','m-f1'])$('#'+id).textContent='—';
    for(const id of ['chart-perclass','chart-cm'])P.charts[id]?.clear();
    $('#tbl-eval-classes tbody').replaceChildren();
    $('#m-n').textContent='选择当前或历史板卡任务后评测。';$('#m-n').title='';
    $('#eval-summary').textContent='评测只读取已收到的分类结果，不重新推理。';
    $('#m-total-coverage').textContent='全测试集覆盖：—';
    $('#m-task-coverage').textContent='任务范围内测试点覆盖：—';
  };
  X.evalTasks=()=>{
    const select=$('#sel-eval-run');select.replaceChildren();
    const empty=document.createElement('option');empty.value='';empty.textContent='请选择已识别的板卡任务';select.append(empty);
    for(const r of Object.values(S.runs).filter(r=>r.s.source==='board'&&r.s.scene===S.scene).sort((a,b)=>b.s.id-a.s.id)){
      const o=document.createElement('option'),s=r.s;o.value=String(s.id);
      o.textContent=`#${s.id} · ${s.version} · ${s.kind==='scan'?'整景':s.rect?.[2]===1&&s.rect?.[3]===1?'单点':'区域'} · ${fmt.n(s.done)} 像素`;
      select.append(o);
    }
    select.value=S.runA?String(S.runA):'';
    $('#btn-metrics').disabled=!S.runs[S.runA]||!(S.runs[S.runA].s.done>0);
  };
  X.metrics=async(rid=S.runA,{quiet=false}={})=>{
    if(!rid){X.clearMetrics();$('#m-n').textContent='请先选择一项历史结果，或开始整景巡检。';return;}
    if(!quiet)X.clearMetrics();
    const token=generation,scene=S.scene,source=S.source?.source;
    const current=()=>token===generation&&scene===S.scene&&rid===S.runA&&source===S.source?.source;
    if(!quiet)$('#m-n').textContent='正在核对测试集标签与板卡分类结果…';
    try{
      const response=await fetch(`/api/run/${rid}/metrics`),m=await response.json();
      if(!current())return;if(!response.ok)throw Error(m.detail||response.statusText);
      const run=S.runs[rid]?.s,names=m.class_names||classNames();
      last={report:m,rid,scene,source};
      for(const id of ['btn-metrics-export','btn-metrics-csv'])$('#'+id).disabled=false;
      $('#eval-summary').textContent=`任务 #${rid} · ${run?.scene} / ${run?.version} · ${run?.status} · 已收到 ${fmt.n(m.received_pixels)} 像素 · 正确测试像素 ${fmt.n(m.correct_pixels)}`;
      $('#m-total-coverage').textContent=`全测试集覆盖：${fmt.n(m.n)} / ${fmt.n(m.test_total)}（${fmt.pct(m.coverage)}）`;
      $('#m-task-coverage').textContent=`任务范围内测试点覆盖：${fmt.n(m.n)} / ${fmt.n(m.task_test_total)}（${fmt.pct(m.task_test_coverage)}）`;
      $('#m-n').textContent=!m.n?'当前结果没有覆盖测试像素，不能计算精度；可选择更大区域或整景巡检。':
        `${m.complete_test_coverage?'完整测试集指标':'当前已覆盖测试像素的指标，不能代表完整测试集'} · 已覆盖 ${m.evaluated_classes} / ${names.length} 类`;
      $('#m-n').title=m.evaluation?`标签 SHA256 ${m.evaluation.manifest_sha256}\n分类结果 SHA256 ${m.prediction_words_seen_sha256}`:'';
      $('#m-oa').textContent=fmt.f(m.OA==null?null:100*m.OA,2);
      $('#m-aa').textContent=fmt.f(m.AA==null?null:100*m.AA,2);
      $('#m-kappa').textContent=m.n&&m.Kappa==null?'未定义':fmt.f(m.Kappa,4);
      $('#m-f1').textContent=fmt.f(m.macro_F1==null?null:100*m.macro_F1,2);
      $('#tbl-eval-classes tbody').innerHTML=names.map((name,i)=>`<tr><td>${escape(name)}</td><td class="num">${fmt.n(m.support[i])}</td><td class="num">${fmt.n(m.cm[i][i])}</td><td class="num">${fmt.pct(m.precision[i],2)}</td><td class="num">${fmt.pct(m.per_class[i],2)}</td><td class="num">${fmt.pct(m.f1[i],2)}</td></tr>`).join('');
      if(!m.n){for(const id of ['chart-perclass','chart-cm'])P.charts[id]?.clear();return;}
      P.chart('chart-perclass').setOption({animation:false,legend:{data:['精确率','召回率','F1'],textStyle:{color:'#7b8ea3'},top:0},
        grid:{left:38,right:8,top:30,bottom:70},tooltip:{...TT,trigger:'axis'},
        xAxis:{type:'category',data:names,...AX,axisLabel:{color:'#7b8ea3',fontSize:9,rotate:40}},
        yAxis:{type:'value',min:0,max:1,...AX,axisLabel:{formatter:v=>`${Math.round(v*100)}%`,color:'#7b8ea3'}},
        series:[['精确率',m.precision,'#38bdf8'],['召回率',m.per_class,'#2dd4bf'],['F1',m.f1,'#fbbf24']].map(([name,data,color])=>({name,type:'bar',data,itemStyle:{color}}))},true);
      const data=[];m.cm.forEach((row,i)=>{const n=row.reduce((a,b)=>a+b,0);row.forEach((count,j)=>data.push([j,i,n?count/n:0,count]));});
      P.chart('chart-cm').setOption({animation:false,title:{text:'混淆矩阵：行＝真实类别，列＝分类结果',textStyle:{color:'#7b8ea3',fontSize:11,fontWeight:'normal'}},
        grid:{left:100,right:12,top:32,bottom:90},tooltip:{...TT,formatter:q=>`真实：${escape(names[q.value[1]])}<br>分类：${escape(names[q.value[0]])}<br>${q.value[3]} 像素（${fmt.pct(q.value[2])}）`},
        xAxis:{type:'category',data:names,...AX,axisLabel:{color:'#7b8ea3',fontSize:9,rotate:45}},
        yAxis:{type:'category',data:names,inverse:true,...AX,axisLabel:{color:'#7b8ea3',fontSize:9}},
        visualMap:{show:false,min:0,max:1,inRange:{color:['#0b1016','#123a4a','#0d9488','#2dd4bf','#fef08a']}},
        series:[{type:'heatmap',data,label:{show:names.length<=10,color:'#fff',fontSize:9,formatter:q=>q.value[2]>=.01?`${Math.round(100*q.value[2])}%`:''}}]},true);
    }catch(error){if(current()){$('#m-n').textContent=`评测暂不可用：${error.message}`;}}
  };
  X.liveMetrics=r=>{
    const signature=r?`${r.id}:${r.done}:${r.status}`:'';
    if(!r||P.tab!=='eval'||!$('#chk-eval-live').checked||liveBusy||lastSignature===signature||Date.now()-lastLive<3000)return;
    lastSignature=signature;lastLive=Date.now();liveBusy=true;
    X.metrics(r.id,{quiet:true}).finally(()=>{liveBusy=false;});
  };
  $('#btn-metrics').onclick=()=>X.metrics();
  $('#btn-metrics-export').onclick=()=>{
    if(!last||last.rid!==S.runA||last.scene!==S.scene)return X.clearMetrics();
    download(`metrics_run_${last.rid}.json`,JSON.stringify(last.report,null,2));
  };
  $('#btn-metrics-csv').onclick=()=>{if(last&&last.rid===S.runA){const a=document.createElement('a');a.href=`/api/run/${last.rid}/metrics.csv`;a.click();}};
  $('#sel-eval-run').onchange=async e=>{
    const rid=Number(e.target.value);if(!rid)return;
    await P.setAB(rid,null);P.showTab('eval');await X.metrics(rid);
  };
  $('#btn-eval-scan').onclick=()=>{P.setKind('scan');P.showTab('eval');BoardPanel.start({kind:'scan',origin:'evaluation'});};
  return X;
})());
