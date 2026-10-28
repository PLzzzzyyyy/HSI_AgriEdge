'use strict';
// Exercise real page event handling without a browser, socket, or board task.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map(),loads=[],frames=[],probes=[];
const old={id:24,scene:'longkou',version:'v2',status:'stopped',source:'board'};
const S={runs:{},scene:'longkou',ledger:{},hidden:new Set()};
const element=id=>{if(!elements.has(id))elements.set(id,{style:{},hidden:false});return elements.get(id);};
let socket;
const helpers={};vm.runInNewContext(fs.readFileSync('gcs/web/core.js','utf8')+'\nglobalThis.taskRect=taskSelectionRect;',helpers);
const context={S,console,Map,Set,Promise,Date,JSON,
  taskSelectionRect:helpers.taskRect,
  $:element,location:{host:'test'},setInterval:()=>{},setTimeout:()=>{},
  fetch:async path=>({ok:true,json:async()=>path==='/api/state'?{source:{},scenes:['longkou','honghu'],runs:[old],run:old,
    key_context:{action:'point',state:'done',scene:'longkou',version:'v2',row:1,col:2,run:{...old,rect:[1,2,1,1]}}}:{} }),
  loadScene:async scene=>{S.scene=scene;S.keyScenePreview=false;S.runA=S.viewCleared?null:24;},
  loadRun:async id=>loads.push(id),toast:()=>{},logLine:()=>{},applyChunk:()=>{},
  MapView:{repaintAll:()=>{}},ConnectionPanel:{apply:()=>{}},
  BoardPanel:{source:()=>{},gate:()=>{},apply:(id,b)=>frames.push(id),probe:()=>probes.push(1),selectionChanged:()=>{}},
  Panels:{runState:()=>{},setKind:()=>{},runsTable:()=>{}},SpeedPanel:{update:()=>{}},
  WebSocket:class{constructor(){socket=this;}}
};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInNewContext(fs.readFileSync('gcs/web/app.js','utf8'),context);
  await flush();assert(socket);
  assert.equal(S.runA,null);assert.deepEqual(probes,[],'Reloading must not replay the old physical point command');
  socket.onmessage({data:JSON.stringify({type:'key_action',state:'done',action:'scene',scene:'honghu',version:'v1',event:{key:5}})});
  await flush();
  assert.equal(S.scene,'honghu');assert.equal(S.keyScenePreview,true);
  assert.equal(S.runA,null);assert.equal(element('#progress-txt').textContent,'等待新场景任务');
  assert.deepEqual(loads,[]);assert.deepEqual(frames,[]); // old task cannot become the new scene's result
  socket.onmessage({data:JSON.stringify({type:'key_action',state:'started',action:'region',scene:'honghu',version:'v1',event:{key:6},
    run:{id:25,scene:'honghu',kind:'region',rect:[1,2,3,4]}})});
  await flush();assert.equal(S.keyScenePreview,false);assert.equal(S.runA,25);
  assert.deepEqual(loads,[25]);assert.deepEqual(frames,[25]);
  console.log('KEY_SCENE_UI_PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
