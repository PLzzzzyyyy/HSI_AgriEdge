'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const base='http://127.0.0.1:8765';
(async()=>{
  const state=await (await fetch(base+'/api/state')).json();
  assert.equal(state.source.release_id,'3db78827f96da19d3ab1c33206abf72b58217c397ef532a7a24032b3aafd8d8e');
  assert(state.source.channel_ready);
  for(const path of ['/','/web/panels.js']){
    const source=await (await fetch(base+path)).text();assert(!source.includes('估算'),path);
  }
  const html=await (await fetch(base+'/')).text();
  for(const label of ['芯片参考功耗','本任务参考能耗','参考 mJ / 像素','非实测'])assert(html.includes(label),label);
  const ws=new WebSocket(base.replace('http','ws')+'/ws');
  const telemetry=await new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>reject(Error('No live telemetry')),10000);
    ws.addEventListener('message',event=>{
      if(typeof event.data!=='string')return;const m=JSON.parse(event.data);
      if(m.type==='tick'&&m.telemetry?.power_est_state==='valid'){clearTimeout(timeout);resolve(m.telemetry);}
    });
    ws.addEventListener('error',reject,{once:true});
  });
  ws.close();assert(!telemetry.device.includes('估算'));
  assert.equal(telemetry.power_estimate.measured,false);
  assert.equal(telemetry.power_estimate.model_id,'a4363b00');
  const frame=await fetch(base+'/api/dp/frame.png',{signal:AbortSignal.timeout(20000)});assert(frame.ok);
  fs.writeFileSync('report/chip_power_labels_20261021/dp_live.png',Buffer.from(await frame.arrayBuffer()));
  const report={result:'PASS',boot:state.source.boot_id,release_id:state.source.release_id,
    model_id:telemetry.power_estimate.model_id,telemetry,
    labels:['芯片参考功耗','本任务参考能耗','参考 mJ / 像素'],
    source_notice_retained:'Vivado 模型／非实测',frame:'dp_live.png',
    scope:'Display wording only; power model and inference hardware unchanged'};
  fs.writeFileSync('report/chip_power_labels_20261021/live_verification.json',JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({result:report.result,boot:report.boot,power_reference_w:telemetry.power_est_w}));
})().catch(e=>{console.error(e);process.exit(1);});
