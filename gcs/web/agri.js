'use strict';
// Board-only business snapshots and persistent, revisioned manual parcel geometry.
Object.assign(Panels, (() => {
  const P = Panels, X = {}, esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let analysisGeneration = 0, analysisAbort = null, ledgerGeneration = 0, exporting = false;
  let dpSelected=null;
  async function selectDP(id) {
    if(!await flushLedger())return toast('请先保存有效地块');
    try{
      const answer=await jsonRequest('/api/dp/selection',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:S.runA,parcel_id:id,revision:S.ledger.revision,threshold:params().conf_thr})});
      if(answer.status.state==='error')throw Error(answer.status.error);
      dpSelected=id;$('#dp-parcel-state').textContent='已提交，等待板卡显示确认';
    }catch(e){$('#dp-parcel-state').textContent=`DP 未同步：${e.message}`;}
  }
  $('#btn-dp-task').onclick=()=>selectDP(null);
  const params = () => ({conf_thr: +$('#rng-conf').value / 100, min_px: +$('#num-minpx').value});
  const usable = r => r?.s.source === 'board' && r.loaded && !r.s.board?.error && !r.s.board?.integrity_error &&
    ['running','paused','stopped','done'].includes(r.s.status) && (r.s.board?.ack || r.s.board?.accepted_via_info);
  async function jsonRequest(url, options) {
    const response = await fetch(url, options), value = await response.json();
    if (!response.ok) throw Error(value.detail || response.statusText);
    return value;
  }
  function controls() {
    const l = S.ledger;
    $('#btn-export').disabled = exporting || !usable(S.runs[S.runA]) || !l || l.loading || l.dirty || !!l.error;
    $('#btn-analyze').disabled = !usable(S.runs[S.runA]);
    $('#btn-parcel-clear').disabled = !l || l.loading || !!l.error || !S.parcels.length;
    $('#parcel-state').textContent = !l || l.loading ? '台账加载中…' : l.error ? `台账未保存：${l.error}` : l.saving || l.dirty ? '台账保存中…' : `台账已保存 · 版本 ${l.revision}`;
  }
  X.businessControls = controls;
  X.clearBusiness = () => {
    analysisGeneration++; analysisAbort?.abort(); S.lastAnalysis = null;
    S.patches = []; S.sampling = []; S.hilite = null;
    $('#tbl-patches tbody').innerHTML = ''; $('#tbl-sampling tbody').innerHTML = ''; $('#patch-sub').textContent = '';
    $('#report-state').textContent = '';
    controls();
  };
  X.analyze = async () => {
    X.clearBusiness(); const rid = S.runA, scene = S.scene, r = S.runs[rid], p = params();
    if (!usable(r)) { $('#patch-sub').textContent = '当前任务未确认、未收到结果或有错误，不能生成成功分析'; return false; }
    const generation = analysisGeneration, controller = new AbortController(); analysisAbort = controller;
    const current = () => generation === analysisGeneration && scene === S.scene && rid === S.runA;
    $('#patch-sub').textContent = '正在分析已接收像素…';
    try {
      const a = await jsonRequest(`/api/run/${rid}/analysis?conf_thr=${p.conf_thr}&min_px=${p.min_px}`, {signal:controller.signal});
      if (!current()) return false;
      S.lastAnalysis = a; S.patches = a.patches; S.sampling = a.sampling;
      const nl = a.patches.filter(v => v.kind === '低置信').length;
      $('#patch-sub').textContent = `快照 ${fmt.n(a.received_pixels)} / ${fmt.n(a.total)} 像素 · ${a.complete_task_coverage ? '任务完整覆盖' : '部分覆盖'} · 低置信 ${nl} / 碎斑 ${a.patches.length-nl}`;
      $('#patch-sub').title = `阈值 ${a.conf_thr}；最小 ${a.min_px} 像素；CLASS+seen SHA256 ${a.prediction_words_seen_sha256}`;
      $('#tbl-patches tbody').innerHTML = a.patches.map((v,k) => `<tr data-k="${k}"><td>${k+1}</td><td><span class="tag ${v.kind === '低置信' ? 'low':'frag'}">${esc(v.kind)}</span></td><td>${esc(clsName(v.cls))}</td><td class="num">${fmt.f(v.area_m2,1)}</td><td class="num">${fmt.n(v.area_px)}</td><td class="num">${fmt.f(v.mean_conf,3)}</td><td class="mono">${v.row}, ${v.col}</td></tr>`).join('');
      $$('#tbl-patches [data-k]').forEach(tr => tr.onclick = () => { const k = +tr.dataset.k, v = S.patches[k]; S.hilite=k; MapView.flyTo(v.row,v.col,Math.max(S.view.k,6)); });
      $('#tbl-sampling tbody').innerHTML = a.sampling.map((v,k) => `<tr data-k="${k}"><td>S${k+1}</td><td class="mono">${v.row}, ${v.col}</td><td class="mono">${fmt.f(v.col*S.gsd,1)}, ${fmt.f(v.row*S.gsd,1)}</td><td class="num">${fmt.f(v.mean_conf,3)}</td></tr>`).join('');
      $$('#tbl-sampling [data-k]').forEach(tr => tr.onclick = () => { const v=S.sampling[+tr.dataset.k]; MapView.flyTo(v.row,v.col,Math.max(S.view.k,5)); });
      MapView.dirty(); return true;
    } catch (e) {
      if (current() && e.name !== 'AbortError') $('#patch-sub').textContent = `分析不可用：${e.message}；不保留旧分析`;
      return false;
    }
  };
  $('#btn-analyze').onclick = X.analyze;
  $('#rng-conf').oninput = e => { $('#txt-conf').textContent = (+e.target.value/100).toFixed(2); X.clearBusiness(); X.parcels(); MapView.dirty(); };
  $('#rng-conf').onchange=()=>{if(dpSelected)selectDP(dpSelected);};
  $('#num-minpx').onchange = () => { X.clearBusiness(); MapView.dirty(); };

  X.loadParcels = async (scene = S.scene) => {
    const generation = ++ledgerGeneration;
    const l = {scene, revision:0, dirty:false, loading:true, saving:false, error:null, edit:0}; S.ledger=l; S.parcels=[]; controls();
    try {
      const doc = await jsonRequest(`/api/scene/${scene}/parcels`);
      if (generation !== ledgerGeneration || scene !== S.scene) return;
      if (doc.scene !== scene || doc.shape[0] !== S.H || doc.shape[1] !== S.W) throw Error('台账场景/尺寸不匹配');
      l.revision=doc.revision; S.parcels=doc.parcels;
    } catch (e) { if (S.ledger===l) l.error=e.message; }
    finally { if (S.ledger===l) { l.loading=false; X.parcels(); MapView.dirty(); } }
  };
  async function flushLedger() {
    const l=S.ledger;
    if (!l || l.loading || l.error) return false;
    if (l.promise) return l.promise;
    if (!l.dirty) return true;
    l.promise=(async () => {
      while (l.dirty && !l.error && S.ledger===l) {
        const edit=l.edit, body=JSON.stringify({revision:l.revision,parcels:S.parcels}); l.saving=true; controls();
        try {
          const doc=await jsonRequest(`/api/scene/${l.scene}/parcels`, {method:'PUT',headers:{'Content-Type':'application/json'},body});
          l.revision=doc.revision; l.dirty=edit!==l.edit;
        } catch(e) { l.error=e.message; logLine(`台账未保存：${e.message}`,'error'); }
      }
      l.saving=false; l.promise=null; if(S.ledger===l)controls(); return !l.dirty && !l.error;
    })();
    return l.promise;
  }
  X.saveParcels = flushLedger;
  X.parcelChanged = () => {
    const l=S.ledger;
    if (!l || l.loading || l.error) { toast('请先加载有效台账，不能覆盖错误/冲突记录'); return; }
    for (const p of S.parcels) p.id ||= crypto.randomUUID();
    l.edit++; l.dirty=true; X.parcels(); MapView.dirty(); flushLedger();
  };
  X.addParcel = pts => {
    const l=S.ledger;
    if (!l || l.loading || l.error) return toast('台账尚未就绪；请在地块页重新加载');
    S.parcels.push({id:crypto.randomUUID(),name:`地块 ${S.parcels.length+1}`,pts}); X.parcelChanged();
  };
  $('#btn-parcel-reload').onclick = () => {
    if(S.ledger?.saving)return toast('请等待正在保存的台账请求结束');
    if(S.ledger?.dirty && !confirm('重新加载会放弃当前未保存的地块草稿，继续？'))return;
    X.loadParcels();
  };
  $('#btn-parcel-clear').onclick = () => { S.parcels=[]; X.parcelChanged(); };
  function inPoly(x,y,pts) {
    let yes=false;
    for(let i=0,j=pts.length-1;i<pts.length;j=i++){
      const [xi,yi]=pts[i],[xj,yj]=pts[j];
      if((yi>y)!==(yj>y) && x<(xj-xi)*(y-yi)/(yj-yi)+xi)yes=!yes;
    }
    return yes;
  }
  X.parcelRows = () => {
    const r=S.runs[S.runA], valid=usable(r), thr=params().conf_thr;
    return S.parcels.map(p => {
      const xs=p.pts.map(v=>v[0]),ys=p.pts.map(v=>v[1]), counts=Array(S.info.classes.length+1).fill(0);
      let n=0,done=0,low=0;
      for(let y=Math.max(0,Math.floor(Math.min(...ys)));y<Math.min(S.H,Math.ceil(Math.max(...ys)));y++)
        for(let x=Math.max(0,Math.floor(Math.min(...xs)));x<Math.min(S.W,Math.ceil(Math.max(...xs)));x++){
          if(!inPoly(x+.5,y+.5,p.pts))continue; n++;
          const i=y*S.W+x;
          if(valid && r.seen?.[i]) { const c=(r.words[i]&255)+1;counts[c]++;done++;if((r.words[i]>>>16)/65536<thr)low++; }
        }
      const main=counts.indexOf(Math.max(...counts)),share=done?counts[main]/done:null;
      return {id:p.id,name:p.name,pixels:n,area_m2:n*S.gsd*S.gsd,received_pixels:done,done:n?done/n:0,
        main:done?clsName(main):null,main_c:done?main:0,main_share:share,mix:done?1-share:null,low:done?low/done:null};
    });
  };
  X.parcels = () => {
    controls();
    if (document.activeElement?.matches('#tbl-parcels [contenteditable]')) return;
    const rows=X.parcelRows();
    $('#tbl-parcels tbody').innerHTML=rows.map((p,k)=>`<tr><td contenteditable="${S.ledger?.error?'false':'true'}" data-name="${k}">${esc(p.name)}</td><td class="num">${fmt.f(p.area_m2,1)}</td><td class="num">${fmt.pct(p.done,1)}</td><td>${esc(p.main)||'—'}</td><td class="num">${fmt.pct(p.main_share)}</td><td class="num">${fmt.pct(p.mix)}</td><td class="num">${fmt.pct(p.low)}</td><td><button class="btn" data-del="${k}" ${S.ledger?.error?'disabled':''}>删除</button></td></tr>`).join('') || '<tr><td colspan="8" class="note">还没有地块；手工边界按场景保存，与真值无关</td></tr>';
    $$('#tbl-parcels [data-del]').forEach(b=>{
      const show=document.createElement('button');show.className='btn';show.textContent='显示到 DP';show.onclick=()=>selectDP(S.parcels[+b.dataset.del].id);b.before(show);
      b.onclick=()=>{S.parcels.splice(+b.dataset.del,1);X.parcelChanged();};
    });
    $$('#tbl-parcels [data-name]').forEach(td=>td.onblur=()=>{const p=S.parcels[+td.dataset.name],name=td.textContent.trim()||'地块';if(p&&p.name!==name){p.name=name;X.parcelChanged();}});
  };

  X.exportReport = async () => {
    const rid=S.runA,scene=S.scene;
    if(exporting || !usable(S.runs[rid]))return toast('请选择无错误的真实板卡任务');
    if(!await flushLedger() || S.ledger?.dirty || S.ledger?.error)return toast('台账未保存或加载失败，不能导出旧台账');
    if(rid!==S.runA || scene!==S.scene)return;
    exporting=true;controls();$('#report-state').textContent='正在核对结果并生成报告包…';
    try {
      const res=await jsonRequest(`/api/run/${rid}/report`,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({...params(),ledger_revision:S.ledger.revision,compare:S.runB})});
      if(rid!==S.runA || scene!==S.scene)return;
      const link=document.createElement('a');link.href=res.download;link.download='';link.click();
      $('#report-state').textContent='报告包已生成：含可打印HTML、分类图、统计/台账、评测/对比及原始字和掩码';
    } catch(e) { if(rid===S.runA && scene===S.scene)$('#report-state').textContent=`报告失败：${e.message}`; }
    finally {exporting=false;controls();}
  };
  $('#btn-export').onclick=X.exportReport;
  return X;
})());
