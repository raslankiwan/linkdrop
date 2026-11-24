const test=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
function setup(){
  const module={exports:{}};const calls={};
  const blob={issueSignedToken:async d=>{calls.scope=d;return 'signed'},presignUrl:async(t,o)=>{calls.presign=o;return {presignedUrl:'https://store.private.blob.vercel-storage.com/x?sig=1'}},del:async p=>{calls.deleted=p}};
  const client={handleUpload:async({body,onBeforeGenerateToken})=>{calls.token=await onBeforeGenerateToken(body.payload.pathname);return {type:'blob.generate-client-token',clientToken:'t'}}};
  vm.runInNewContext(fs.readFileSync('api/upload.js','utf8'),{module,Buffer,URL,Date,JSON,require:n=>n==='@vercel/blob/client'?client:blob});
  return {handler:module.exports,calls};
}
function req(body,headers={host:'linkdrop.test',origin:'https://linkdrop.test'}){return {method:'POST',headers,body}}
function res(){return {headers:{},setHeader(k,v){this.headers[k]=v},end(v){this.body=JSON.parse(v)}}}
const good='uploads/'+'c'.repeat(32)+'/Report-v2.pdf';
test('client upload tokens are limited to the uploads prefix and 200 MB',async()=>{
  const s=setup(),r=res();await s.handler(req({type:'blob.generate-client-token',payload:{pathname:good}}),r);
  assert.equal(r.statusCode,200);assert.equal(s.calls.token.maximumSizeInBytes,200*1024*1024);assert.equal(s.calls.token.allowOverwrite,false);
  for(const pathname of ['downloads/'+'c'.repeat(32)+'/x.pdf','uploads/../x.pdf','uploads/'+'c'.repeat(32)+'/a/b.pdf']){
    const bad=res();await setup().handler(req({type:'blob.generate-client-token',payload:{pathname}}),bad);assert.equal(bad.statusCode,400);
  }
});
test('source links are presigned for reading one upload only',async()=>{
  const s=setup(),r=res();await s.handler(req({action:'source',pathname:good}),r);
  assert.equal(r.statusCode,200);assert.match(r.body.url,/blob\.vercel-storage\.com/);
  assert.equal(s.calls.scope.pathname,good);assert.deepEqual(Array.from(s.calls.scope.operations),['get']);assert.equal(s.calls.presign.access,'private');
  const bad=res();await setup().handler(req({action:'source',pathname:'downloads/'+'a'.repeat(32)+'/media.mp4'}),bad);assert.equal(bad.statusCode,400);
});
test('cross-site requests are refused and uploads can be deleted',async()=>{
  const r=res();await setup().handler(req({action:'source',pathname:good},{host:'linkdrop.test',origin:'https://evil.test'}),r);assert.equal(r.statusCode,403);
  const s=setup(),d=res();await s.handler(req({action:'delete',pathname:good}),d);assert.equal(d.statusCode,200);assert.equal(s.calls.deleted,good);
});
