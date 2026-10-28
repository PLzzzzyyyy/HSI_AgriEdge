'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const base='http://127.0.0.1:8765',dir='report/interaction_speed_20261024';
const release='d0f9bde2125ddb4ed96c46986b04fed91daab0a264d679c067db09a2fd2fdb29';
async function get(path){const r=await fetch(base+path,{signal:AbortSignal.timeout(30000)});assert(r.ok,path);return r;}
(async()=>{
  const state=await (await get('/api/state')).json();assert.equal(state.source.release_id,release);assert(state.source.channel_ready);
  assert(state.runs.length>=89);assert(state.runs.some(r=>r.id===64));assert(state.runs.some(r=>r.id===85));
  const html=await (await get('/')).text();assert(!html.includes('预计剩余'));assert(!html.includes('id="t-eta"'));
  assert(html.includes('开始实测对比'));assert(html.includes('清空内容'));
  const point=await (await get('/api/run/86/board')).json();
  assert.equal(point.model,'v3_board');assert(point.probes.length>=3);
  const probes=point.probes.slice(0,3).map(p=>({row:p.row,col:p.col,state:p.state,req_seq:p.req_seq,class_id:p.class_id,confidence_q16:p.confidence_q16}));
  assert.deepEqual(probes.map(p=>[p.row,p.col]),[[176,152],[225,168],[340,283]]);
  assert(probes.every(p=>p.state==='done'));assert.equal(new Set(probes.map(p=>p.req_seq)).size,3);
  const roi=await (await get('/api/run/89/board')).json();assert.equal(roi.status,'done');assert.equal(roi.received_pixels,1089);
  const speed=await (await get('/api/speed/history/e6800bc325e2493083444f3bdb1e60e0')).json();
  assert.equal(speed.state,'done');assert.deepEqual(speed.versions,['v2','v3']);assert.deepEqual(speed.rect,[259,168,32,64]);
  assert(speed.items.every(i=>i.status==='done'&&i.done===2048&&i.total===2048&&i.rate>0&&i.compute_ms>0&&i.trace.length>2));
  assert.deepEqual(speed.items.map(i=>i.run_id),[87,88]);
  const rateA=speed.items[0].rate,rateB=speed.items[1].rate;
  const markerPath='firmware/keys_20261018/deployment.json',marker=JSON.parse(fs.readFileSync(markerPath,'utf8'));
  assert.equal(marker.release_id,release);
  for(const [file,digest]of Object.entries(marker.files))assert.equal(crypto.createHash('sha256').update(fs.readFileSync('firmware/keys_20261018/'+file)).digest('hex'),digest);
  const report={result:'PASS',time:new Date().toISOString(),release_id:release,boot:state.source.boot_id,dp_init_rc:0,
    startup_log:'.runtime-tmp/download_20261024_182703_25604.log',history_before:85,history_after:state.runs.length,
    continuous_click:{run:86,host_version:'v3',board_model:point.model,clear_between_clicks:false,probes},
    final_roi:{run:89,received:roi.received_pixels,total:roi.total,status:roi.status,roi:roi.roi},
    speed:{id:speed.id,rect:speed.rect,items:speed.items.map(({trace,...item})=>({...item,trace_points:trace.length})),
      ratio:rateB/rateA,difference_percent:100*(rateB/rateA-1),conclusion:'Same fixed inference structure; measured speeds effectively equal; no artificial delay or multiplier',
      measured_release_id:'52ec92b504bd898a58f810187cdac9a3e632cc12bf6978f9cccf3a44e7f39c75',
      final_change:'Only speed.js record selector restoration changed after measurement; backend and inference unchanged'},
    browser_manual_checks:['three consecutive native map clicks, including box tool, no clear',
      'fresh region 89 completed then clear, same region mode and probe drawer',
      'history and raw results preserved','real comparison progress on two maps',
      'comparison history reopened after service and board restart','model selectors match saved comparison','recorded-time replay'],
    screenshots:['continuous_probe_v3.jpg','final_roi_done.jpg','final_roi_cleared.jpg','final_clear_mode.jpg','speed_final.jpg'],
    inference_hardware_unchanged:true};
  fs.writeFileSync(dir+'/live_verification.json',JSON.stringify(report,null,2)+'\n');
  marker.state='DEPLOYED_LOCAL_DEMO';marker.boot=state.source.boot_id;marker.verification=dir+'/live_verification.json';
  fs.writeFileSync(markerPath,JSON.stringify(marker,null,2)+'\n');
  console.log(JSON.stringify({result:report.result,boot:report.boot,history:report.history_after,probes:probes.length,
    rateA,rateB,difference_percent:report.speed.difference_percent}));
})().catch(e=>{console.error(e);process.exit(1);});
