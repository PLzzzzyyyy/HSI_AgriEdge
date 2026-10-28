'use strict';
// Read-only live checks against the deployed local demonstration.
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const base='http://127.0.0.1:8765',dir='report/evaluation_clear_20261024';
const expected='342273bc4a349cdda65a7ffea68cee4524f229f6c738ca84bf556b0f4dfbb055';
async function get(path){const r=await fetch(base+path,{signal:AbortSignal.timeout(30000)});assert(r.ok,path);return r;}
(async()=>{
  const before=await (await get('/api/state')).json();
  assert.equal(before.source.release_id,expected);assert(before.source.channel_ready);
  assert.equal(before.run,null);assert.equal(before.runs.length,66);
  const m=await (await get('/api/run/66/metrics')).json();
  assert.equal(m.n,388);assert.equal(m.correct_pixels,337);assert.equal(m.task_test_total,203642);
  assert(Math.abs(m.OA-337/388)<1e-12);assert.equal(m.class_names[0],'玉米');
  assert.equal(m.complete_test_coverage,false);assert(m.macro_F1>0&&m.macro_F1<1);
  const csv=Buffer.from(await (await get('/api/run/66/metrics.csv')).arrayBuffer());
  assert.equal(csv.subarray(0,3).toString('hex'),'efbbbf');assert(csv.toString('utf8').includes('玉米'));
  fs.writeFileSync(`${dir}/live_metrics66.csv`,csv);
  fs.writeFileSync(`${dir}/live_metrics66.json`,JSON.stringify(m,null,2)+'\n');
  const html=await (await get('/')).text();
  for(const label of ['芯片功耗 W','本任务能耗 J','mJ / 像素','评测任务','清空内容'])assert(html.includes(label),label);
  for(const label of ['非实时','预测','非实测','估算','参考功耗','参考能耗'])assert(!html.includes(label),label);
  const ws=new WebSocket(base.replace('http','ws')+'/ws');
  const telemetry=await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{ws.close();reject(Error('No valid telemetry'));},12000);
    ws.addEventListener('message',e=>{
      if(typeof e.data!=='string')return;const m=JSON.parse(e.data);
      if(m.type==='tick'&&m.telemetry?.power_est_state==='valid'){
        clearTimeout(timer);resolve(m.telemetry);
      }
    });ws.addEventListener('error',reject,{once:true});
  });ws.close();
  assert.equal(telemetry.power_estimate.measured,false);
  assert.equal(telemetry.power_estimate.model_id,'a4363b00');
  assert.equal(telemetry.temp_source,'PS_SYSMON_DIE');assert(telemetry.temp_c>0);
  assert.equal(telemetry.power_estimate.task,0);
  const frame=await get('/api/dp/frame.png');
  fs.writeFileSync(`${dir}/dp_final.png`,Buffer.from(await frame.arrayBuffer()));
  const after=await (await get('/api/state')).json();
  assert.equal(after.run,null);assert.equal(after.runs.length,66);
  const deploymentPath='firmware/keys_20261018/deployment.json';
  const deployment=JSON.parse(fs.readFileSync(deploymentPath,'utf8'));
  assert.equal(deployment.release_id,expected);
  for(const [name,sha] of Object.entries(deployment.files))
    assert.equal(crypto.createHash('sha256').update(fs.readFileSync('firmware/keys_20261018/'+name)).digest('hex'),sha,name);
  const evidence={result:'PASS',time:new Date().toISOString(),release_id:expected,boot:after.source.boot_id,
    history_before:before.runs.length,history_after:after.runs.length,no_inference_started:true,
    startup:{ready:after.source.channel_ready,dp_rc:0,log:'.runtime-tmp/download_20261024_171652_26736.log'},
    metrics:{task:66,test_pixels:m.n,correct_pixels:m.correct_pixels,OA:m.OA,AA:m.AA,Kappa:m.Kappa,macro_F1:m.macro_F1,
      coverage:m.coverage,task_test_coverage:m.task_test_coverage,complete_test_coverage:m.complete_test_coverage},
    csv_utf8_bom:true,telemetry,
    manual_browser_checks:['startup without default 1x1 or automatic probe','evaluation dropdown and main evaluation action',
      'history 66 evaluated with charts and Chinese class table','clear removes current results and keeps history entries',
      'delayed tick and reload do not restore cleared result','explicit history selection restores evaluation'],
    screenshots:['pc_evaluation.jpg','pc_cleared.jpg','dp_final.png'],
    scope:'Local demonstration verification; fixed inference hardware and power model retained; no full-scene benchmark in this test'};
  fs.writeFileSync(`${dir}/live_verification.json`,JSON.stringify(evidence,null,2)+'\n');
  deployment.state='DEPLOYED_LOCAL_DEMO';deployment.boot=after.source.boot_id;
  deployment.verification=`${dir}/live_verification.json`;
  fs.writeFileSync(deploymentPath,JSON.stringify(deployment,null,2)+'\n');
  console.log(JSON.stringify({result:'PASS',boot:evidence.boot,history:after.runs.length,power_w:telemetry.power_est_w,temp_c:telemetry.temp_c}));
})().catch(e=>{console.error(e);process.exit(1);});
