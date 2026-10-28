// Existing Playwright package, no simulator. --live only observes the current real job.
// node tools/check_gcs_roi.cjs <playwright-package> [--live]
const {chromium}=require(process.argv[2]);
const fs=require('node:fs');
const path=require('node:path');
const live=process.argv.includes('--live');
const out=path.resolve('report/gcs_roi/ui_observation_'+new Date().toISOString().replace(/[:.]/g,'-'));
fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const ctx=await browser.newContext({viewport:{width:1536,height:864},acceptDownloads:true});
  const page=await ctx.newPage();
  const errors=[], events=[];
  page.on('pageerror',e=>errors.push(String(e)));
  page.on('websocket',ws=>ws.on('framereceived',f=>{
    if(typeof f.payload==='string') {try { const m=JSON.parse(f.payload); if(['board_update','run_start','run_end','log'].includes(m.type)) events.push(m); }catch{}}
  }));
  const checks={};
  let report={mode:live?'live-board':'offline-ui-gate',checks,errors,events};
  try {
    await page.goto('http://127.0.0.1:8765');
    await page.waitForFunction(()=>typeof S!=='undefined' && S.info && S.ws?.readyState===1,{},{timeout:90000});
    if(!live){
      await page.locator('#pill-source').click();
      await page.locator('input[name=src][value=board]').check();
      await page.locator('#btn-source').click();
      await page.waitForFunction(()=>S.source?.source==='board' && !document.querySelector('#board-roi').hidden && document.querySelector('#btn-start').disabled && document.querySelector('#t-temp').textContent==='未测');
      checks.fixed_source=await page.evaluate(()=>S.source.board_ip==='192.168.1.10' && S.source.board_port===5010);
      checks.no_authorization=await page.evaluate(()=>!S.source.authorized);
      checks.start_disabled=await page.locator('#btn-start').isDisabled();
      checks.missing_15=await page.locator('.board-cell.missing').count()===15;
      checks.no_export_without_run=await page.locator('#board-export-json').isDisabled();
      // Backend rejection tested as well, without authorizing or sending any UDP.
      await page.evaluate(()=>send({cmd:'start',kind:'region',scene:'longkou',version:'v2',rect:[0,0,3,5]}));
      await page.waitForFunction(()=>document.querySelector('#log').textContent.includes('not confirmed'));
      const st=await (await page.request.get('http://127.0.0.1:8765/api/state')).json();
      checks.no_task_created=st.run===null && st.runs.length===0;
      const probe=await page.request.get('http://127.0.0.1:8765/api/probe?scene=longkou&version=v2&r=0&c=0');
      checks.pc_probe_blocked=probe.status()===409;
      const old=await page.request.post('http://127.0.0.1:8765/api/board/authorize',{data:{boot_id:'e4196b84',board_started:true}});
      checks.old_boot_blocked=old.status()===400;
      await page.evaluate(()=>Panels.probe(0,0));
      checks.no_missing_probe_fallback=await page.locator('#probe-head').textContent().then(t=>t.includes('尚未收到'));
      checks.oa_not_measured=await page.locator('#m-oa').textContent().then(t=>t==='未测');
    } else {
      if(process.argv.includes('--await-start'))
        await page.waitForFunction(()=>S.source?.source==='board' && S.live,{},{timeout:120000});
      await page.waitForFunction(()=>S.source?.source==='board' && S.live && ['done','error'].includes(S.runs[S.live]?.s.status),{},{timeout:35000});
      const run=await page.evaluate(()=>S.runs[S.live].s);
      const snap=await (await page.request.get(`http://127.0.0.1:8765/api/run/${run.id}/board`)).json();
      if(snap.full_scene)throw Error('Use the full-scene acceptance button; this observer is restricted to the legacy 15-cell ROI');
      const cells=await page.locator('.board-cell:not(.missing)').evaluateAll(els=>els.map(el=>({x:+el.dataset.x,y:+el.dataset.y,class_word:el.querySelector('.word').textContent,class_id:+el.querySelector('strong').textContent.replace('类别 ',''),confidence_q16:+el.dataset.q16,confidence:+el.querySelector('.confidence').textContent})));
      Object.assign(report,{boot_id:snap.boot_id,session:snap.session,task:snap.task,run_id:run.id,cells});
      checks.status_done=snap.status==='done' && run.status==='done';
      checks.dom_api_exact=JSON.stringify(cells)===JSON.stringify(snap.cells);
      checks.unique_15=new Set(cells.map(c=>`${c.x},${c.y}`)).size===15;
      checks.ack_done=!!snap.ack && snap.done_status?.done===15 && snap.done_status?.total===15 && snap.done_status?.front_row===3;
      checks.identity=await page.locator('#board-identity').textContent().then(t=>[snap.boot_id,snap.session,String(snap.task)].every(v=>t.includes(v)));
      checks.progress_15=await page.locator('#board-progress-bar').getAttribute('value')==='15';
      checks.failed_not_success=!snap.error;
      checks.no_retry_button=await page.locator('#btn-start').isDisabled();
      checks.map_exact=await page.evaluate(s=>s.cells.every(c=>{const r=S.runs[S.live],i=c.y*S.W+c.x;return r.pred[i]===c.class_id+1 && r.conf[i]/255===c.confidence;}),snap);
      await page.locator('.board-cell[data-x="0"][data-y="0"]').click();
      const first=snap.cells[0];
      checks.probe_current_result=await page.locator('#probe-head').textContent().then(t=>t.includes(`类别 ${first.class_id}`)&&t.includes(String(first.confidence)));
      checks.probe_raw_word=await page.locator('#probe-kv').textContent().then(t=>t.includes(first.class_word)&&t.includes(snap.boot_id));
      // Exercise both actual export buttons, compare their download contents.
      for(const format of ['json','csv']) {
        const promise=page.waitForEvent('download');
        await page.locator(`#board-export-${format}`).click();
        const download=await promise, file=path.join(out,`ui_export.${format}`);
        await download.saveAs(file);
        if(format==='json')checks.json_export_exact=JSON.stringify(JSON.parse(fs.readFileSync(file,'utf8')).cells)===JSON.stringify(cells);
        else checks.csv_export_15=fs.readFileSync(file,'utf8').trim().split(/\r?\n/).length===16;
      }
    }
    checks.unmeasured=await page.evaluate(()=>['t-power','t-temp','t-rate','t-mspx','t-jpx'].every(id=>document.getElementById(id).textContent==='未测'));
    checks.chinese_class_mapping=await page.evaluate(()=>S.boardClasses?.[0]?.name_zh==='玉米');
    await page.locator('#board-details summary').click();
    checks.details_can_expand=await page.locator('#board-grid').isVisible();
    const layout=await page.locator('#board-roi').evaluate(el=>{const r=el.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom,scrollWidth:el.scrollWidth,clientWidth:el.clientWidth,viewport:[innerWidth,innerHeight]};});
    report.layout=layout;
    checks.layout=layout.right<=layout.viewport[0] && layout.bottom<=layout.viewport[1] && layout.scrollWidth<=layout.clientWidth;
    checks.no_map_panel_overlap=await page.evaluate(()=>{
      const a=document.querySelector('#map').getBoundingClientRect(),b=document.querySelector('#board-roi').getBoundingClientRect(),l=document.querySelector('.layers').getBoundingClientRect();
      return a.right<=b.left && l.right<=b.left && getComputedStyle(document.querySelector('.legend')).display==='none';
    });
    checks.no_browser_error=errors.length===0;
    report.text=await page.locator('#board-roi').innerText();
    if(live) await page.screenshot({path:path.join(out,'formal_ui.png')});
    report.result=Object.values(checks).every(Boolean)?'PASS':'FAIL';
  } catch(e) {report.result='FAIL';report.failure=String(e);}
  finally {
    fs.writeFileSync(path.join(out,live?'ui_acceptance.json':'ui_gate_check.json'),JSON.stringify(report,null,2));
    await ctx.close();await browser.close();
  }
  console.log(JSON.stringify(report,null,2));
  if(report.result!=='PASS')process.exitCode=1;
})();
