'use strict';
const assert=require('node:assert/strict');
const {fixture}=require('./test_cross_scene_probe');
const posts=f=>f.requests.filter(r=>r.options?.method==='POST');
(async()=>{
  const f=await fixture();
  await f.context.panel.probe(351,152);
  assert.equal(posts(f).length,1,'A map click submits exactly one request, including after HTTP adoption');
  assert.equal(f.element('#board-probe-run').hidden,true);
  await f.context.panel.probe(351,153);
  assert.equal(posts(f).length,2,'A subsequent click uses the existing task probe channel');
  assert.equal(posts(f)[1].url,'/api/run/29/board/probe');
  const selected=f.context.state.probe;
  await f.context.panel.probe(352,154);
  assert.equal(posts(f).length,2,'Queued probes block repeated clicks');
  assert.equal(f.context.state.probe,selected,'An in-flight result keeps its selected coordinates');

  const alias=await fixture('longkou','v3');
  await alias.context.panel.probe(351,152);
  alias.context.panel.apply(29,{...alias.context.state.runs[29].s.board,model:'v3_board'});
  await alias.context.panel.probe(351,153);
  assert.equal(posts(alias).length,2,'Host v3 and board v3_board refer to the same validated run');
  alias.context.panel.apply(29,{...alias.context.state.runs[29].s.board,interaction:{state:'open',probe:null}});
  await alias.context.panel.probe(352,154);
  assert.equal(posts(alias).length,3,'A third consecutive map click requires no clear action');

  const immediate=await fixture();
  const fetch=immediate.context.fetch;
  let finishInput;
  immediate.context.fetch=(url,opts)=>url.includes('input-point')?
    new Promise(resolve=>{finishInput=()=>resolve({ok:false,status:409,json:async()=>({detail:'fixture'})});}):fetch(url,opts);
  const pending=immediate.context.panel.probe(351,152);
  assert.equal(posts(immediate).length,1,'PL submission does not wait for the input preview');
  const point=immediate.context.state.probe;
  await immediate.context.panel.probe(352,153);
  assert.equal(posts(immediate).length,1,'HTTP submission ownership rejects rapid double clicks');
  assert.equal(immediate.context.state.probe,point);
  // Adoption refresh loads the preview again without resubmitting the probe.
  for(let n=0;n<8;n++){
    finishInput?.();await new Promise(resolve=>setImmediate(resolve));
  }
  await pending;
  assert.equal(posts(immediate).length,1);

  const disconnected=await fixture();
  disconnected.context.panel.gate({source:'board',authorized:false,active:false,channel_ready:false});
  await disconnected.context.panel.probe(351,152);
  assert.equal(posts(disconnected).length,0,'Disconnected clicks do not send device commands');
  const busy=await fixture('honghu','v1','running');
  await busy.context.panel.probe(351,152);
  assert.equal(posts(busy).length,0,'A different running task is preserved');
  console.log('CLICK_PROBE_PASS: automatic single request, warm reuse, race protection, immediate dispatch, disconnected/busy guards');
})().catch(error=>{console.error(error);process.exitCode=1;});
