// Called by the existing offline browser harness; no devices or inference.
const path=require('node:path');
const flags={badAnalysis:false,slowAnalysis:false,badCompare:false,slowCompare:false,slowSave:false};
let ledger={scene:'longkou',shape:[550,400],revision:0,parcels:[],updated:null};
const posted=[];
const summary={source:'board',identity:{boot_id:'12345678',session:'0000002a',task:11,wcrc:'27231983',scene:'longkou',model:'v2'},
  received_pixels:2,total:3,coverage:2/3,complete_task_coverage:false,prediction_words_seen_sha256:'OFFLINE_FIXTURE',conf_thr:.6,min_px:1};
function reply(res,value,status=200){res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(value));}
function route(req,res){
  if(req.url.startsWith('/api/scene/longkou/annotations?')){
    const n=+new URL(req.url,'http://fixture').searchParams.get('count');
    reply(res,{scene:'longkou',count:n,points:Array.from({length:n},(_,i)=>[1,i]),inside_region:n});return true;
  }
  if(req.url==='/api/scene/longkou/parcels'){
    if(req.method==='GET'){reply(res,ledger);return true;}
    let raw='';req.on('data',d=>raw+=d);req.on('end',()=>{
      const body=JSON.parse(raw);posted.push({kind:'ledger',body});
      const save=()=>{
        if(body.revision!==ledger.revision){reply(res,{detail:'OFFLINE 台账版本冲突'},409);return;}
        ledger={...ledger,revision:ledger.revision+1,parcels:body.parcels,updated:'OFFLINE'};reply(res,ledger);
      };if(flags.slowSave)setTimeout(save,80);else save();
    });return true;
  }
  if(/^\/api\/run\/10[12]\/analysis\?/.test(req.url)){
    const bad=flags.badAnalysis,fn=()=>reply(res,bad?{detail:'OFFLINE analysis error'}:{...summary,
      patches:[{kind:'低置信',cls:1,area_px:1,area_m2:.214369,mean_conf:0,row:0,col:0,bbox:[0,0,0,0]}],sampling:[],area:[]},bad?409:200);
    if(flags.slowAnalysis)setTimeout(fn,120);else fn();return true;
  }
  if(req.url.startsWith('/api/compare?')){
    const bad=flags.badCompare,fn=()=>reply(res,bad?{detail:'OFFLINE compare error'}:{source:'board',common:1,changed:1,agree:0,
      labeled:1,acc_a:1,acc_b:0,complete_task_coverage:false,same_roi:true,evaluation:{available:true},
      a:summary,b:{...summary,identity:{...summary.identity,task:12}}},bad?409:200);
    if(flags.slowCompare)setTimeout(fn,120);else fn();return true;
  }
  if(req.url==='/api/run/101/report'){
    let raw='';req.on('data',d=>raw+=d);req.on('end',()=>{posted.push({kind:'report',body:JSON.parse(raw)});
      reply(res,{report:{scope:'OFFLINE_BROWSER_FIXTURE'},download:'/api/offline-report.txt'});});return true;
  }
  if(req.url==='/api/offline-report.txt'){res.writeHead(200,{'Content-Disposition':'attachment; filename="offline-report.txt"'});res.end('OFFLINE browser fixture, NOT a board report.');return true;}
  return false;
}
async function run(page,report,out){
  await page.evaluate(async()=>{
    S.runA=S.live=101;S.runB=null;S.rect=null;
    const make=(id,task,cells)=>{
      const b={boot_id:'12345678',session:'0000002a',task,wcrc:'27231983',scene:'longkou',model:'v2',ack:true,task_lifecycle:true,
        status:'stopped',error:null,integrity_error:false,roi:{x:0,y:0,width:3,height:1},total:3,received_pixels:cells.length,
        class_counts:Array(9).fill(0),interaction:{state:'closed'},cells:cells.map(([x,word])=>({x,y:0,class_word:word.toString(16).padStart(8,'0'),class_id:word&255,confidence_q16:word>>>16,confidence:(word>>>16)/65536}))};
      for(const c of b.cells)b.class_counts[c.class_id]++;
      S.runs[id]=newRun({id,scene:'longkou',version:'v2',source:'board',kind:'region',status:'stopped',total:3,done:cells.length,board:b});BoardPanel.apply(id,b);
    };
    make(101,11,[[0,0],[1,0x80000001]]);make(102,12,[[1,0x80000002],[2,0xffff0003]]);
    BoardPanel.gate({source:'board',task_lifecycle:true,active:false,authorized:false});
    await Panels.loadParcels();await Panels.setAB(101,null);Panels.showTab('agri');
    document.querySelector('#num-minpx').value='1';
  });
  report.checks.agri_mask_not_pred_sentinel=await page.evaluate(()=>{
    S.runs[101].pred[2]=9; // deliberately stale derived label, seen remains false
    const s=Panels.stats();return s.total===2&&s.cnt[1]===1&&s.cnt[2]===1&&s.cnt[9]===0;
  });
  await page.evaluate(()=>Panels.analyze());
  report.checks.agri_partial_snapshot_visible=(await page.locator('#patch-sub').innerText()).includes('部分覆盖')&&await page.locator('#tbl-patches tbody tr').count()===1;
  flags.badAnalysis=true;await page.evaluate(()=>Panels.analyze());
  report.checks.agri_failure_clears_old_snapshot=(await page.locator('#patch-sub').innerText()).includes('OFFLINE analysis error')&&await page.locator('#tbl-patches tbody tr').count()===0;
  flags.badAnalysis=false;flags.slowAnalysis=true;
  const pending=page.evaluate(()=>Panels.analyze());
  await page.waitForFunction(()=>document.querySelector('#patch-sub').textContent.includes('正在分析'));
  await page.evaluate(()=>Panels.setAB(102,null));await pending;flags.slowAnalysis=false;
  report.checks.agri_delayed_request_cannot_relabel_new_task=await page.evaluate(()=>S.runA===102&&S.lastAnalysis===null&&S.patches.length===0);
  await page.evaluate(async()=>{await Panels.setAB(101,null);Panels.addParcel([[0,0],[3,0],[3,1],[0,1]]);await Panels.saveParcels();});
  report.checks.parcel_persists_and_counts_seen=await page.evaluate(async()=>{
    await Panels.loadParcels();const p=Panels.parcelRows()[0];
    return S.parcels.length===1&&S.ledger.revision===1&&p.pixels===3&&p.received_pixels===2&&p.main_c===1&&p.mix===.5;
  });
  flags.slowSave=true;
  await page.evaluate(async()=>{S.parcels[0].name='修改一';Panels.parcelChanged();S.parcels[0].name='<script>修改二</script>';Panels.parcelChanged();await Panels.saveParcels();Panels.parcels();});
  flags.slowSave=false;
  report.checks.parcel_rapid_edits_are_serialized=ledger.revision===3&&ledger.parcels[0].name==='<script>修改二</script>';
  report.checks.parcel_name_is_text_not_html=await page.locator('#tbl-parcels script').count()===0&&(await page.locator('#tbl-parcels tbody').innerText()).includes('<script>修改二</script>');
  ledger={...ledger,revision:4,parcels:[{...ledger.parcels[0],name:'另一页面已保存'}]};
  await page.evaluate(async()=>{S.parcels[0].name='冲突草稿';Panels.parcelChanged();await Panels.saveParcels();});
  report.checks.parcel_conflict_preserves_remote_and_disables_report=ledger.parcels[0].name==='另一页面已保存'&&await page.locator('#btn-export').isDisabled()&&(await page.locator('#parcel-state').innerText()).includes('冲突');
  await page.evaluate(async()=>{await Panels.loadParcels();await Panels.setAB(101,102);Panels.showTab('runs');});
  report.checks.real_task_swipe_and_common_comparison=await page.locator('#swipe').isVisible()&&(await page.locator('#cmp-txt').innerText()).includes('公共像素 1')&&await page.evaluate(()=>S.runB===102&&S.comparison.acc_a===1&&S.comparison.acc_b===0);
  flags.badCompare=true;await page.evaluate(()=>Panels.setAB(101,102));
  report.checks.compare_error_clears_old_scores=(await page.locator('#cmp-txt').innerText()).includes('OFFLINE compare error')&&await page.evaluate(()=>S.comparison===null);
  flags.badCompare=false;flags.slowCompare=true;
  const comparing=page.evaluate(()=>Panels.setAB(101,102));
  await page.waitForFunction(()=>document.querySelector('#cmp-txt').textContent.includes('正在核对'));
  await page.evaluate(()=>Panels.setAB(102,null));await comparing;flags.slowCompare=false;
  report.checks.compare_old_response_ignored=await page.evaluate(()=>S.runA===102&&S.runB===null&&S.comparison===null&&document.querySelector('#cmp-txt').textContent==='');
  await page.evaluate(async()=>{await Panels.setAB(101,102);Panels.showTab('agri');});
  const downloaded=page.waitForEvent('download');await page.locator('#btn-export').click();await downloaded;
  const request=posted.find(v=>v.kind==='report');
  report.checks.report_uses_parameters_revision_and_selected_real_pair=request?.body.compare===102&&request.body.min_px===1&&request.body.conf_thr===.6&&request.body.ledger_revision===4;
  await page.evaluate(()=>Panels.analyze());await page.screenshot({path:path.join(out,'offline_agri.png')});
  await page.evaluate(()=>Panels.showTab('parcel'));await page.screenshot({path:path.join(out,'offline_parcels.png')});
  report.checks.clear_map_preserves_history_and_persistent_ledger=await page.evaluate(async()=>{
    document.querySelector('#btn-clear-map').click();await Promise.resolve();
    return S.runA===null&&S.runB===null&&S.patches.length===0&&S.parcels.length===1&&S.runs[101].seen[0]===1;
  });
  await page.evaluate(async()=>{await Panels.setAB(101,102);Panels.showTab('runs');});
  await page.screenshot({path:path.join(out,'offline_compare.png')});
  report.checks.loop_failure_is_not_completed_step=await page.evaluate(()=>{
    const r=S.runs[101].s,rect=[0,0,1,3];S.loop={};
    S.loopWait={step:'run_old',scene:'longkou',version:'v2',rect,rid:null};
    Loop.onRunStart({...r,rect});Loop.onRunEnd({...r,rect,status:'error',done:2,total:3});
    return !S.loop.run_old&&S.loopWait===null;
  });
  await page.evaluate(async()=>{
    S.info.closed_loop={region:{hold_class:3,region:{row0:0,col0:0,size:64}},ann30:{points:[],inside_region:0}};
    S.loopOld=101;S.loopNew=102;Panels.showTab('loop');await Loop.table();
  });
  report.checks.loop_reads_real_task_comparison_only=(await page.locator('#tbl-loop tbody').innerText()).includes('100.00%')&&
    (await page.locator('#loop-compare-state').innerText()).includes('部分覆盖');
  report.checks.loop_model_steps_stay_gated=await page.locator('[data-act="run_old"]').isDisabled()&&
    await page.locator('[data-act="upload"]').isDisabled()&&await page.locator('[data-act="run_new"]').isDisabled();
  await page.evaluate(()=>{S.ws={readyState:1,send:value=>window.loopCommand=JSON.parse(value)};});
  await page.locator('#loop-annotate').fill('25');await page.locator('#loop-annotate').dispatchEvent('change');
  await page.locator('[data-act="finetune"]').click();
  report.checks.loop_parameters_match_registered_recipe=await page.evaluate(()=>loopCommand.scene==='longkou'&&loopCommand.annotate===25&&loopCommand.base_version==='hold3'&&JSON.stringify(loopCommand.rect)==='[0,0,64,64]');
  await page.locator('[data-act="annotate"]').click();await page.waitForFunction(()=>S.annotations.length===25);
  report.checks.loop_annotation_count_not_fixed_thirty=true;
  flags.badCompare=true;await page.evaluate(()=>Loop.table());flags.badCompare=false;
  report.checks.loop_failed_compare_clears_scores=await page.locator('#tbl-loop tbody tr').count()===0&&(await page.locator('#loop-compare-state').innerText()).includes('OFFLINE compare error');
}
module.exports={route,run};
