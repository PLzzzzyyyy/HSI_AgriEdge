'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={document:{querySelector:()=>null},console};
vm.createContext(context);vm.runInContext(fs.readFileSync('gcs/web/core.js','utf8'),context);
const mapping=JSON.parse(fs.readFileSync('gcs/class_labels_zh.json','utf8'));
for(const scene of ['longkou','honghu','hanchuan']){
  const rows=mapping.scenes[scene],raw=rows.map(c=>c.name_en),names=rows.map(c=>c.name_zh);
  context.testInfo={classes:raw,display_classes:names,palette:['#000000',...rows.map(c=>c.color)]};
  vm.runInContext('S.info=testInfo',context);
  const actual=Array.from(vm.runInContext('classNames()',context));
  assert.deepEqual(actual,names);
  for(let i=0;i<rows.length;i++)assert.equal(vm.runInContext(`clsColor(${i+1})`,context),rows[i].color);
  assert.equal(vm.runInContext('clsName(0)',context),'无');
  assert.equal(vm.runInContext('clsName(255)',context),'类别 254');
}
for(const file of ['panels.js','evaluation.js','loop.js']){
  const source=fs.readFileSync('gcs/web/'+file,'utf8');
  assert(!/data:\s*S\.info\.classes\b/.test(source),file+' has a raw English chart axis');
  assert(source.includes('classNames()'),file+' must use checked Chinese names');
}
console.log('PC_CLASS_NAMES_PASS: all 47 labels, original colors, probability/evaluation/loop axes');
