'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function fixture(scene='honghu',version='v1',status='done',transport=null){
  const elements=new Map(),requests=[];
  function element(key){
    if(!elements.has(key))elements.set(key,{style:{},dataset:{},classList:{toggle(){}},children:[],value:'v1',selectedOptions:[{}],
      nextElementSibling:{},parentElement:{},setAttribute(){},append(...items){this.children.push(...items);},replaceChildren(){this.children=[];},
      appendChild(item){this.children.push(item);return item;},
      querySelector(selector){
        const match=selector.match(/^\[data-([a-z-]+)(?:="([^"]*)")?\]$/);if(!match)return null;
        const key=match[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
        return this.children.find(e=>e.dataset&&key in e.dataset&&(match[2]===undefined||e.dataset[key]===match[2]))||null;
      },getContext(){return {fillRect(){},strokeRect(){},drawImage(){}};}});
    return elements.get(key);
  }
  const doc={querySelector:element,querySelectorAll:()=>[],createElement:()=>element(Symbol()),createTextNode:text=>({textContent:text})};
  const noop=()=>{};
  const panels=new Proxy({charts:{},chart:()=>({setOption:noop,clear:noop})},{get:(o,k)=>o[k]||noop});
  const context={console,document:doc,setTimeout:noop,clearTimeout:noop,AbortController,
    TimingPanel:{select:noop},Panels:panels,MapView:{dirty:noop,repaintAll:noop,paintA:noop,paintB:noop},Loop:{gate:noop},
    fetch:async(url,options)=>{
      requests.push({url,options});
      if(url==='/web/longkou_v2_classes.json')return {json:async()=>({})};
      if(url.includes('input-point'))return {ok:false,status:409,json:async()=>({detail:'Input not needed by this test'})};
      if(transport)return transport(url,options);
      if(url==='/api/board/point-probe')return {ok:true,json:async()=>({run:{id:29,scene,version,source:'board',kind:'region',rect:[351,152,1,1],status:'done'},probe:{state:'queued'}})};
      if(url==='/api/run/29/board/probe')return {ok:true,json:async()=>({state:'queued',row:351,col:153,req_seq:8})};
      if(url==='/api/run/29/board')return {ok:true,json:async()=>({scene,model:version,task_lifecycle:true,full_scene:false,roi:{x:152,y:351,width:1,height:1},total:1,
        status:'done',received_pixels:1,ack:true,start_seq:1,interaction:{state:'open',probe:null},cells:[]})};
      throw Error('Unexpected request '+url);
    }
  };
  vm.createContext(context);vm.runInContext(fs.readFileSync('gcs/web/core.js','utf8')+'\nglobalThis.state=S;',context);
  Object.assign(context.state,{scene,version,H:940,W:475,info:{classes:Array(22).fill('raw'),display_classes:Array(22).fill('中文类别')},
    source:{source:'board'},live:28,runs:{28:{s:{id:28,scene:'longkou',version:'v2',source:'board',status}}}});
  context.loadRun=async id=>{context.state.runs[id].loaded=true;};
  vm.runInContext(fs.readFileSync('gcs/web/board.js','utf8')+'\nglobalThis.panel=BoardPanel;',context);
  context.panel.gate({source:'board',authorized:true,active:true,channel_ready:true,task_lifecycle:true,capabilities:{models:true},model_operation:{state:'done'}});
  await flush();context.panel.selectionChanged();
  return {context,requests,element,scene,version};
}
module.exports={fixture};
if(require.main===module)(async()=>{
  const f=await fixture();await f.context.panel.probe(351,152);
  assert.equal(f.element('#board-probe-run').disabled,false,'Cross-scene point must create a new task');
  assert.equal(f.element('#board-probe-run').hidden,true,'Map selection replaces the send button');
  // Deliberately deliver the HTTP response before any WebSocket run_start.
  const request=f.requests.find(r=>r.url==='/api/board/point-probe');assert(request);
  assert.deepEqual(JSON.parse(request.options.body),{row:351,col:152,scene:'honghu',version:'v1',confirmed:true});
  assert.equal(f.context.state.live,29);assert.equal(f.context.state.runA,29);
  assert.equal(f.context.state.runs[28].s.scene,'longkou');assert.equal(f.context.state.runs[28].s.status,'done');
  await f.context.panel.probe(351,153);
  assert(f.requests.some(r=>r.url==='/api/run/29/board/probe'),'Same scene/model must reuse the independent probe channel');
  const busy=await fixture('honghu','v1','running');await busy.context.panel.probe(351,152);
  assert.equal(busy.element('#board-probe-run').disabled,true);assert.match(busy.element('#board-probe-state').textContent,/尚未结束/);
  assert(!busy.requests.some(r=>r.options?.method==='POST'));
  const model=await fixture('longkou','v3_board');await model.context.panel.probe(351,152);
  assert.equal(model.element('#board-probe-run').disabled,false,'New selected model must not probe old v2 task');
  model.context.panel.apply(28,{scene:'longkou',model:'v2'});
  assert.equal(model.element('#board-probe-run').disabled,false,'Late old-model update must not replace selection binding');
  const body=JSON.parse(model.requests.find(r=>r.url==='/api/board/point-probe').options.body);
  assert.equal(body.version,'v3_board');assert.equal(body.scene,'longkou');
  const selected=await fixture();selected.context.state.keyScenePreview=true;
  await selected.context.panel.probe(351,152);assert(selected.requests.some(r=>r.options?.method==='POST'));
  console.log('CROSS_SCENE_PROBE_PASS: new scene/model, busy rejection, history retention, HTTP-before-WebSocket adoption');
})().catch(e=>{console.error(e);process.exitCode=1;});
