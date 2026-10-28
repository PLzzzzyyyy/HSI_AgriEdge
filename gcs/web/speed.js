'use strict';
const SpeedPanel=(()=>{
  let data=null,rect=null,hidden=new Set(),frame=0,replayStart=null,historyGeneration=0,following=true;
  const hydrating=new Set();
  const busy=()=>['queued','running'].includes(S.speedComparison?.state);
  const name=v=>S.info?.versions.find(x=>x.id===v)?.label||v;
  function scope(){
    $('#speed-scope').textContent=rect?`${S.scene} · 行 ${rect[0]}～${rect[0]+rect[2]-1}，列 ${rect[1]}～${rect[1]+rect[3]-1} · ${rect[2]}×${rect[3]} = ${fmt.n(rect[2]*rect[3])} 像素`:'请先选择对比区域';
  }
  function recordSelection(value){
    if(value?.scene!==S.scene)return;
    rect=[...value.rect];scope();
    $('#speed-a').value=value.versions[0];$('#speed-b').value=value.versions[1];
  }
  function controls(){
    const active=busy();$('#speed-start').disabled=active||!rect||!$('#speed-a').value||!$('#speed-b').value||$('#speed-a').value===$('#speed-b').value||!S.source?.channel_ready;
    $('#speed-stop').disabled=!active;
    for(const id of ['speed-a','speed-b','speed-use-roi','speed-default-roi','speed-history'])$('#'+id).disabled=active;
    $('#speed-replay').disabled=data?.state!=='done';$('#speed-export').disabled=!data;
    $('#speed-start').title=!S.source?.channel_ready?'板卡连接未就绪，请先连接板卡':$('#speed-a').value===$('#speed-b').value?'请选择两个不同权重':'在同一区域依次实测两个权重';
    if(!data&&!active)$('#speed-state').textContent=!S.source?.channel_ready?'板卡连接未就绪，请在“链路与下发”连接后开始实测':'已就绪；请选择两个权重和同一对比区域';
  }
  function configure(){
    const versions=S.info?.versions.filter(v=>v.pkg&&v.deployable!==false)||[];
    for(const id of ['speed-a','speed-b']){
      const el=$('#'+id);el.replaceChildren();
      for(const v of versions){const o=document.createElement('option');o.value=v.id;o.textContent=v.label;el.append(o);}
    }
    $('#speed-a').value=versions.some(v=>v.id===S.version)?S.version:versions[0]?.id||'';
    $('#speed-b').value=versions.find(v=>v.id!==$('#speed-a').value)?.id||'';
    rect=[Math.max(0,Math.floor((S.H-32)/2)),Math.max(0,Math.floor((S.W-64)/2)),Math.min(32,S.H),Math.min(64,S.W)];
    scope();controls();render();
  }
  function pointAt(item,ms,clock){
    let done=0;
    for(const p of item.trace||[]){const at=clock==='compute'?p.compute_ms:p.t_ms;if(at!=null&&at<=ms)done=p.done;}
    return done;
  }
  function map(canvas,item,count){
    const x=canvas.getContext('2d'),w=canvas.width,h=canvas.height;
    x.clearRect(0,0,w,h);x.fillStyle='#080e14';x.fillRect(0,0,w,h);
    if(!data||data.scene!==S.scene||!S.base)return;
    const [r,c,rh,cw]=data.rect,k=Math.min((w-20)/cw,(h-20)/rh),ox=(w-cw*k)/2,oy=(h-rh*k)/2;
    x.imageSmoothingEnabled=false;x.drawImage(S.base,c,r,cw,rh,ox,oy,cw*k,rh*k);
    const run=S.runs[item?.run_id];
    if(run?.pred)for(let i=0;i<Math.min(count,rh*cw);i++){
      const y=r+Math.floor(i/cw),col=c+i%cw,idx=y*S.W+col;
      if(!run.seen?.[idx])continue;
      x.fillStyle=clsColor(run.pred[idx]);x.fillRect(ox+(col-c)*k,oy+(y-r)*k,k+.1,k+.1);
    }
    x.strokeStyle='#2dd4bf';x.lineWidth=2;x.strokeRect(ox,oy,cw*k,rh*k);
    if(count>0&&count<rh*cw){const yy=oy+Math.floor(count/cw)*k;x.strokeStyle='#fff';x.beginPath();x.moveTo(ox,yy);x.lineTo(ox+cw*k,yy);x.stroke();}
  }
  function render(time=null){
    if(Panels.tab!=='speed')return;
    const valid=data&&data.scene===S.scene,clock=$('#speed-clock').value;
    ['a','b'].forEach((key,i)=>{
      const item=valid?data.items[i]:null,cv=$('#speed-map-'+key);
      const count=item?(time==null?item.done:pointAt(item,time,clock)):0;
      $('#speed-title-'+key).textContent=`${key.toUpperCase()} · ${item?name(item.version):name($('#speed-'+key).value)||'等待'}${item?.run_id?' · 任务 #'+item.run_id:''}`;
      map(cv,item,count);
      $('#speed-value-'+key).textContent=item?`${fmt.n(count)} / ${fmt.n(item.total)} 像素 · ${fmt.pct(count/item.total)}\n${fmt.f(item.rate,3)} px/s · ${fmt.f(item.ms_per_pixel,6)} ms/像素 · 任务 ${fmt.f(item.elapsed_s,2)} s`:'等待本权重运行';
    });
    const a=valid?data.items[0]:null,b=valid?data.items[1]:null;
    if(a?.rate&&b?.rate){
      const gain=(b.rate/a.rate-1)*100;
      $('#speed-delta').textContent=`B / A 计算倍率 ${fmt.f(b.rate/a.rate,4)}× · ${gain>=0?'快':'慢'} ${fmt.f(Math.abs(gain),3)}% · 每像素差 ${fmt.f(a.ms_per_pixel-b.ms_per_pixel,6)} ms${Math.abs(gain)<5?' · 速度接近':''}`;
    }else $('#speed-delta').textContent=valid?'等待两项板端计时，不用准备时间代替计算速度':'—';
    if(time!=null)$('#speed-state').textContent=`同步回放 · ${clock==='compute'?'板端计算':'任务'}时间 ${fmt.f(time/1000,2)} s · 使用记录的进度点`;
  }
  function update(next){
    S.speedComparison=next;
    if(!next){controls();return;}
    if(!following){controls();return;}
    if(hidden.has(next.id)){controls();return;}
    if(data?.id!==next.id){cancelAnimationFrame(frame);replayStart=null;recordSelection(next);}
    data=next;
    if(data.scene===S.scene)for(const item of data.items){
      const run=S.runs[item.run_id];
      if(run&&!run.loaded&&!hydrating.has(item.run_id)){
        hydrating.add(item.run_id);loadRun(item.run_id).catch(e=>toast('对比像素恢复失败：'+e.message)).finally(()=>{hydrating.delete(item.run_id);render();});
      }
    }
    $('#speed-state').textContent=`${{queued:'准备对比',running:`正在实测 ${next.phase?'B':'A'} 权重`,done:'两项实测已完成',cancelled:'已停止，保留已完成结果',error:'对比未完成'}[next.state]}${next.error?' · '+next.error:''}`;
    controls();if(replayStart==null)render();
  }
  async function start(){
    if(!rect)return;
    try{
      const response=await fetch('/api/speed/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scene:S.scene,versions:[$('#speed-a').value,$('#speed-b').value],rect})});
      const value=await response.json();if(!response.ok)throw Error(value.detail||response.statusText);
      following=true;update(value);Panels.showTab('speed');
    }catch(e){$('#speed-state').textContent='不能开始对比：'+e.message;}
  }
  function replay(){
    if(data?.state!=='done')return;
    cancelAnimationFrame(frame);const clock=$('#speed-clock').value;
    const end=Math.max(...data.items.map(i=>clock==='compute'?i.compute_ms:i.trace.at(-1).t_ms));
    if(!(end>0))return;
    replayStart=performance.now();
    function step(now){if(replayStart==null)return;const elapsed=now-replayStart;render(Math.min(elapsed,end));
      if(elapsed<end)frame=requestAnimationFrame(step);else replayStart=null;}
    frame=requestAnimationFrame(step);
  }
  async function history(){
    const response=await fetch('/api/speed'),value=await response.json(),el=$('#speed-history');el.replaceChildren();
    const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='选择已保存对比';el.append(placeholder);
    for(const h of value.history||[]){const o=document.createElement('option');o.value=h.id;o.textContent=`${h.created} · ${h.scene} · ${h.versions.join(' / ')} · ${h.state}`;el.append(o);}
  }
  $('#speed-history-refresh').onclick=()=>history().catch(e=>toast(e.message));
  $('#speed-history').onchange=async e=>{
    if(!e.target.value)return;const generation=++historyGeneration;
    try{const response=await fetch('/api/speed/history/'+e.target.value),value=await response.json();if(!response.ok)throw Error(value.detail);
      if(value.scene!==S.scene){toast('请先切到 '+value.scene+' 场景再打开该对比');return;}
      for(const item of value.items||[])if(S.runs[item.run_id])await loadRun(item.run_id);
      if(generation!==historyGeneration)return;hidden.delete(value.id);following=false;data=value;recordSelection(value);render();controls();$('#speed-state').textContent='已打开保存的实测对比';
    }catch(e){toast('对比历史不可用：'+e.message);}
  };
  $('#speed-start').onclick=start;
  $('#speed-stop').onclick=async()=>{await fetch('/api/speed/stop',{method:'POST'});$('#speed-state').textContent='正在停止对比，等待板卡确认';};
  $('#speed-use-roi').onclick=()=>{if(!S.rect)return toast('请先在地图上框选区域');rect=[...S.rect];scope();controls();};
  $('#speed-default-roi').onclick=configure;
  for(const id of ['speed-a','speed-b'])$('#'+id).onchange=()=>{controls();render();};
  $('#speed-focus').onclick=()=>{$('.layout').classList.toggle('speed-focus');MapView.resize();};
  $('#speed-replay').onclick=replay;$('#speed-clock').onchange=()=>{cancelAnimationFrame(frame);replayStart=null;render();};
  $('#speed-export').onclick=()=>{if(data)download('speed_'+data.id+'.json',JSON.stringify(data,null,2));};
  function clear(){const id=data?.id||S.speedComparison?.id;if(id)hidden.add(id);following=true;data=null;historyGeneration++;replayStart=null;cancelAnimationFrame(frame);render();controls();$('#speed-state').textContent='当前对比显示已清空；实测记录保留在对比历史';}
  return {configure,update,clear,history,render,busy,allowRun:s=>!s.origin?.startsWith('speed:')||!hidden.has(s.origin.slice(6))};
})();
