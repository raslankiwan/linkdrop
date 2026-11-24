// "Convert any file" panel shared by the web app and the desktop app.
// The page passes onSubmit(spec) where spec is {kind:'upload', file, target}
// or {kind:'link', url, target}; target 'original' means download as-is.
(function(root){
  const LABELS={pdf:'PDF document',docx:'Word document',odt:'OpenDocument text',rtf:'Rich text',txt:'Plain text',md:'Markdown',html:'Web page (HTML)',
    pptx:'PowerPoint',odp:'OpenDocument slides',xlsx:'Excel workbook',ods:'OpenDocument sheet',csv:'CSV',tsv:'TSV',json:'JSON',yaml:'YAML',
    png:'PNG image',jpg:'JPG image',webp:'WebP image',gif:'GIF (animated)',bmp:'BMP image',tiff:'TIFF image',ico:'Icon (ICO)',
    mp4:'MP4 video',mkv:'MKV video',webm:'WebM video',mov:'MOV video',avi:'AVI video',mp3:'MP3 audio',m4a:'M4A audio',wav:'WAV audio',
    flac:'FLAC audio',opus:'Opus audio',ogg:'Ogg Vorbis audio',aac:'AAC audio',zip:'ZIP archive',tar:'TAR archive','tar.gz':'TAR.GZ archive',
    'tar.bz2':'TAR.BZ2 archive','tar.xz':'TAR.XZ archive'};
  const NORMAL={jpeg:'jpg',jfif:'jpg',htm:'html',markdown:'md',yml:'yaml',tif:'tiff',tgz:'tar.gz',tbz2:'tar.bz2',txz:'tar.xz',aif:'aiff',oga:'ogg'};
  function extension(name){
    const lower=String(name||'').toLowerCase().split(/[?#]/)[0];
    const compound=/\.(tar\.(?:gz|bz2|xz))$/.exec(lower);if(compound)return compound[1];
    const m=/\.([a-z0-9]{1,10})$/.exec(lower);const ext=m?m[1]:'';return NORMAL[ext]||ext;
  }
  function linkExtension(url){try{return extension(decodeURIComponent(new URL(url).pathname.split('/').pop()))}catch{return ''}}
  function mb(bytes){return bytes>=1048576?(bytes/1048576).toFixed(bytes>=10485760?0:1)+' MB':Math.max(1,Math.round(bytes/1024))+' KB'}

  root.LinkDropConvert={extension,init(options){
    const $=id=>document.getElementById(id);
    let caps={formats:{}},mode='upload',file=null;
    const fileInput=$('file-input'),drop=$('drop'),target=$('target'),go=$('convert'),hint=$('convert-hint'),error=$('convert-error'),url=$('file-url');
    function setError(message){error.textContent=message||''}
    function fill(ext){
      const list=(caps.formats[ext]||[]);const previous=target.value;target.innerHTML='';
      if(mode==='link')target.add(new Option('Original file · no conversion','original'));
      for(const t of list)target.add(new Option(`${t.toUpperCase()} · ${LABELS[t]||t}`,t));
      if([...target.options].some(o=>o.value===previous))target.value=previous;
      const empty=!target.options.length;
      if(empty)target.add(new Option(file?'No conversions for this file type':'Choose a file first',''));
      target.disabled=empty;
      go.disabled=mode==='upload'?!file||!list.length:!url.value;
      go.textContent=mode==='link'&&target.value==='original'?'↓  Download file':'⇄  Convert & download';
    }
    function describe(){
      if(mode==='link'){
        const ext=linkExtension(url.value);fill(ext);
        hint.textContent=ext&&!(caps.formats[ext]||[]).length?`.${ext} files download as-is.`:`Any public file link. Up to ${mb(options.maxBytes())} on this ${options.place}.`;
        return;
      }
      if(!file){fill('');drop.querySelector('.drop-label').innerHTML='<b>Drop a file here</b> or <u>browse</u>';hint.textContent=summary();return}
      const ext=extension(file.name);
      drop.querySelector('.drop-label').innerHTML=`<b>${escapeHtml(file.name)}</b> · ${mb(file.size)} <u>change</u>`;
      if(file.size>options.maxBytes()){fill('');hint.textContent='';setError(`This file is ${mb(file.size)}. The limit here is ${mb(options.maxBytes())}.${options.place==='web'?' Use the desktop app for larger files.':''}`);go.disabled=true;return}
      fill(ext);
      hint.textContent=(caps.formats[ext]||[]).length?'Choose the format you want.':`.${ext||'?'} files can't be converted ${options.place==='web'?'on the web':'here'} yet.${!caps.office&&['doc','odt','rtf','pptx','ppt','odp','xls','ods','pages','key','numbers','epub'].includes(ext)?' Office formats need the desktop app with LibreOffice installed.':''}`;
    }
    function summary(){
      const n=Object.keys(caps.formats).length;
      return `${n} input types: video, audio, images, PDF, Word, Markdown, HTML, spreadsheets & data, archives${caps.office?', and Office documents':''}. Up to ${mb(options.maxBytes())}.`;
    }
    function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
    function pick(f){setError('');file=f||null;describe()}
    for(const button of document.querySelectorAll('[data-convert-mode]'))button.onclick=()=>{
      mode=button.dataset.convertMode;setError('');
      for(const b of document.querySelectorAll('[data-convert-mode]'))b.setAttribute('aria-pressed',String(b===button));
      drop.hidden=mode!=='upload';url.hidden=mode!=='link';describe();if(mode==='link')url.focus();
    };
    drop.onclick=()=>fileInput.click();
    drop.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();fileInput.click()}};
    fileInput.onchange=()=>pick(fileInput.files[0]);
    drop.ondragover=e=>{e.preventDefault();drop.classList.add('over')};
    drop.ondragleave=()=>drop.classList.remove('over');
    drop.ondrop=e=>{e.preventDefault();drop.classList.remove('over');pick(e.dataTransfer.files[0])};
    url.oninput=()=>{setError('');describe()};
    target.onchange=()=>describe();
    go.onclick=async()=>{
      setError('');
      try{
        if(mode==='upload'){if(!file)return;await options.onSubmit({kind:'upload',file,target:target.value});file=null;fileInput.value='';describe()}
        else{if(!url.reportValidity()||!url.value)return;await options.onSubmit({kind:'link',url:url.value,target:target.value||'original'});url.value='';describe()}
      }catch(e){setError(e.message)}
    };
    fetch('/api/capabilities').then(r=>r.json()).then(c=>{caps=c;options.onCapabilities&&options.onCapabilities(c);describe()}).catch(()=>{hint.textContent='Could not load supported formats. Reload to try again.'});
    describe();
  }};
})(globalThis);
