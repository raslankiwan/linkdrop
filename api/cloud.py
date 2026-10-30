import base64, hashlib, hmac, json, mimetypes, os, signal, subprocess, sys, tempfile, threading, time, uuid
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from vercel.blob import sync as blob
from lib.engine import FORMATS, QUALITY, public_url

app=FastAPI()
ROOT=Path(__file__).resolve().parents[1]

def events(data):
    proc=None
    timer=None
    try:
        yield json.dumps({'status':'starting','progress':0})+'\n'
        with tempfile.TemporaryDirectory(prefix='linkdrop-') as folder:
            data['folder']=folder
            proc=subprocess.Popen([sys.executable,str(ROOT/'lib'/'engine.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
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
                if code<0: yield json.dumps({'status':'error','error':'This download exceeded the hosted time limit (about 4 minutes). Try a lower quality or use the local app.'})+'\n'
                return
            yield json.dumps({'status':'uploading','progress':100})+'\n'
            file=Path(folder)/result['filename']
            pathname=f'downloads/{uuid.uuid4().hex}/{file.name}'
            with file.open('rb') as body:
                saved=blob.put_blob(pathname,body,access='private',content_length=result['size'],content_type=mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            payload=base64.urlsafe_b64encode(json.dumps({'pathname':saved.pathname,'expires':int(time.time())+86400}).encode()).decode().rstrip('=')
            signature=hmac.new(os.environ['LINKDROP_SECRET'].encode(),payload.encode(),hashlib.sha256).hexdigest()
            yield json.dumps({**result,'status':'complete','progress':100,'fileUrl':'/api/file?ticket='+payload+'.'+signature})+'\n'
    except GeneratorExit: raise
    except Exception as exc:
        yield json.dumps({'status':'error','error':str(exc)[:1200]})+'\n'
    finally:
        if timer: timer.cancel()
        if proc and proc.poll() is None:
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass

@app.post('/{path:path}')
async def handler(request:Request):
    try:
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
            return JSONResponse({'error':'Cross-site requests are not allowed.'},403)
        raw=await request.body()
        if len(raw)>8192: raise ValueError('Request too large.')
        data=json.loads(raw)
        public_url(data.get('url'))
        if request.url.path.endswith('/inspect') or data.get('action')=='inspect':
            data['action']='inspect'
            result=subprocess.run([sys.executable,str(ROOT/'lib'/'engine.py')],input=json.dumps(data)+'\n',text=True,capture_output=True,timeout=55,env={**os.environ,'PYTHONPATH':os.pathsep.join(sys.path)})
            rows=[json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            if result.returncode: raise ValueError(rows[-1].get('error','Cannot inspect this video.') if rows else 'Cannot inspect this video.')
            return JSONResponse(rows[-1],headers={'Cache-Control':'no-store'})
        if data.get('format') not in FORMATS or data.get('quality') not in QUALITY: raise ValueError('Unsupported format or quality.')
        if not os.environ.get('LINKDROP_SECRET'): raise ValueError('Cloud downloads are not configured.')
        data['action']='download'
        return StreamingResponse(events(data),media_type='application/x-ndjson',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
    except subprocess.TimeoutExpired: return JSONResponse({'error':'The source took too long to respond. Try another link.'},504)
    except Exception as exc: return JSONResponse({'error':str(exc)[:1200]},400)

@app.get('/{path:path}')
def health(path:str):
    return {'status':'ok','engine':'yt-dlp','limitMB':200,'maxSeconds':245}
