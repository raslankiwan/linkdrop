const test=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
test('clear history removes finished/failed records and preserves active jobs',()=>{
  const records=[{id:'done',status:'complete',format:'mp4',title:'Done',fileUrl:'/api/file?ticket=x'},{id:'failed',status:'error',format:'mp3',title:'Failed'}];
  const nodes={};const node=id=>nodes[id]||=( {value:'',addEventListener(){}} );let stored;
  const context={document:{getElementById:node},localStorage:{getItem:()=>JSON.stringify(records),setItem:(k,v)=>stored=JSON.parse(v)},crypto:{randomUUID:()=> 'active'},fetch:()=>new Promise(()=>{})};
  vm.runInNewContext(fs.readFileSync('public/app.js','utf8'),context);
  node('url').value='https://example.com/video.mp4';node('url').reportValidity=()=>true;node('format').value='mp4';node('quality').value='best';
  node('download').onclick();assert.equal(stored.length,3);
  node('clear-history').onclick();assert.equal(stored.length,1);assert.equal(stored[0].id,'active');assert.equal(stored[0].status,'starting');
});
test('empty history renders an empty state after clearing',()=>{
  const nodes={};let stored;
  vm.runInNewContext(fs.readFileSync('public/app.js','utf8'),{document:{getElementById:id=>nodes[id]||=({addEventListener(){}})},localStorage:{getItem:()=>JSON.stringify([{id:'1',status:'error',format:'mp4'}]),setItem:(k,v)=>stored=JSON.parse(v)}});
  nodes['clear-history'].onclick();assert.equal(stored.length,0);assert.match(nodes.jobs.innerHTML,/Nothing here yet/);
});
