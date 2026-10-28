// Offline multi-scene/model UI fixtures, used by the existing browser harness.
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve('gcs');let slowHonghu=false,timingMode='ok';
const timingFixture={available:true,pure_pl_available:false,internal_ps_pl_split_available:false,
  identity:{boot_id:'12345678',session:'0000002a',task:31,scene:'hanchuan',model:'demo',wcrc:'12345678'},
  elapsed_us:10000,accounted_us:6000,other_us:4000,wait_service:{calls:1,us:250},
  phases:['setup','step','probe','results','display','rows','pump','model','control'].map((part,i)=>({part,label:part,calls:1,us:[300,5000,200,60,150,80,120,50,40][i]})),
  scope:'OFFLINE_SYNTHETIC_APP_PHASE_TIMING_NOT_REAL_BOARD_MEASUREMENT'};
function reply(res,value){res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(value));}
function route(req,res){
  if(req.url==='/api/run/77/timing'){
    const mode=timingMode;
    const data=mode==='bad'?{...timingFixture,identity:{...timingFixture.identity,wcrc:'deadbeef'}}:
      mode==='missing'?{available:false,reason:'OFFLINE missing UART timing'}:timingFixture;
    if(mode==='slow')setTimeout(()=>reply(res,data),100);else reply(res,data);return true;
  }
  const match=/^\/api\/scene\/(longkou|honghu|hanchuan)(?:\/(gt|split|rgb|parcels))?$/.exec(req.url);
  if(match){
    const scene=match[1],part=match[2],palette=JSON.parse(fs.readFileSync(path.join(root,'scenes',scene,'palette.json')));
    if(!part){
      const info={H:palette.height,W:palette.width,bands:270,classes:palette.classes.slice(1),palette:palette.colors,
        mission:{gsd_m:.05,site:'OFFLINE FIXTURE',weather:'未测',date:'fixture',platform:'fixture',sensor:'fixture',altitude_m:0},
        versions:[{id:'v1',label:'fixture candidate',pkg:'demo',pkg_bytes:1000000,deployable:true},
                  {id:'missing',label:'fixture unavailable',pkg:'missing',pkg_bytes:null,deployable:false}],closed_loop:null};
      if(scene==='honghu'&&slowHonghu)setTimeout(()=>reply(res,info),80);else reply(res,info);return true;
    }
    if(part==='gt'||part==='split'){res.end(Buffer.alloc(palette.height*palette.width));return true;}
    if(part==='rgb'){res.writeHead(200,{'Content-Type':'image/png'});res.end(fs.readFileSync(path.join(root,'scenes',scene,'rgb.png')));return true;}
    reply(res,{scene,shape:[palette.height,palette.width],revision:0,parcels:[]});return true;
  }
  if(req.url==='/api/board/models/query'||req.url==='/api/board/models/activate'){
    res.writeHead(409,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:'OFFLINE model receipt not available'}));return true;
  }
  return false;
}
async function run(page,report,out){
  await page.evaluate(async()=>{
    S.live=null;S.runA=null;S.runB=null;S.kind='scan';S.ws={readyState:1,send:data=>(window.modelFixtureSent||=[]).push(JSON.parse(data))};
    $('#sel-scene').innerHTML=['longkou','honghu','hanchuan'].map(scene=>`<option value="${scene}">${scene}</option>`).join('');
    await BoardPanel.source({source:'board',task_lifecycle:true,active:true,authorized:true,capabilities:{models:true},registry:[]});
    Panels.showTab('link');
  });
  await page.selectOption('#sel-scene','honghu');
  await page.waitForFunction(()=>S.scene==='honghu'&&S.H===940&&S.W===475);
  report.checks.models_three_scene_selection=await page.evaluate(()=>!$('#sel-scene').disabled&&S.info.classes.length===22&&clsName(22)==='Tree'&&clsName(1)==='Red roof');
  report.checks.models_scene_change_clears_old_swipe=await page.evaluate(()=>S.runA===null&&S.runB===null&&$('#swipe').hidden&&$('#swipe-a').textContent==='A');
  report.checks.models_missing_package_disabled=await page.locator('#sel-upload option[value="missing"]').isDisabled();
  await page.locator('#btn-model-query').click();await page.waitForFunction(()=>$('#model-state').textContent.includes('OFFLINE model'));
  report.checks.models_query_explicit_failure=await page.evaluate(()=>!window.modelFixtureSent?.length&&$('#model-state').textContent.includes('未确认'));
  await page.locator('#btn-upload').click();
  report.checks.models_upload_activation_explicit=await page.evaluate(()=>{
    const sent=window.modelFixtureSent;return sent.length===1&&sent[0].cmd==='upload'&&sent[0].activate===true&&sent[0].scene==='honghu';
  });
  await page.screenshot({path:path.join(out,'offline_models_controls.png')});
  report.checks.models_no_false_activation=await page.evaluate(()=>{
    S.version='v1';Panels.upload({type:'upload_end',action:'upload',scene:'honghu',version:'missing',ok:true,persisted:true,activated:false,bytes:100});
    return S.version==='v1'&&$('#upload-txt').textContent.includes('未激活');
  });
  await page.evaluate(()=>loadScene('hanchuan'));
  report.checks.models_hanchuan_contract=await page.evaluate(()=>S.H===1217&&S.W===303&&S.info.classes.length===16&&clsName(16)==='Water');
  slowHonghu=true;await page.evaluate(async()=>{const older=loadScene('honghu');const newer=loadScene('hanchuan');await Promise.all([older,newer]);});slowHonghu=false;
  report.checks.models_scene_async_not_mixed=await page.evaluate(()=>S.scene==='hanchuan'&&S.H===1217&&S.W===303&&S.gt.length===1217*303&&S.info.classes.length===16);
  await page.evaluate(async()=>{
    const b={model_lifecycle:true,task_lifecycle:true,boot_id:'12345678',session:'0000002a',task:31,start_seq:5,scene:'hanchuan',model:'demo',wcrc:'12345678',shape:[1217,303],classes:16,kind:1,
      total:1,received_pixels:1,roi:{x:302,y:1216,width:1,height:1},status:'done',ack:true,error:null,
      class_counts:Array.from({length:16},(_,i)=>i===15?1:0),cells:[{x:302,y:1216,class_word:'FFFF000F',class_id:15,confidence_q16:65535,confidence:65535/65536}],interaction:{state:'open'}};
    const summary={id:77,source:'board',scene:'hanchuan',version:'v1',kind:'region',total:1,done:1,status:'done',board:b};
    S.runs[77]=newRun(summary);S.runA=S.live=77;MapView.resetScene();BoardPanel.apply(77,b);MapView.repaintAll();Panels.showTab('probe');
  });
  report.checks.models_raw_edge_class_not_longkou=await page.evaluate(()=>{
    const r=S.runs[77],i=1216*303+302;return r.words[i]===0xffff000f&&r.seen[i]===1&&r.pred[i]===16&&$('#board-shape').textContent.includes('hanchuan / demo');
  });
  report.checks.models_old_result_not_current_selection=await page.evaluate(()=>{
    Panels.upload({type:'upload_end',action:'activate',source:'board',scene:'hanchuan',version:'v1',ok:true,activated:true,bytes:0});
    return S.runs[77].s.board.wcrc==='12345678'&&S.runs[77].s.board.model==='demo';
  });
  await page.evaluate(()=>{Panels.showTab('link');$('#board-records').open=true;$('#task-timing-details').open=true;});
  await page.locator('#task-timing-read').click();await page.waitForFunction(()=>$('#task-timing-table tbody').children.length===9);
  report.checks.timing_private_phases_not_pure_pl=await page.evaluate(()=>$('#task-timing-state').textContent.includes('PS内部与纯PL：仍未独立测量')&&
    $('#task-timing-table tbody').children.length===9&&$('#task-timing-state').textContent.includes('不相加'));
  const waitDownload=page.waitForEvent('download');await page.locator('#task-timing-export').click();const downloaded=await waitDownload;
  await downloaded.saveAs(path.join(out,'offline_phase_timing.json'));
  report.checks.timing_export_matches_receipt=JSON.stringify(JSON.parse(fs.readFileSync(path.join(out,'offline_phase_timing.json'))))===JSON.stringify(timingFixture);
  await page.screenshot({path:path.join(out,'offline_phase_timing.png')});
  const reportPath=path.resolve(out,'../phase_report/preview.html');
  if(fs.existsSync(reportPath)){
    const context=await page.context().browser().newContext({viewport:{width:1440,height:1024}});
    const preview=await context.newPage();
    try{
      await preview.setContent(fs.readFileSync(reportPath,'utf8'));
      report.checks.phase_report_visible_and_explicit=await preview.locator('body').evaluate(el=>{
        const title=[...el.querySelectorAll('h2')].find(h=>h.textContent.includes('任务分项耗时'));
        return el.textContent.includes('OFFLINE SYNTHETIC FIXTURE')&&title?.nextElementSibling?.querySelectorAll('tbody tr').length===9&&el.textContent.includes('PS数值准备与纯PL内部尚未独立测量');
      });
      report.checks.phase_report_no_horizontal_overflow=await preview.locator('body').evaluate(el=>el.scrollWidth<=window.innerWidth);
      await preview.screenshot({path:path.join(out,'offline_phase_report.png'),fullPage:true});
    }finally{await context.close();}
  }
  timingMode='bad';await page.evaluate(()=>TimingPanel.read());
  report.checks.timing_wrong_model_clears_previous=await page.evaluate(()=>$('#task-timing-table tbody').children.length===0&&$('#task-timing-export').disabled&&$('#task-timing-state').textContent.includes('身份'));
  timingMode='missing';await page.evaluate(()=>TimingPanel.read());
  report.checks.timing_missing_no_receive_time_fallback=await page.evaluate(()=>$('#task-timing-table tbody').children.length===0&&$('#task-timing-state').textContent.includes('OFFLINE missing UART'));
  timingMode='slow';await page.evaluate(async()=>{const old=TimingPanel.read();TimingPanel.select(78,{...S.runs[77].s.board,task:32});await old;});
  report.checks.timing_delayed_response_cannot_relabel_task=await page.evaluate(()=>$('#task-timing-table tbody').children.length===0&&$('#task-timing-export').disabled);
  timingMode='ok';await page.evaluate(()=>{TimingPanel.select(77,S.runs[77].s.board);$('#task-timing-details').open=false;Panels.showTab('probe');});
  report.checks.models_identity_conflict_preserves_words=await page.evaluate(()=>{
    const r=S.runs[77];BoardPanel.apply(77,{...r.s.board,wcrc:'12345679'});
    return r.words[1216*303+302]===0xffff000f&&r.s.board.wcrc==='12345678'&&r.s.board.integrity_error===true;
  });
  await page.screenshot({path:path.join(out,'offline_models_hanchuan.png')});
  report.checks.models_pc_map_not_dp_overlay=await page.locator('#board-class-map,#board-class-summary,.map-wrap #board-roi').count()===0;
}
module.exports={route,run};
