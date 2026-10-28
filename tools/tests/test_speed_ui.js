'use strict';
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const elements=new Map();
function element(id){
  if(!elements.has(id))elements.set(id,{value:id==='#speed-clock'?'compute':'',width:640,height:270,children:[],classList:{toggle(){}},
    append(o){this.children.push(o);if(!this.value)this.value=o.value;},replaceChildren(){this.children=[];this.value='';},
    getContext:()=>({clearRect(){},fillRect(){},drawImage(){},strokeRect(){},beginPath(){},moveTo(){},lineTo(){},stroke(){}})});
  return elements.get(id);
}
const S={H:550,W:400,scene:'longkou',version:'v2',source:{channel_ready:true},info:{versions:[{id:'v2',pkg:'v2',label:'V2'},{id:'v3',pkg:'v3',label:'V3'}]},runs:{}};
const context={S,$:element,Set,console,Panels:{tab:'speed'},document:{createElement:()=>({})},MapView:{resize(){}},
  fmt:{n:v=>String(v),f:(v,d)=>v==null?'—':v.toFixed(d),pct:v=>(v*100).toFixed(1)+'%'},
  cancelAnimationFrame(){},requestAnimationFrame(){},performance:{now:()=>0},clsColor:()=>'',toast(){}};
vm.createContext(context);vm.runInContext(fs.readFileSync('gcs/web/speed.js','utf8')+'\nglobalThis.panel=SpeedPanel;',context);
context.panel.configure();assert.equal(element('#speed-a').value,'v2');assert.equal(element('#speed-b').value,'v3');
const data={id:'sample',scene:'longkou',rect:[0,0,32,64],versions:['v2','v3'],state:'done',phase:1,items:[
  {version:'v2',run_id:1,done:500,total:500,rate:250,ms_per_pixel:4,elapsed_s:3,compute_ms:2000,trace:[{compute_ms:0,done:0},{compute_ms:1000,done:250},{compute_ms:2000,done:500}]},
  {version:'v3',run_id:2,done:500,total:500,rate:200,ms_per_pixel:5,elapsed_s:4,compute_ms:2500,trace:[{compute_ms:0,done:0},{compute_ms:1000,done:200},{compute_ms:2500,done:500}]}
]};
context.panel.update(data);context.panel.render(1000);
assert.equal(element('#speed-b').value,'v3','Restored controls must match the recorded result, not a default model');
assert.match(element('#speed-value-a').textContent,/250 \/ 500/);assert.match(element('#speed-value-b').textContent,/200 \/ 500/);
assert.match(element('#speed-delta').textContent,/0.8000×.*慢 20.000%/);
context.panel.clear();context.panel.update(data);
assert.equal(element('#speed-delta').textContent,'—');assert.equal(context.panel.allowRun({origin:'speed:sample'}),false);
assert.equal(context.panel.allowRun({origin:'speed:new'}),true);
assert.equal(S.speedComparison,data,'Clearing the view does not mutate the running comparison');
assert.equal(data.items[0].trace[1].done,250);
console.log('SPEED_UI_PASS: recorded-time progress, measured ratios and cleared-view isolation');
