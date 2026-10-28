// Browser-only offline fixtures. No real GCS service, UART, UDP or inference.
const {chromium}=require(process.argv[2]);
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const agri=require('./check_gcs_agri.cjs');
const models=require('./check_gcs_models.cjs');
const round1=require('./check_gcs_round1.cjs');
const out=path.resolve(process.argv[3]||'build/host/gcs_ui_check');fs.mkdirSync(out,{recursive:true});
const web=path.resolve('gcs/web'),total=220000,raw=Buffer.alloc(total*5),requests=[];
for(let i=0;i<total;i++){raw.writeUInt32LE((((i*13)&65535)*65536+(i%9))>>>0,i*4);raw[total*4+i]=1;}
let badRestore=false;
let badMetrics=false,slowMetrics=false;
const metricsFixture={source:'board',n:3,test_total:5,OA:2/3,AA:.75,Kappa:.4,complete_test_coverage:false,
  per_class:[.5,1,...Array(7).fill(null)],cm:[[1,1,...Array(7).fill(0)],[0,1,...Array(7).fill(0)],...Array.from({length:7},()=>Array(9).fill(0))],
  evaluation:{manifest_sha256:'offline-label-fixture'},prediction_words_seen_sha256:'offline-words-fixture'};
const server=http.createServer((req,res)=>{
  const record={method:req.method,url:req.url};requests.push(record);
  if(agri.route(req,res))return;
  if(models.route(req,res))return;
  if(req.url==='/api/run/1/metrics'){
    const bad=badMetrics,reply=()=>{res.setHeader('Content-Type','application/json');res.writeHead(bad?409:200);
      res.end(JSON.stringify(bad?{detail:'OFFLINE fixed label CRC mismatch'}:metricsFixture));};
    if(slowMetrics)setTimeout(reply,120);else reply();return;
  }
  if(req.url.startsWith('/api/scene/longkou/input-point?')){
    const query=new URL(req.url,'http://fixture').searchParams,row=+query.get('r'),col=+query.get('c');
    const reply=()=>{
      res.setHeader('Content-Type','application/json');
      if(row===548){res.writeHead(409);res.end(JSON.stringify({detail:'OFFLINE input hash mismatch'}));return;}
      res.end(JSON.stringify({scene:'longkou',row,col,board_returned:false,pc_model_inference:false,wavelengths_nm:null,
        source:{path:'OFFLINE/fixture/cube_f32.bin',bytes:243794880,sha256:'0'.repeat(64),crc32:'01234567'},
        band_indices:Array.from({length:270},(_,i)=>i),spectrum:Array.from({length:270},(_,i)=>row+i/270),
        rgb_bands:[112,67,31],patch_rgb:Array.from({length:7},()=>Array.from({length:7},()=>[10,80,160])),
        patch_valid:Array.from({length:7},()=>Array(7).fill(1))}));
    }; if(row===0)setTimeout(reply,120);else reply();return;
  }
  if(req.url==='/api/run/1/board_words'){
    if(badRestore){res.writeHead(503);res.end('unavailable');return;}
    res.setHeader('Content-Type','application/octet-stream');res.end(raw);return;
  }
  if(req.url==='/api/run/1/board/probe'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({state:'queued',row:549,col:399,req_seq:null,error:null}));return;}
  if(req.url==='/api/run/1/board/acceptance'){res.writeHead(409,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:'OFFLINE fixture: board records missing'}));return;}
  if(req.url==='/api/board/connect'){let body='';req.on('data',d=>body+=d);req.on('end',()=>{record.body=JSON.parse(body);res.writeHead(409,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:'OFFLINE board endpoint unavailable'}));});return;}
  if(req.url==='/web/app.js'){res.end('// Offline component integration; no service/WS connection.');return;}
  const target=req.url==='/'?path.join(web,'index.html'):path.resolve(web,req.url.replace(/^\/web\//,''));
  if(!target.startsWith(web+path.sep)||!fs.existsSync(target)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':target.endsWith('.json')?'application/json':'text/html');
  res.end(fs.readFileSync(target));
});
(async()=>{
  let browser;const report={scope:'OFFLINE_BROWSER_FIXTURES_NOT_BOARD_ACCEPTANCE',checks:{},errors:[]};
  try{
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    browser=await chromium.launch({channel:'msedge',headless:true});
    const page=await browser.newPage({viewport:{width:1536,height:864}});
    page.on('pageerror',e=>report.errors.push(String(e)));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(()=>typeof BoardPanel!=='undefined'&&S.boardClasses?.length===9);
    await page.evaluate(async()=>{
      S.scene='longkou';S.H=550;S.W=400;S.version='v2';S.gsd=.463;
      S.info={classes:S.boardClasses.map(c=>c.name_zh),mission:{gsd_m:.463},versions:[{id:'v2'}],palette:['#000000','#ff0000','#00ff00','#0000ff','#aaaa00','#aa00aa','#00aaaa','#bbbbbb','#444444','#ff8800']};
      S.palRGB=S.info.palette.map(hexRGB);S.gt=new Uint8Array(220000);S.split=new Uint8Array(220000);
      S.base=document.createElement('canvas');S.base.width=400;S.base.height=550;
      const counts=Array(9).fill(0);for(let i=0;i<220000;i++)counts[i%9]++;
      const b={boot_id:'12345678',session:'0000002a',task:7,start_seq:1,scene:'longkou',model:'v2',wcrc:'27231983',full_scene:true,
        total:220000,received_pixels:220000,class_counts:counts,roi:{x:0,y:0,width:400,height:550},status:'done',ack:true,done_status:{done:220000},cells:[],
        interaction:{state:'open',reason:null,probe:null}};
      S.runs[1]={s:{id:1,source:'board',scene:'longkou',version:'v2',kind:'scan',total:220000,done:220000,status:'done',board:b},loaded:false};
      S.live=1;S.runA=1;MapView.resetScene();
      await BoardPanel.source({source:'board',authorized:false,active:true,board_ip:'192.168.1.10',board_port:5010});
      await loadRun(1);MapView.repaintAll();
    });
    report.checks.exact_220000_words=await page.evaluate(()=>S.runs[1].words.every((w,i)=>w===((((i*13)&65535)*65536+(i%9))>>>0))&&S.runs[1].seen.every(v=>v===1));
    report.checks.pc_has_no_duplicate_dp_panel=await page.locator('#board-class-map,#board-class-summary,.map-wrap #board-roi').count()===0;
    report.checks.canvas_full_scene=await page.evaluate(()=>{
      const c=document.querySelector('#map').getBoundingClientRect(),wrap=document.querySelector('#map-wrap').getBoundingClientRect();
      return Math.abs(c.width-wrap.width)<1&&Math.abs(c.height-wrap.height)<1&&
        Math.abs(S.view.x+S.W*S.view.k/2-c.width/2)<1&&Math.abs(S.view.y+S.H*S.view.k/2-c.height/2)<1&&
        S.view.x>=0&&S.view.y>=0&&S.W*S.view.k<=c.width&&S.H*S.view.k<=c.height;
    });
    report.checks.details_collapsed=!(await page.locator('#board-details').getAttribute('open'));
    report.checks.chinese_classes=await page.locator('.legend').isVisible()&&(await page.locator('.legend').innerText()).includes('玉米');
    report.checks.unmeasured=await page.evaluate(()=>['t-power','t-temp','t-rate','t-mspx','t-jpx'].every(id=>document.getElementById(id).textContent==='未测'));
    await page.evaluate(()=>{Panels.showTab('eval');return Panels.metrics(1);});
    report.checks.board_metrics_exact_display=await page.locator('#m-oa').innerText()==='66.67'&&
      await page.locator('#m-aa').innerText()==='75.00'&&await page.locator('#m-kappa').innerText()==='0.4000'&&
      (await page.locator('#m-n').innerText()).includes('部分覆盖');
    report.checks.board_confusion_raw_counts=await page.evaluate(()=>{
      const cells=Panels.charts['chart-cm'].getOption().series[0].data;return cells[0][3]===1&&cells[1][3]===1&&cells.length===81;
    });
    const downloaded=page.waitForEvent('download');await page.locator('#btn-metrics-export').click();
    const artifact=await downloaded;await artifact.saveAs(path.join(out,'offline_metrics_export.json'));
    report.checks.metric_export_matches_display=JSON.stringify(JSON.parse(fs.readFileSync(path.join(out,'offline_metrics_export.json'))))===JSON.stringify(metricsFixture);
    await page.screenshot({path:path.join(out,'offline_metrics.png')});
    badMetrics=true;await page.evaluate(()=>Panels.metrics(1));
    report.checks.metric_failure_no_stale_values=await page.locator('#m-oa').innerText()==='—'&&
      (await page.locator('#m-n').innerText()).includes('CRC mismatch')&&await page.locator('#btn-metrics-export').isDisabled();
    badMetrics=false;slowMetrics=true;
    await page.evaluate(()=>{const p=Panels.metrics(1);S.runA=2;Panels.clearMetrics();return p;});
    report.checks.metric_old_request_cannot_replace_new_run=await page.locator('#m-oa').innerText()==='—'&&
      await page.locator('#btn-metrics-export').isDisabled();
    slowMetrics=false;await page.evaluate(()=>{S.runA=1;return Panels.metrics(1);});
    await page.evaluate(()=>BoardPanel.probe(549,399));
    report.checks.probe_does_not_erase_metrics=await page.locator('#m-oa').innerText()==='66.67';
    report.checks.local_input_no_inference=await page.evaluate(()=>{
      const src=document.querySelector('[data-board-input-source]');
      return src?.textContent==='预处理输入光谱'&&JSON.parse(src.dataset.boardInputSource).crc32==='01234567'&&
        Panels.charts['chart-spectrum']?.getOption().series[0].data.length===270;
    });
    report.checks.selection_passive=!requests.some(r=>r.method==='POST');
    await page.locator('#board-probe-run').click();
    await page.waitForFunction(()=>document.querySelector('#board-probe-state').textContent.includes('排队中'));
    report.checks.explicit_probe_post=requests.filter(r=>r.url==='/api/run/1/board/probe').length===1;
    await page.evaluate(()=>{
      const b=structuredClone(S.runs[1].s.board),word=S.runs[1].words[219999];
      b.interaction.probe={state:'done',row:549,col:399,req_seq:11,class_word:word.toString(16).padStart(8,'0'),class_id:word&255,
        confidence_q16:word>>>16,logits_q16:[0,1,2,3,4,5,6,7,8],probabilities:Array(9).fill(1/9)};
      BoardPanel.apply(1,b);BoardPanel.apply(1,b);
    });
    report.checks.logits_probabilities_label=(await page.locator('#board-probe-state').innerText()).includes('置信度')&&await page.locator('[data-probe-logits="value"]').isHidden();
    report.checks.board_only_ui=await page.locator('input[name="src"]').count()===0&&await page.locator('#btn-source').count()===0;
    report.checks.no_redundant_technical_text=!/PC推理|PC模型|本子集|WCRC|req_seq|boot=/.test(await page.locator('body').innerText());
    await page.evaluate(()=>{const b=structuredClone(S.runs[1].s.board);b.interaction.probe.state='error';b.interaction.probe.error='offline timeout';BoardPanel.apply(1,b);});
    report.checks.probe_failure_clears_old_success=await page.locator('[data-probe-logits]').count()===0;
    await page.evaluate(()=>{BoardPanel.probe(0,0);return BoardPanel.probe(1,1);});
    await page.waitForTimeout(180); // deliberate older delayed fixture response
    report.checks.local_input_stale_response_ignored=await page.evaluate(()=>
      document.querySelector('[data-board-input-source]')?.dataset.row==='1'&&
      Panels.charts['chart-spectrum'].getOption().series[0].data[0][1]===1);
    await page.evaluate(()=>BoardPanel.probe(548,399));
    report.checks.local_input_failure_clears_old_display=await page.evaluate(()=>
      document.querySelector('[data-board-input-source]')?.textContent.includes('hash mismatch')&&
      !Panels.charts['chart-spectrum'].getOption().series?.length);
    report.checks.attention_unavailable_not_logits=await page.locator('#rng-layer').isDisabled()&&
      (await page.locator('#chart-attn').getAttribute('data-empty')).includes('暂不可用');
    await page.evaluate(()=>BoardPanel.probe(549,399));
    badRestore=true;
    report.checks.restore_failure_not_loaded=await page.evaluate(async()=>{S.runs[1].loaded=false;try{await loadRun(1);return false;}catch(e){return !S.runs[1].loaded&&e.message.includes('503');}});
    badRestore=false;await page.evaluate(()=>loadRun(1));
    // Actual refresh, then restore component state from saved fixture in a new page
    // is covered above by the same production loadRun path, not synthetic pixel painting.
    await page.evaluate(()=>Panels.showTab('link'));
    await page.evaluate(()=>ConnectionPanel.apply({board_records_protocol:1,board_gate:{source:'board',active:false,authorized:false},uart:{active:false}}));
    report.checks.ethernet_restore_no_open=!requests.some(r=>r.url.startsWith('/api/uart/')||r.url==='/api/board/connect');
    report.checks.no_normal_serial_controls=await page.locator('#uart-start,#uart-port,#sd-connect,script[src*="uart.js"]').count()===0;
    report.checks.connection_diagnostics_collapsed=await page.locator('#board-connect-diagnostics').evaluate(e=>!e.open);
    await page.locator('#board-connect').click();
    report.checks.boot_method_not_guessed=await page.locator('#board-boot-method').inputValue()===''&&!requests.some(r=>r.url==='/api/board/connect');
    await page.locator('#board-boot-method').selectOption('jtag');
    page.once('dialog',d=>d.accept());await page.locator('#board-connect').click();
    await page.waitForFunction(()=>$('#board-connect-state').textContent.includes('OFFLINE board endpoint unavailable'));
    const connect=requests.find(r=>r.url==='/api/board/connect');
    report.checks.explicit_jtag_failure_no_start=connect.body.confirmed===true&&connect.body.boot_method==='jtag'&&
      (await page.locator('#board-connect-state').innerText()).includes('无响应不等于 SD 仍在加载');
    await page.evaluate(()=>ConnectionPanel.apply({board_records_protocol:1,board_gate:{source:'board',active:false,authorized:false},uart:{active:true}}));
    report.checks.existing_uart_owner_not_taken_over=await page.locator('#board-connect').isDisabled();
    await page.evaluate(()=>ConnectionPanel.apply({board_records_protocol:1,uart:{active:false},board_gate:{source:'board',active:false,authorized:true,connection_transport:'ethernet',boot_id:'12345678'}}));
    report.checks.ready_without_manual_identity=(await page.locator('#board-connect-state').innerText()).includes('显式开始任务')&&await page.locator('#board-connect').isDisabled();
    await page.screenshot({path:path.join(out,'offline_connect.png')});
    await page.setViewportSize({width:1100,height:768});
    await page.locator('#board-connect-state').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out,'offline_connect_1100.png')});
    report.checks.connect_button_viewport=await page.locator('#board-connect').evaluate(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;});
    await page.setViewportSize({width:1536,height:864});
    const first=await browser.newPage();await first.goto(`http://127.0.0.1:${server.address().port}`);
    await first.waitForFunction(()=>typeof ConnectionPanel!=='undefined');
    const connections=requests.filter(r=>r.url==='/api/board/connect').length;
    await first.evaluate(()=>{Panels.showTab('link');ConnectionPanel.apply({board_records_protocol:1,uart:{active:false},board_gate:{source:'board',active:false,authorized:false}});});
    await first.locator('#board-connect').click();
    report.checks.first_use_never_guesses_startup=await first.locator('#board-boot-method').inputValue()===''&&requests.filter(r=>r.url==='/api/board/connect').length===connections;
    await first.close();
    await page.evaluate(()=>Panels.showTab('link'));
    await page.locator('#board-records').evaluate(el=>{el.open=true;});
    await page.locator('#board-acceptance').click();
    await page.waitForFunction(()=>document.querySelector('#board-acceptance-state').textContent.includes('board records missing'));
    report.checks.unified_verification_reports_gap_without_rerun=true;
    report.checks.no_pc_probe_or_control=requests.every(r=>!r.url.startsWith('/api/probe')&&!r.url.includes('authorize'));
    report.checks.lifecycle_accumulates_and_isolates=await page.evaluate(async()=>{
      S.runA=S.live=2;S.runs[2]=newRun({id:2,source:'board',scene:'longkou',version:'v2',kind:'region',status:'running',total:2,done:0});
      const b={boot_id:'12345678',session:'00000042',task:8,task_lifecycle:true,roi:{x:398,y:549,width:2,height:1},full_scene:false,total:2,received_pixels:1,status:'running',class_counts:[1,0,0,0,0,0,0,0,0],interaction:{state:'open'},cells:[]};
      const cell=(x,k)=>({x,y:549,class_word:(0xffff0000+k).toString(16),class_id:k,confidence_q16:65535,confidence:65535/65536});
      BoardPanel.apply(2,{...b,chunk:[cell(398,0)]});BoardPanel.apply(2,{...b,received_pixels:2,status:'done',chunk:[cell(399,1)]});
      const intact=S.runs[2].seen[219998]===1&&S.runs[2].seen[219999]===1&&S.runs[2].words[219998]===0xffff0000;
      S.runA=1;BoardPanel.apply(1,S.runs[1].s.board);
      BoardPanel.apply(2,S.runs[2].s.board);
      return intact&&document.querySelector('#board-identity').textContent==='任务 #7';
    });
    report.checks.lifecycle_start_uses_actual_rectangle=await page.evaluate(async()=>{
      S.runA=S.live=2;S.runs[2].s.status='stopped';S.rect=[549,398,1,2];S.kind='region';
      BoardPanel.gate({source:'board',task_lifecycle:true,authorized:true,active:true});
      window.offlineCommands=[];S.ws={readyState:1,send:data=>offlineCommands.push(JSON.parse(data))};
      BoardPanel.start();return JSON.stringify(offlineCommands[0]?.rect)==='[549,398,1,2]'&&offlineCommands[0]?.kind==='region';
    });
    report.checks.lifecycle_controls_wait_for_confirmation=await page.evaluate(()=>{
      BoardPanel.rejected('start');const retry=!document.querySelector('#btn-start').disabled;
      S.runs[2].s.status='paused';S.runs[2].s.board.command=null;
      BoardPanel.gate({source:'board',task_lifecycle:true,authorized:false,active:true});
      const resume=!document.querySelector('#btn-pause').disabled&&document.querySelector('#btn-pause').textContent.includes('继续');
      S.runs[2].s.board.command={kind:4,state:'applying'};BoardPanel.gate(S.source);
      return retry&&resume&&document.querySelector('#btn-pause').disabled&&document.querySelector('#btn-stop').disabled;
    });
    report.checks.board_compute_timing_independent_of_receive_rate=await page.evaluate(()=>{
      S.runs[2].s.status='running';S.runs[2].s.receive_rate=1;
      S.runs[2].s.board.performance={ms_per_pixel:5,pixels_per_second:200};BoardPanel.gate(S.source);
      const ok=document.querySelector('#t-rate').textContent==='200'&&document.querySelector('#t-mspx').textContent==='5.000';
      S.runs[2].s.board.performance=null;BoardPanel.gate(S.source);
      return ok&&document.querySelector('#t-rate').textContent==='未测'&&document.querySelector('#t-mspx').textContent==='未测';
    });
    report.checks.history_http_merges_concurrent_live_words=await page.evaluate(async()=>{
      const fetch0=window.fetch;let release;
      const b={...S.runs[2].s.board,task:98,command:null,received_pixels:1,status:'running',roi:{x:0,y:0,width:2,height:1}};
      const r=S.runs[98]={s:{...S.runs[2].s,id:98,board:b},pred:null,conf:null,loaded:false};
      const raw=new Uint8Array(220000*5),dv=new DataView(raw.buffer);dv.setUint32(0,0xffff0002,true);raw[220000*4]=1;
      window.fetch=url=>String(url).includes('/api/run/98/board_words')?new Promise(resolve=>release=resolve):fetch0(url);
      try {
        const waiting=loadRun(98);
        BoardPanel.apply(98,{...b,chunk:[{x:1,y:0,class_word:'FFFF0003',class_id:3,confidence:65535/65536,confidence_q16:65535}]});
        release({ok:true,arrayBuffer:async()=>raw.buffer});await waiting;
        return r.seen[0]===1&&r.seen[1]===1&&r.words[0]===0xffff0002&&r.words[1]===0xffff0003;
      }finally{window.fetch=fetch0;delete S.runs[98];}
    });
    report.checks.recovery_button_is_explicit_and_fault_gated=await page.evaluate(()=>{
      S.runA=S.live=2;const b=S.runs[2].s.board;
      const test={...b,start_seq:1,command:null,error:'Disconnected fixture',status:'error',interaction:{state:'closed'},integrity_error:false};
      BoardPanel.gate({source:'board',task_lifecycle:true,active:false});BoardPanel.apply(2,test);
      const enabled=!document.querySelector('#board-recover').disabled;
      BoardPanel.apply(2,{...test,integrity_error:true});
      return enabled&&document.querySelector('#board-recover').disabled;
    });
    await agri.run(page,report,out);
    await models.run(page,report,out);
    await round1.run(page,report,out);
    report.checks.no_js_errors=report.errors.length===0;
    await page.evaluate(()=>Panels.showTab('probe'));
    await page.evaluate(()=>{MapView.resize();MapView.fit();});
    report.layout=await page.locator('#map-wrap').evaluate(el=>{const r=el.getBoundingClientRect();return {right:r.right,bottom:r.bottom,width:r.width,scrollWidth:el.scrollWidth,clientWidth:el.clientWidth};});
    report.checks.viewport_fit=report.layout.right<=1536&&report.layout.bottom<=864&&report.layout.scrollWidth<=report.layout.clientWidth;
    await page.screenshot({path:path.join(out,'offline_scene.png')});
    report.result=Object.values(report.checks).every(Boolean)?'PASS':'FAIL';
  }catch(e){report.result='FAIL';report.failure=String(e);}
  finally{
    if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));
    fs.writeFileSync(path.join(out,'offline_browser.json'),JSON.stringify(report,null,2));
  }
  console.log(JSON.stringify(report,null,2));if(report.result!=='PASS')process.exitCode=1;
})();
