const test=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const helper=fs.readFileSync('public/auto-save.js','utf8');
function browser(extra={}){
  const nodes={},frames=[];const node=id=>nodes[id]||=({value:'',addEventListener(){},reportValidity:()=>true});
  const context=vm.createContext({URLSearchParams,TextDecoder,document:{getElementById:node,createElement:tag=>({tag}),body:{appendChild:frame=>frames.push(frame)}},localStorage:{getItem:()=>null,setItem(){}},...extra});
  vm.runInContext(helper,context);return {context,node,frames};
}
test('delivery requests once per job and cannot navigate to arbitrary URLs',()=>{
  const b=browser();const delivery=b.context.LinkDropAutoSave;
  assert.equal(delivery.request('one','/api/file?ticket=signed'),true);
  assert.equal(delivery.request('one','/api/file?ticket=signed'),false);
  assert.equal(delivery.request('bad','https://example.com'),false);
  assert.equal(b.frames.length,1);assert.equal(b.frames[0].hidden,true);
});
test('cloud completion automatically requests delivery once, without a save click',async()=>{
  const bytes=new TextEncoder().encode([1,2].map(()=>JSON.stringify({status:'complete',fileUrl:'/api/file?ticket=signed',size:123})).join('\n')+'\n');
  const b=browser({crypto:{randomUUID:()=> 'new'},fetch:async()=>({ok:true,body:{getReader(){let read=false;return {read:async()=>read?{done:true}:(read=true,{done:false,value:bytes})}}}})});
  vm.runInContext(fs.readFileSync('public/app.js','utf8'),b.context);
  b.node('url').value='https://example.com/video.mp4';b.node('format').value='mp4';b.node('quality').value='best';b.node('download').onclick();
  await new Promise(setImmediate);
  assert.equal(b.frames.length,1);assert.equal(b.frames[0].src,'/api/file?ticket=signed');assert.match(b.node('jobs').innerHTML,/Download requested/);assert.match(b.node('jobs').innerHTML,/Download again/);
});
test('history reload does not automatically save old completed files',()=>{
  const b=browser({localStorage:{getItem:()=>JSON.stringify([{id:'old',status:'complete',format:'mp4',fileUrl:'/api/file?ticket=old'}]),setItem(){}}});
  vm.runInContext(fs.readFileSync('public/app.js','utf8'),b.context);assert.equal(b.frames.length,0);
});
test('local polling saves only jobs submitted in this tab, once',async()=>{
  const id='a'.repeat(32);let poll;
  const b=browser({location:{hash:'',pathname:'/'},setInterval:fn=>poll=fn,fetch:async path=>({ok:true,json:async()=>path==='/api/download'?{id}:{jobs:[{id,status:'complete',format:'mp4',title:'New'},{id:'b'.repeat(32),status:'complete',format:'mp4',title:'Old'}]}})});
  const script=fs.readFileSync('index.html','utf8').split('<script>')[1].split('</script>')[0];
  vm.runInContext(script,b.context);b.node('url').value='https://example.com/video.mp4';b.node('format').value='mp4';b.node('quality').value='best';
  await b.node('download').onclick();await poll();await poll();
  assert.equal(b.frames.length,1);assert.equal(b.frames[0].src,'/file/'+id);
});
