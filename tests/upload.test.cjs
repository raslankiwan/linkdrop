const test=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
function setup(){
  const module={exports:{}};const calls={put:[],scopes:[],deleted:null};
  const blob={
    put:async(pathname,body,options)=>{calls.put.push({pathname,bytes:body.length,options});return {pathname}},
    issueSignedToken:async d=>{calls.scopes.push(d);return 'signed'},
    presignUrl:async(t,o)=>({presignedUrl:`https://store.private.blob.vercel-storage.com/${o.pathname}?sig=1`}),
    del:async p=>{calls.deleted=p}
  };
  vm.runInNewContext(fs.readFileSync('api/upload.js','utf8'),{module,Buffer,URL,Date,JSON,Array,String,Number,Error,setTimeout,require:()=>blob});
  return {handler:module.exports,calls};
}
const host={host:'linkdrop.test',origin:'https://linkdrop.test'};
function req(url,body,headers={}){return {method:'POST',url,headers:{...host,...headers},body}}
function res(){return {headers:{},setHeader(k,v){this.headers[k]=v},end(v){this.body=JSON.parse(v)}}}
const id='c'.repeat(32);
test('parts are stored privately under the upload id and limited to 4 MB',async()=>{
  const s=setup(),r=res();
  await s.handler(req(`/api/upload?id=${id}&part=3`,Buffer.alloc(1000),{'content-type':'application/octet-stream'}),r);
  assert.equal(r.statusCode,200);assert.equal(s.calls.put[0].pathname,`uploads/${id}/part-0003`);assert.equal(s.calls.put[0].options.access,'private');
  const big=res();await setup().handler(req(`/api/upload?id=${id}&part=0`,Buffer.alloc(4000001),{'content-type':'application/octet-stream'}),big);assert.equal(big.statusCode,400);
  for(const url of [`/api/upload?id=../x&part=0`,`/api/upload?id=${id}&part=50`,`/api/upload?id=${id}&part=-1`]){
    const bad=res();await setup().handler(req(url,Buffer.alloc(10),{'content-type':'application/octet-stream'}),bad);assert.equal(bad.statusCode,400,url);
  }
});
test('source returns one read-only presigned URL per part',async()=>{
  const s=setup(),r=res();await s.handler(req('/api/upload',{action:'source',id,parts:2}),r);
  assert.equal(r.statusCode,200);assert.equal(r.body.urls.length,2);assert.match(r.body.urls[1],/part-0001/);
  assert.deepEqual(Array.from(s.calls.scopes[0].operations),['get']);
  const bad=res();await setup().handler(req('/api/upload',{action:'source',id,parts:51}),bad);assert.equal(bad.statusCode,400);
});
test('cross-site requests are refused and parts can be deleted',async()=>{
  const r=res();await setup().handler(req('/api/upload',{action:'source',id,parts:1},{origin:'https://evil.test'}),r);assert.equal(r.statusCode,403);
  const s=setup(),d=res();await s.handler(req('/api/upload',{action:'delete',id,parts:2}),d);
  assert.equal(d.statusCode,200);assert.deepEqual(Array.from(s.calls.deleted),[`uploads/${id}/part-0000`,`uploads/${id}/part-0001`]);
});
