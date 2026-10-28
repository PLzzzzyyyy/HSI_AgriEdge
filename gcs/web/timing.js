'use strict';
// Actual board timing records. Never sends a model/task command or invents
// internal PS/PL latency from the end-to-end receive rate.
const TimingPanel=(()=>{
  let generation=0,selected=null,last=null;
  const keys=['boot_id','session','task','scene','model','wcrc'];
  const key=(rid,b)=>b?JSON.stringify([rid,...keys.map(k=>b[k])]):null;
  function clear(message='未测；读取本任务已保存的板端计时记录。'){
    generation++;last=null;$('#task-timing-table tbody').replaceChildren();$('#task-timing-export').disabled=true;
    $('#task-timing-state').textContent=message;
  }
  function select(rid,board){
    const next=key(rid,board);
    if(!selected||selected.key!==next){clear();selected=next?{rid,board,key:next}:null;}
    else selected.board=board;
    const ready=board?.model_lifecycle&&['done','stopped'].includes(board.status)&&!board.error&&!board.integrity_error;
    $('#task-timing-read').disabled=!ready;
    if(!ready)clear(board?.error?'任务有错误，不显示分项为完整测量。':'任务未结束或没有新版计时记录。');
  }
  async function read(){
    if(!selected)return;
    const currentSelection=selected;clear('正在核验板端计时；仅在原连接显式回读记录，不启动任务……');const token=generation;
    const current=()=>token===generation&&selected===currentSelection;
    try{
      if(selected.board?.board_log?.required){
        const refresh=await fetch(`/api/run/${selected.rid}/board/records`,{method:'POST'}),receipt=await refresh.json();if(!current())return;
        if(!refresh.ok)throw Error(receipt.detail||refresh.statusText);
      }
      const response=await fetch(`/api/run/${selected.rid}/timing`),data=await response.json();if(!current())return;
      if(!response.ok)throw Error(data.detail||response.statusText);
      if(!data.available){$('#task-timing-state').textContent=`未测或不可用：${data.reason||'记录不完整'}`;return;}
      if(keys.some(k=>data.identity?.[k]!==selected.board[k])||typeof data.pure_pl_available!=='boolean'||typeof data.internal_ps_pl_split_available!=='boolean')throw Error('分项任务身份或计时口径不符');
      const phases=data.phases;
      if(!Array.isArray(phases)||phases.length!==9||phases.some(p=>!Number.isSafeInteger(p.us)||p.us<0||!Number.isSafeInteger(p.calls)||p.calls<0))throw Error('计时分项格式错误');
      if(phases.reduce((sum,p)=>sum+p.us,0)!==data.accounted_us||data.accounted_us+data.other_us!==data.elapsed_us)throw Error('计时分项合计不符');
      const body=$('#task-timing-table tbody');body.replaceChildren();
      for(const p of phases){const tr=document.createElement('tr');for(const value of [p.label,fmt.n(p.calls),fmt.f(p.us/1000,3)]){const td=document.createElement('td');td.textContent=value;tr.append(td);}body.append(tr);}
      $('#task-timing-state').textContent=`任务 #${data.identity.task} · 已分项 ${fmt.f(data.accounted_us/1000,3)} ms；其他（含暂停/日志等）${fmt.f(data.other_us/1000,3)} ms。等待服务子集 ${fmt.f(data.wait_service.us/1000,3)} ms 已含在分项中，不相加。PS内部与纯PL：仍未独立测量。`;
      const detail=data.internal_timing;
      if(detail?.available){
        const engine=detail.engine;
        if(!data.internal_ps_pl_split_available||!Array.isArray(detail.phases)||detail.phases.length!==8||engine?.hz!==199998000||!Number.isSafeInteger(engine.cycles)||!Number.isSafeInteger(engine.pixels))throw Error('内部计时/PL契约不符');
        for(const p of detail.phases){
          if(!Number.isSafeInteger(p.us)||p.us<0||!Number.isSafeInteger(p.calls)||p.calls<0)throw Error('内部计时格式错误');
          const tr=document.createElement('tr');for(const v of [`step 内部 · ${p.label}`,fmt.n(p.calls),fmt.f(p.us/1000,3)]){const td=document.createElement('td');td.textContent=v;tr.append(td);}body.append(tr);
        }
        $('#task-timing-state').textContent=`任务 #${data.identity.task} · App计时 ${fmt.f(data.elapsed_us/1000,3)} ms；内部细分属于step子集，不与上表重复相加。PL ${fmt.n(engine.cycles)} 周期 / ${engine.hz/1e6} MHz，${engine.pixels?fmt.f(engine.ms_per_pixel,6)+' ms/像素（批均值）':'无完成样本'}；含PL侧AXI等待，不含PS。driver等待服务 ${fmt.f(detail.wait_service.us/1000,3)} ms 已含在wait中；PL周期也不能再加到wait墙钟。`;
      }else if(data.pure_pl_available||data.internal_ps_pl_split_available)throw Error('缺内部原始记录，不能显示PS/PL数值');
      last=data;$('#task-timing-export').disabled=false;
    }catch(e){if(current())clear(`计时不可用：${e.message}；不显示旧记录。`);}
  }
  $('#task-timing-read').onclick=read;
  $('#task-timing-export').onclick=()=>{if(last&&selected)download(`timing_${last.identity.boot_id}_${last.identity.task}.json`,JSON.stringify(last,null,2));};
  return {select,clear,read};
})();
