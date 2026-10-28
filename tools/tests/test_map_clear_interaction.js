'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const events={},elements=new Map(),probes=[],rects=[];
function canvas(){const x={createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),putImageData(d){this.last=new Uint8Array(d.data);}};
  return {width:0,height:0,getContext:()=>x,getBoundingClientRect:()=>({left:0,top:0,width:500,height:500}),setPointerCapture(){},addEventListener:(k,fn)=>{events[k]=fn;}};}
function element(id){if(!elements.has(id))elements.set(id,id==='#map'?canvas():{style:{},addEventListener(){}});return elements.get(id);}
const S={W:10,H:10,gt:new Uint8Array(100),palRGB:[[0,0,0],[255,0,0]],view:{k:1,x:0,y:0},tool:'box',runs:{1:{s:{source:'board'},pred:new Uint8Array(100),conf:new Uint8Array(100),seen:new Uint8Array(100)}},runA:1,runB:null,hidden:new Set()};
const c={S,$:element,document:{createElement:canvas},window:{devicePixelRatio:1,addEventListener(){}},requestAnimationFrame(){},
  ResizeObserver:class{observe(){}},Panels:{cursor(){},probe:(r,c)=>probes.push([r,c]),setRect:r=>rects.push(r)}};
vm.createContext(c);vm.runInContext(fs.readFileSync('gcs/web/map.js','utf8')+'\nglobalThis.map=MapView;',c);c.map.resetScene();
S.view={k:10,x:0,y:0};
events.pointerdown({clientX:15,clientY:25,button:0,pointerId:1});events.pointerup({clientX:15,clientY:25,button:0});
assert.deepEqual(probes,[[2,1]],'A box-tool click without a drag is an automatic point probe');
events.pointerdown({clientX:15,clientY:25,button:0,pointerId:1});events.pointermove({clientX:45,clientY:55});events.pointerup({clientX:45,clientY:55,button:0});
assert.equal(probes.length,1,'Dragging a box must not submit a point');assert.equal(rects.length,1);
const run=S.runs[1];run.pred[0]=1;run.seen[0]=1;c.map.paintA(0);c.map.flush();
assert.equal(c.map.layer('pred').x.last[3],255);
S.runA=null;c.map.repaintAll();c.map.flush();
for(const layer of ['pred','conf','err','predB','diff'])assert(c.map.layer(layer).x.last.every(v=>v===0),layer+' cache cleared');
assert.equal(run.pred[0],1);assert.equal(run.seen[0],1,'Clearing a canvas must preserve historical data');
console.log('MAP_CLEAR_AND_CLICK_PASS: actual pixel caches transparent; box-click probes; drag only selects');
