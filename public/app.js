const $=id=>document.getElementById(id);
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const AUDIO=['mp3','m4a','wav','flac','opus'];
const KEY='linkdrop-history-v1';let metadata=null;let running=0;let jobs=[];
try{jobs=JSON.parse(localStorage.getItem(KEY)||'[]');if(!Array.isArray(jobs))jobs=[];jobs=jobs.filter(j=>j&&typeof j.id==='string').map(j=>['complete','error'].includes(j.status)?j:{...j,status:'error',error:'The page was closed before this download finished. Please try again.'})}catch{}
function persist(){try{localStorage.setItem(KEY,JSON.stringify(jobs.slice(0,100)))}catch{}}
function render(){
  persist();$('count').textContent=jobs.length?'('+jobs.length+')':'';
  $('clear-history').disabled=!jobs.some(j=>['complete','error'].includes(j.status));
  if(!jobs.length){$('jobs').innerHTML='<div class="empty">Nothing here yet. Your next great find goes here.</div>';return}
  $('jobs').innerHTML=jobs.map(j=>`<article class="job"><div class="jobtop"><div class="fileicon">${AUDIO.includes(j.format)?'♫':'▷'}</div><div class="jobinfo"><div class="title">${escape(j.title)}</div><div class="status">${escape(String(j.format).toUpperCase())} · ${escape(({processing:'Converting / merging…',uploading:'Securing your file…'})[j.status]||j.status)}${j.status==='downloading'?' · '+(j.progress||0)+'%':''}${j.size?' · '+(j.size/1048576).toFixed(1)+' MB':''}</div></div>${j.status==='complete'&&typeof j.fileUrl==='string'&&j.fileUrl.startsWith('/api/file?ticket=')?`<a class="save" href="${escape(j.fileUrl)}">Save file ↓</a>`:''}</div>${j.error?`<div class="error">${escape(j.error)}</div>`:''}${!['complete','error','queued'].includes(j.status)?`<div class="bar"><i style="width:${Math.max(3,Math.min(100,j.progress||0))}%"></i></div>`:''}</article>`).join('');
}
async function api(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const j=await r.json();if(!r.ok)throw Error(j.error||'Request failed');return j}
$('url').addEventListener('input',()=>{metadata=null;$('meta').hidden=true});
$('format').onchange=()=>{$('quality').disabled=AUDIO.includes($('format').value);$('download').textContent=AUDIO.includes($('format').value)?'↓  Download audio':'↓  Download video'};
$('inspect').onsubmit=async e=>{e.preventDefault();$('error').textContent='';$('analyze').disabled=true;$('analyze').textContent='Finding…';try{metadata=await api('/api/inspect',{action:'inspect',url:$('url').value});$('meta').hidden=false;$('meta').innerHTML=`<strong>${escape(metadata.title)}</strong><small>${escape(metadata.platform)}${metadata.uploader?' · '+escape(metadata.uploader):''}${metadata.duration?' · '+Math.floor(metadata.duration/60)+':'+String(Math.floor(metadata.duration%60)).padStart(2,'0'):''}</small>${metadata.heights?.length?'<small>Source resolutions: '+metadata.heights.map(h=>escape(h)+'p').join(', ')+'</small>':''}`}catch(e){$('error').textContent=e.message}finally{$('analyze').disabled=false;$('analyze').textContent='Find video ↗'}};
async function execute(job){
  running++;job.status='starting';render();let terminal=false;
  try {
    const r=await fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'download',url:job.url,format:job.format,quality:job.quality})});
    if(!r.ok){let msg;try{msg=(await r.json()).error}catch{}throw Error(msg||'The server could not start this download.')}
    if(!r.body)throw Error('Streaming is unavailable in this browser.');
    const reader=r.body.getReader();const decoder=new TextDecoder();let pending='';
    function consume(line){if(!line.trim())return;const event=JSON.parse(line);Object.assign(job,event);if(['complete','error'].includes(event.status))terminal=true;render()}
    while(true){const {value,done}=await reader.read();if(done)break;pending+=decoder.decode(value,{stream:true});let index;while((index=pending.indexOf('\n'))!==-1){consume(pending.slice(0,index));pending=pending.slice(index+1)}}
    pending+=decoder.decode();if(pending.trim())consume(pending);
    if(!terminal)throw Error('Connection ended before completion. Try lower quality, or use the local app for large files.');
  }catch(e){job.status='error';job.error=e.message}
  finally{running--;render();drain()}
}
function drain(){while(running<2){const job=jobs.find(j=>j.status==='queued');if(!job)break;execute(job)}}
$('download').onclick=()=>{if(!$('url').value||!$('url').reportValidity())return;$('error').textContent='';if(jobs.filter(j=>!['complete','error'].includes(j.status)).length>=10){$('error').textContent='Queue is full. Wait for a download to finish.';return}jobs.unshift({id:crypto.randomUUID(),url:$('url').value,title:metadata?.title||$('url').value,format:$('format').value,quality:$('quality').value,status:'queued',progress:0});render();drain()};
$('clear-history').onclick=()=>{jobs=jobs.filter(j=>!['complete','error'].includes(j.status));render()};
render();
