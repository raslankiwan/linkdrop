import base64, hashlib, hmac, json, mimetypes, os, re, signal, subprocess, sys, tempfile, threading, time
from pathlib import Path
from urllib.parse import unquote, urlparse
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from vercel.blob import sync as blob
from lib.engine import FORMATS, QUALITY, public_url
from lib.errors import download_error
from lib.storage import named_path, storage_path
from lib import convert as converter

app=FastAPI()
ROOT=Path(__file__).resolve().parents[1]
MAX_BYTES=200*1024*1024
DIRECT_UPLOAD_BYTES=4*1024*1024  # Vercel caps function request bodies at 4.5 MB.
NO_STORE={'Cache-Control':'no-store'}

def ticket(pathname):
    payload=base64.urlsafe_b64encode(json.dumps({'pathname':pathname,'expires':int(time.time())+86400}).encode()).decode().rstrip('=')
    signature=hmac.new(os.environ['LINKDROP_SECRET'].encode(),payload.encode(),hashlib.sha256).hexdigest()
    return '/api/file?ticket='+payload+'.'+signature

def events(data,worker='engine.py',upload=None):
    proc=None
    timer=None
    try:
        yield json.dumps({'status':'starting','progress':0})+'\n'
        with tempfile.TemporaryDirectory(prefix='linkdrop-') as folder:
            data['folder']=folder
            if upload is not None:
                source=Path(folder)/('source.'+(converter.extension(data['filename']) or 'bin'))
                source.write_bytes(upload);data['input']=str(source)
            proc=subprocess.Popen([sys.executable,str(ROOT/'lib'/worker)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL,text=True,start_new_session=True,env={**os.environ,'PYTHONPATH':os.pathsep.join(sys.path)})
            def kill():
                try: os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError: pass
            timer=threading.Timer(245,kill);timer.start()
            proc.stdin.write(json.dumps(data)+'\n');proc.stdin.close()
            result=None
            for line in proc.stdout:
                event=json.loads(line)
                if event.get('status')=='uploading': result=event
                else: yield line
            code=proc.wait()
            if code or not result:
                if code<0: yield json.dumps({'status':'error','error':'This job exceeded the hosted time limit (about 4 minutes). Try a smaller file or use the desktop app.'})+'\n'
                return
            yield json.dumps({'status':'uploading','progress':100})+'\n'
            file=Path(result.pop('path',None) or Path(folder)/result['filename'])
            pathname=named_path(result['filename']) if worker=='convert.py' else storage_path(file.name)
            with file.open('rb') as body:
                saved=blob.put_blob(pathname,body,access='private',content_length=result['size'],content_type=mimetypes.guess_type(result['filename'])[0] or 'application/octet-stream')
            yield json.dumps({**result,'status':'complete','progress':100,'fileUrl':ticket(saved.pathname)})+'\n'
    except GeneratorExit: raise
    except Exception as exc:
        yield json.dumps({'status':'error','error':str(exc)[:1200]})+'\n'
    finally:
        if timer: timer.cancel()
        if proc and proc.poll() is None:
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass

def same_origin(request):
    origin=request.headers.get('origin')
    return not origin or origin.rstrip('/')==str(request.base_url).rstrip('/')

def stream(data,worker,upload=None):
    return StreamingResponse(events(data,worker,upload),media_type='application/x-ndjson',headers={**NO_STORE,'X-Accel-Buffering':'no'})

async def convert(request):
    """Upload (raw body, small files), blob upload (presigned URL) or any public link -> convert -> private download."""
    if not os.environ.get('LINKDROP_SECRET'): raise ValueError('Cloud conversion is not configured.')
    if request.headers.get('content-type','').startswith('application/octet-stream'):
        filename=unquote(request.headers.get('x-filename',''))
        data={'filename':Path(filename).name[:160] or 'file','target':request.headers.get('x-target','')}
        if int(request.headers.get('content-length') or 0)>DIRECT_UPLOAD_BYTES: raise ValueError('Upload too large for a direct request.')
        body=await request.body()
        if len(body)>DIRECT_UPLOAD_BYTES: raise ValueError('Upload too large for a direct request.')
    else:
        raw=await request.body()
        if len(raw)>8192: raise ValueError('Request too large.')
        payload=json.loads(raw); body=None
        url=payload.get('sourceUrl')
        if payload.get('source')=='upload' and not (isinstance(url,str) and urlparse(url).scheme=='https' and (urlparse(url).hostname or '').endswith('.blob.vercel-storage.com')):
            raise ValueError('Invalid upload reference.')
        public_url(url)
        data={'sourceUrl':url,'target':payload.get('target',''),'filename':Path(str(payload.get('filename') or '')).name[:160] or None}
    target=str(data['target'] or '').lower()
    if target!='original':
        ext=converter.extension(data.get('filename') or '')
        if ext and target not in converter.targets(ext): raise ValueError(f'Converting .{ext} to .{target} is not supported here.')
        if not ext and data.get('sourceUrl') is None: raise ValueError('The file needs an extension so its type can be detected.')
    data.update(target=target,maxBytes=MAX_BYTES,timeout=225)
    return stream(data,'convert.py',body)

def capabilities():
    return JSONResponse({**converter.capabilities(),'maxBytes':MAX_BYTES,'directUploadBytes':DIRECT_UPLOAD_BYTES,'maxSeconds':245},headers={'Cache-Control':'public, max-age=300'})

@app.post('/{path:path}')
async def handler(request:Request):
    try:
        if not same_origin(request): return JSONResponse({'error':'Cross-site requests are not allowed.'},403)
        if request.url.path.endswith('/convert'): return await convert(request)
        raw=await request.body()
        if len(raw)>8192: raise ValueError('Request too large.')
        data=json.loads(raw)
        public_url(data.get('url'))
        if request.url.path.endswith('/inspect') or data.get('action')=='inspect':
            data['action']='inspect'
            result=subprocess.run([sys.executable,str(ROOT/'lib'/'engine.py')],input=json.dumps(data)+'\n',text=True,capture_output=True,timeout=55,env={**os.environ,'PYTHONPATH':os.pathsep.join(sys.path)})
            rows=[json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            if result.returncode:
                return JSONResponse(rows[-1] if rows else download_error('Cannot inspect this video.'),400,headers=NO_STORE)
            return JSONResponse(rows[-1],headers=NO_STORE)
        if data.get('format') not in FORMATS or data.get('quality') not in QUALITY: raise ValueError('Unsupported format or quality.')
        if not os.environ.get('LINKDROP_SECRET'): raise ValueError('Cloud downloads are not configured.')
        data['action']='download'
        return stream(data,'engine.py')
    except subprocess.TimeoutExpired: return JSONResponse({'error':'The source took too long to respond. Try another link.'},504)
    except Exception as exc: return JSONResponse({'error':str(exc)[:1200]},400)

@app.get('/{path:path}')
def health(path:str):
    if path.rstrip('/').endswith('capabilities'): return capabilities()
    return {'status':'ok','engine':'yt-dlp','limitMB':200,'maxSeconds':245}
