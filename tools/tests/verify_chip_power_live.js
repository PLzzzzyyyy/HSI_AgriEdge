'use strict';
// Explicit local demo verification: real board regions, pause/resume and a probe.
const assert=require('node:assert/strict'),fs=require('node:fs');
const base='http://127.0.0.1:8765';
const out='report/chip_power_20261021';
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function api(path,body){const r=await fetch(base+path,{...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(120000)});assert(r.ok,await r.clone().text());return r.json();}
async function until(predicate,timeout=90000){const end=Date.now()+timeout;while(Date.now()<end){const v=await predicate();if(v)return v;await delay(100);}throw Error('Verification timeout');}
(async()=>{
  const before=await api('/api/state');assert(before.source.channel_ready);
  assert(!['running','paused'].includes(before.run?.status),'Do not interrupt user task');
  const ws=new WebSocket(base.replace('http','ws')+'/ws');let tick;
  const errors=[];ws.addEventListener('message',event=>{if(typeof event.data==='string'){const m=JSON.parse(event.data);if(m.type==='tick')tick=m;if(m.type==='error')errors.push(m);}});
  await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
  await until(()=>tick?.telemetry?.power_est_state==='valid');
  assert.equal(tick.telemetry.power_w,null);assert.equal(tick.telemetry.power_estimate.measured,false);
  const initial=tick.telemetry;
  console.log('LIVE: connected; estimate',initial.power_est_w,'W; temperature',initial.temp_c);
  ws.send(JSON.stringify({cmd:'start',kind:'region',scene:'longkou',version:'v2',rect:[0,0,50,20],pace_rows:0}));
  let first=await until(async()=>{const s=await api('/api/state');assert(!errors.length,JSON.stringify(errors));return s.run&&s.run.id!==before.run?.id?s.run:null;});
  const id=first.id;
  await until(async()=>{first=(await api('/api/state')).run;assert.equal(first.id,id);assert.notEqual(first.status,'error',JSON.stringify(first.board));return first.done>=80;});
  ws.send(JSON.stringify({cmd:'pause'}));
  await until(async()=>{first=(await api('/api/state')).run;return first.status==='paused';},15000);
  await until(()=>tick?.run?.id===id&&tick.run.power_estimate?.active);
  await delay(1100);const pausedBefore=(await api('/api/state')).run.power_estimate;
  await delay(2100);const pausedAfter=(await api('/api/state')).run.power_estimate;
  assert(pausedAfter.energy_est_j>pausedBefore.energy_est_j,'Pause wall-time included');
  ws.send(JSON.stringify({cmd:'resume'}));
  first=await until(async()=>{const r=(await api('/api/state')).run;assert.notEqual(r.status,'error',JSON.stringify(r.board));return r.status==='done'&&r.power_estimate&&!r.power_estimate.active?r:null;});
  assert.equal(first.done,1000);assert.equal(first.energy_j,null);
  assert.equal(first.power_estimate.done,1000);const frozen=first.power_estimate;
  console.log('LIVE: region complete; energy frozen',frozen.energy_est_j,'J');
  await api(`/api/run/${id}/board/probe`,{row:1,col:1});
  await until(async()=>{const r=await api(`/api/run/${id}/board`);const p=r.interaction?.probe;assert.notEqual(p?.state,'error',JSON.stringify(p));return p?.state==='done'?p:null;});
  await delay(1300);const afterProbe=(await api('/api/state')).run.power_estimate;
  assert.equal(afterProbe.energy_est_j,frozen.energy_est_j);assert.equal(afterProbe.duration_s,frozen.duration_s);
  ws.send(JSON.stringify({cmd:'start',kind:'region',scene:'longkou',version:'v2',rect:[1,1,3,4],pace_rows:0}));
  const second=await until(async()=>{const r=(await api('/api/state')).run;return r.id!==id&&r.status==='done'&&r.power_estimate&&!r.power_estimate.active?r:null;});
  assert.equal(second.done,12);assert(second.power_estimate.energy_est_j<frozen.energy_est_j);
  const image=await fetch(base+'/api/dp/frame.png',{signal:AbortSignal.timeout(20000)});assert(image.ok,await image.clone().text());
  fs.writeFileSync(out+'/dp_live.png',Buffer.from(await image.arrayBuffer()));
  await delay(1100);const latest=(await api('/api/state')).run;
  assert.equal(latest.power_estimate.energy_est_j,second.power_estimate.energy_est_j);
  assert.equal(tick.telemetry.power_est_state,'valid');
  const report={result:'PASS',boot:before.source.boot_id,release_id:before.source.release_id,
    model_id:initial.power_estimate.model_id,initial_telemetry:initial,pause:{before:pausedBefore,after:pausedAfter},
    first:{id:first.id,done:first.done,estimate:frozen},after_probe:afterProbe,
    second:{id:second.id,done:second.done,estimate:second.power_estimate},latest_telemetry:tick.telemetry,
    checks:['real region inference','pause wall-time included','DONE freezes estimate','subsequent PL probe does not change task energy','new task resets account','PC receives same board model','physical framebuffer mirror captured'],
    scope:'Local board demonstration; estimated chip power, NOT measured board current/power or calibrated energy.'};
  fs.writeFileSync(out+'/live_verification.json',JSON.stringify(report,null,2)+'\n');
  ws.close();console.log(JSON.stringify({result:report.result,boot:report.boot,first:id,second:second.id,power_est_w:tick.telemetry.power_est_w,measured:false}));
})().catch(e=>{console.error(e);process.exit(1);});
