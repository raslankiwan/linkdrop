const test=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');const crypto=require('node:crypto');
function setup(){const module={exports:{}};let scoped;let copied;
vm.runInNewContext(fs.readFileSync('api/file.js','utf8'),{module,Buffer,URL,Date,Number,process:{env:{LINKDROP_SECRET:'test-secret'}},require:name=>name==='node:crypto'?crypto:{getDownloadUrl:url=>{const parsed=new URL(url);parsed.searchParams.set('download','1');return parsed.toString()},copy:async(from,to,options)=>{copied={from,to,options};return {pathname:to}},issueSignedToken:async d=>{scoped=d;return 'signed'},presignUrl:async()=>({presignedUrl:'https://private.example/signed'})}});
return {handler:module.exports,scope:()=>scoped,copied:()=>copied};}
function ticket(data){const p=Buffer.from(JSON.stringify(data)).toString('base64url');return p+'.'+crypto.createHmac('sha256','test-secret').update(p).digest('hex')}
function response(){return {headers:{},setHeader(k,v){this.headers[k]=v},end(v){this.body=v}}}
test('valid file ticket grants only its scoped private file',async()=>{const s=setup(),res=response();const pathname='downloads/'+ 'a'.repeat(32)+'/clip.mp4';await s.handler({url:'/api/file?ticket='+ticket({pathname,expires:Date.now()/1000+1000})},res);assert.equal(res.statusCode,302);assert.equal(s.scope().pathname,pathname);assert.deepEqual(Array.from(s.scope().operations),['get']);assert.equal(res.headers.Location,'https://private.example/signed?download=1')});
test('expired and tampered tickets are rejected',async()=>{for(const t of [ticket({pathname:'downloads/'+ 'a'.repeat(32)+'/clip.mp4',expires:1}),'fake.'+'a'.repeat(64)]){const res=response();await setup().handler({url:'/api/file?ticket='+t},res);assert.equal(res.statusCode,400)}});

test('legacy Arabic and emoji filenames migrate within the same job before signing',async()=>{
  for(const filename of ['لا تنسى الإعجاب 🌹💝.mp4','595K views Â· Ù„Ø§ ðŸŒ¹.mp4']){
    const s=setup(),res=response(),prefix='downloads/'+'b'.repeat(32)+'/';
    await s.handler({url:'/api/file?ticket='+ticket({pathname:prefix+filename,expires:Date.now()/1000+1000})},res);
    assert.equal(res.statusCode,302);assert.equal(s.copied().from,prefix+filename);
    assert.equal(s.copied().to,prefix+'media.mp4');assert.equal(s.copied().options.access,'private');
    assert.equal(s.scope().pathname,prefix+'media.mp4');assert.deepEqual(Array.from(s.scope().operations),['get']);
  }
});
test('an invalid ticket cannot trigger legacy blob migration',async()=>{
  const s=setup(),res=response();await s.handler({url:'/api/file?ticket=invalid.'+'0'.repeat(64)},res);
  assert.equal(res.statusCode,400);assert.equal(s.copied(),undefined);
});
