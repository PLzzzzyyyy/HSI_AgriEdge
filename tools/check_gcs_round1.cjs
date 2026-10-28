// Additional browser-only ABI4 fixtures. No production endpoint or inference.
const path=require('node:path');
async function run(page,report,out){
  await page.evaluate(async()=>{
    const old=S.runs[77].s.board;
    const b={...old,task:32,error:null,integrity_error:false,status:'done',interaction:{state:'open',probe:null}};
    S.runs[78]=newRun({id:78,source:'board',scene:'hanchuan',version:'v1',kind:'region',total:1,done:1,status:'done',board:b});
    S.runA=S.live=78;BoardPanel.gate({source:'board',task_lifecycle:true,active:true,authorized:true,capabilities:{models:true}});
    BoardPanel.apply(78,b);await BoardPanel.probe(1216,302);
    const p={state:'done',row:1216,col:302,req_seq:2,class_word:'FFFF000F',class_id:15,confidence_q16:65535,
      logits_q16:Array.from({length:16},(_,i)=>i===15?65536:0),probabilities:Array.from({length:16},(_,i)=>i===15?1:0),
      identity:{scene:'hanchuan',model:'demo',wcrc:'12345678',classes:16},attention_shape:[12,6,6],attention_crc32:'12345678',
      attention_q24:Array.from({length:432},(_,i)=>i%6===(Math.floor(i/36)+Math.floor(i/6)%6)%6?16777216:0)};
    window.round1FixtureProbe=structuredClone(p);b.interaction.probe=p;BoardPanel.apply(78,b);
    const banner=document.createElement('div');banner.id='offline-round1-banner';banner.textContent='OFFLINE SYNTHETIC FIXTURE — NOT BOARD / SD / TIMING ACCEPTANCE';
    Object.assign(banner.style,{position:'fixed',top:'0',left:'400px',zIndex:'9999',background:'#541b25',color:'white',fontSize:'12px',padding:'4px'});document.body.append(banner);
  });
  report.checks.attention_raw_q24_scale_only=await page.evaluate(()=>S.probe.attn?.length===12&&S.probe.attn[0][0][0]===1&&!$('#rng-layer').disabled&&$('#board-probe-state').textContent.includes('Q0.24'));
  await page.locator('#rng-layer').evaluate(e=>{e.value='12';e.dispatchEvent(new Event('input'));});
  report.checks.attention_all_layers_existing_chart=await page.evaluate(()=>$('#txt-layer').textContent==='12'&&Panels.charts['chart-attn'].getOption().series[0].data.some(v=>v[0]===5&&v[1]===0&&v[2]===1));
  await page.screenshot({path:path.join(out,'offline_attention_layout.png')});
  await page.evaluate(()=>{const b=structuredClone(S.runs[78].s.board);b.interaction.probe.state='error';b.interaction.probe.error='OFFLINE lost fragment';BoardPanel.apply(78,b);});
  report.checks.attention_error_clears_old_tensor=await page.evaluate(()=>!S.probe.attn&&$('#rng-layer').disabled&&!Panels.charts['chart-attn'].getOption().series?.length);
  await page.evaluate(()=>{const b=structuredClone(S.runs[78].s.board);b.interaction.probe=structuredClone(window.round1FixtureProbe);b.interaction.probe.attention_q24.pop();BoardPanel.apply(78,b);});
  report.checks.attention_partial_not_full=await page.evaluate(()=>!S.probe.attn&&$('#board-probe-state').textContent.includes('不完整'));
  await page.route('**/api/run/78/board/probe',r=>r.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'OFFLINE attention rejected'})}));
  await page.locator('#board-probe-run').click();await page.waitForFunction(()=>$('#board-probe-state').textContent.includes('OFFLINE attention rejected'));
  await page.evaluate(()=>{const b=structuredClone(S.runs[78].s.board);b.interaction.probe=structuredClone(window.round1FixtureProbe);BoardPanel.apply(78,b);});
  report.checks.attention_failed_post_cannot_resurrect_old_result=await page.evaluate(()=>!S.probe.attn&&$('#rng-layer').disabled);
  await page.unroute('**/api/run/78/board/probe');
  const identity=await page.evaluate(()=>Object.fromEntries(['boot_id','session','task','scene','model','wcrc'].map(k=>[k,S.runs[78].s.board[k]])));
  const names=['setup','step','probe','results','display','rows','pump','model','control'];
  const phases=names.map((part,i)=>({part,label:part,calls:1,us:i===0?10:i===1?1000:0}));
  const parts=['validate','extract','normalize','embed','cache_prepare','submit','wait','cache_complete'];
  const detail={available:true,phases:parts.map((part,i)=>({part,label:part,calls:[3,1,1,1,1,2,1,1][i],us:[5,20,20,30,5,10,800,5][i]})),
    wait_service:{us:200,calls:1},other_step_us:105,engine:{cycles:100000,hz:199998000,calls:1,pixels:1,ms_per_pixel:100000*1000/199998000}};
  let bad=false;
  await page.route('**/api/run/78/timing',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({available:true,identity,phases,
    pure_pl_available:true,internal_ps_pl_split_available:true,accounted_us:1010,elapsed_us:1200,other_us:190,wait_service:{us:200,calls:1},
    internal_timing:bad?{...detail,engine:{...detail.engine,hz:200000000}}:detail})}));
  await page.evaluate(()=>{Panels.showTab('link');$('#board-records').open=true;$('#task-timing-details').open=true;TimingPanel.select(78,S.runs[78].s.board);});
  await page.locator('#task-timing-read').click();await page.waitForFunction(()=>$('#task-timing-table tbody').children.length===17);
  report.checks.internal_ps_pl_measurement_separate=await page.evaluate(()=>$('#task-timing-state').textContent.includes('199.998')&&$('#task-timing-state').textContent.includes('不含PS')&&$('#task-timing-state').textContent.includes('不能再加到wait'));
  await page.locator('#task-timing-state').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'offline_ps_pl_timing.png')});
  report.checks.new_timing_no_horizontal_overflow=await page.locator('#task-timing-details').evaluate(e=>e.scrollWidth<=e.clientWidth+1);
  bad=true;await page.locator('#task-timing-read').click();await page.waitForFunction(()=>$('#task-timing-table tbody').children.length===0);
  report.checks.wrong_nominal_frequency_clears_measurements=await page.locator('#task-timing-export').isDisabled();
  await page.unroute('**/api/run/78/timing');
  await page.evaluate(()=>ConnectionPanel.apply({service_app:'gcs_r1_abi4',board_gate:{source:'board',authorized:false,active:false},uart:{active:false}}));
  report.checks.old_python_new_static_assets_cannot_connect=await page.locator('#board-connect').isDisabled()&&(await page.locator('#board-connect-state').innerText()).includes('后台未加载');
  await page.evaluate(async()=>{
    const source={source:'board',task_lifecycle:true,authorized:false,active:false};
    await BoardPanel.source(source);ConnectionPanel.apply({board_records_protocol:1,board_gate:source,uart:{active:false}});
  });
  let connectRequests=[],reply='failure';
  await page.route('**/api/board/connect',r=>{
    connectRequests.push(r.request().postDataJSON());
    const ready=reply==='ready'||reply==='malformed';
    const source={source:'board',task_lifecycle:true,boot_id:'12345678',active:false,authorized:ready,connection_transport:ready?'ethernet':null};
    const discovery={boot_id:'12345678',boot_method:r.request().postDataJSON().boot_method,independent_cold_start_verified:false,
      startup:{state:reply==='ready'?'ready':'scanning_models',scan_progress:{bytes:65536,registered:4}}};
    return r.fulfill({status:reply==='failure'?409:200,contentType:'application/json',body:JSON.stringify(reply==='failure'?{detail:'OFFLINE stale App rejected'}:{source,discovery,ready,uart_opened:false})});
  });
  report.checks.ethernet_restore_no_automatic_discovery=connectRequests.length===0;
  await page.locator('#board-boot-method').selectOption('jtag');
  page.once('dialog',d=>d.dismiss());await page.locator('#board-connect').click();
  report.checks.ethernet_cancel_no_traffic=connectRequests.length===0;
  page.once('dialog',d=>d.accept());await page.locator('#board-connect').click();
  await page.waitForFunction(()=>$('#board-connect-state').textContent.includes('OFFLINE stale App rejected'));
  report.checks.ethernet_explicit_confirmation_and_failure_gate=connectRequests.length===1&&connectRequests[0].confirmed===true&&connectRequests[0].boot_method==='jtag'&&
    (await page.locator('#board-connect-state').innerText()).includes('不启动任务');
  report.checks.connection_failure_no_stale_receipt=await page.locator('#board-connect-details').textContent()==='';
  reply='scanning';await page.locator('#board-boot-method').selectOption('sd');
  page.once('dialog',d=>d.accept());await page.locator('#board-connect').click();
  await page.waitForFunction(()=>$('#board-connect-state').textContent.includes('正在扫描 SD 模型'));
  report.checks.scan_progress_does_not_authorize=connectRequests.length===2&&connectRequests[1].boot_method==='sd'&&await page.evaluate(()=>!S.source.authorized)&&
    await page.locator('#board-connect').isEnabled()&&(await page.locator('#board-connect-state').innerText()).includes('65536');
  reply='malformed';page.once('dialog',d=>d.accept());await page.locator('#board-connect').click();
  await page.waitForFunction(()=>$('#board-connect-state').textContent.includes('缺少完整启动核验'));
  report.checks.malformed_ready_cannot_keep_old_receipt=await page.locator('#board-connect-details').textContent()===''&&await page.evaluate(()=>!S.source.authorized);
  reply='ready';await page.locator('#board-boot-method').selectOption('jtag');
  page.once('dialog',d=>d.accept());await page.locator('#board-connect').click();
  await page.waitForFunction(()=>$('#board-connect-state').textContent.includes('12345678 已就绪'));
  report.checks.ethernet_ready_still_requires_explicit_task=connectRequests.length===4&&connectRequests[3].boot_method==='jtag'&&await page.locator('#board-connect').isDisabled()&&
    (await page.locator('#board-connect-state').innerText()).includes('独立冷启动仍需人工验收');
  report.checks.ethernet_controls_no_horizontal_overflow=await page.locator('#board-connect-state').evaluate(e=>e.scrollWidth<=e.clientWidth+1);
  await page.evaluate(()=>ConnectionPanel.offline());
  report.checks.connection_offline_clears_old_receipt=await page.locator('#board-connect-details').textContent()===''&&await page.locator('#board-connect').isDisabled();
  await page.unroute('**/api/board/connect');
  await page.evaluate(()=>document.querySelector('#offline-round1-banner').remove());
}
module.exports={run};
