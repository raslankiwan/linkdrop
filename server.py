import json, os, secrets, sys, threading, time, uuid, mimetypes, shutil
from pathlib import Path
from urllib.parse import unquote, urlparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import yt_dlp
import imageio_ffmpeg
from lib.errors import download_error
from lib import convert as converter

FROZEN = getattr(sys, 'frozen', False)
ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
# Installed desktop apps save into the user's Downloads folder; a source checkout keeps ./downloads.
DATA = Path(os.environ.get('LINKDROP_DOWNLOADS') or (Path.home() / 'Downloads' / 'LinkDrop' if FROZEN else ROOT / 'downloads'))
DATA.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD = 4 * 1024 ** 3
STATIC = {'/auto-save.js': 'text/javascript', '/convert.js': 'text/javascript', '/convert.css': 'text/css'}
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
TOKEN = secrets.token_urlsafe(32)
JOBS = {}
LOCK = threading.Lock()
GATE = threading.BoundedSemaphore(2)
FORMATS = {'original', 'mp4', 'mkv', 'webm', 'mov', 'mp3', 'm4a', 'wav', 'flac', 'opus'}
AUDIO = {'mp3', 'm4a', 'wav', 'flac', 'opus'}

def urlcheck(url):
    p = urlparse(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('Paste a valid HTTP or HTTPS link.')
    return url

def options(browser=None):
    opts = {'quiet': True, 'no_warnings': True, 'noplaylist': True, 'socket_timeout': 25,
            'retries': 2, 'ffmpeg_location': FFMPEG, 'js_runtimes': {'node': {}},
            'remote_components': ['ejs:github']}
    if browser:
        if browser not in {'chrome','safari','firefox','edge','brave'}: raise ValueError('Choose a supported browser.')
        opts['cookiesfrombrowser']=(browser,)
    return opts

def update(jid, **values):
    with LOCK: JOBS[jid].update(values)

def run(jid, data):
    with GATE:
        folder = DATA / jid
        folder.mkdir()
        def progress(d):
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                update(jid, status='downloading', progress=round(100*d.get('downloaded_bytes',0)/total,1) if total else 0,
                       speed=d.get('speed'), eta=d.get('eta'))
            elif d['status'] == 'finished': update(jid, status='processing', progress=100)
        try:
            update(jid, status='starting')
            fmt, quality = data['format'], data['quality']
            ceiling = '' if quality == 'best' else '[height<=?' + quality + ']'
            opts = options(data.get('browser'))
            opts.update({'outtmpl': str(folder / '%(title).160B.%(ext)s'), 'progress_hooks': [progress],
                         'restrictfilenames': False, 'windowsfilenames': True})
            if fmt in AUDIO:
                opts.update(format='bestaudio/best', postprocessors=[{'key':'FFmpegExtractAudio', 'preferredcodec':fmt, 'preferredquality':'192'}])
            else:
                opts['format'] = f'bv*{ceiling}+ba/b{ceiling}'
                if fmt != 'original':
                    opts['merge_output_format'] = 'mkv'
                    opts['postprocessors'] = [{'key':'FFmpegVideoConvertor', 'preferedformat':fmt}]
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(data['url'], download=True)
            files = [p for p in folder.iterdir() if p.is_file() and p.suffix not in ('.part','.ytdl','.temp')]
            if not files: raise ValueError('The platform did not return a downloadable file.')
            path = max(files, key=lambda p:p.stat().st_size)
            update(jid, status='complete', progress=100, title=info.get('title') or path.stem,
                   filename=path.name, size=path.stat().st_size)
        except Exception as e:
            update(jid, status='error', **download_error(e))

def run_convert(jid, data):
    with GATE:
        folder = DATA / jid
        try:
            update(jid, status='starting')
            if data.get('sourceUrl'):
                update(jid, status='downloading', progress=0)
                def progress(done, total): update(jid, progress=round(done / total * 100, 1) if total else 0, size=done)
                source, name = converter.fetch(data['sourceUrl'], folder, 0, guard=False, progress=progress)
                update(jid, title=name)
            else:
                source, name = Path(data['input']), data['filename']
            if data['target'] == 'original':
                path = folder / name
                if path != source: shutil.move(str(source), path)
            else:
                update(jid, status='processing', progress=100)
                out = folder / 'out'; out.mkdir(exist_ok=True)
                result = converter.convert(source, data['target'], out, name, timeout=3600)
                path = folder / result.name
                shutil.move(str(result), path); shutil.rmtree(out, ignore_errors=True)
                if source.exists() and source != path: source.unlink()
            update(jid, status='complete', progress=100, title=path.name, filename=path.name, size=path.stat().st_size)
        except Exception as e:
            update(jid, status='error', error=str(e)[:1200] or e.__class__.__name__, code='CONVERT_FAILED')

def reveal(jid, open_file=False):
    """Show a finished file in Finder/Explorer, or open it with its default app (desktop app)."""
    import subprocess
    with LOCK: job=dict(JOBS.get(jid,{}))
    if job.get('status')!='complete': raise ValueError('File unavailable.')
    file=(DATA/jid/job['filename']).resolve()
    if DATA.resolve() not in file.parents or not file.is_file(): raise ValueError('The file was moved or deleted.')
    if sys.platform=='darwin': subprocess.Popen(['open',str(file)] if open_file else ['open','-R',str(file)])
    elif os.name=='nt':
        if open_file: os.startfile(str(file))  # type: ignore[attr-defined]
        else: subprocess.Popen(['explorer','/select,',str(file)])
    else: subprocess.Popen(['xdg-open',str(file if open_file else file.parent)])
    return {'ok':True}

def new_job(title, fmt, kind='download'):
    with LOCK:
        if sum(j['status'] not in ('complete','error') for j in JOBS.values())>=10: raise ValueError('Queue is full. Wait for a job to finish.')
        jid=uuid.uuid4().hex; JOBS[jid]={'status':'queued','title':title,'format':fmt,'progress':0,'kind':kind}
    return jid

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def sendjson(self, obj, code=200):
        body=json.dumps(obj).encode(); self.send_response(code)
        self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
            return self.sendjson({'error':'Invalid host'},403)
        path=urlparse(self.path).path
        if path=='/':
            body=(ROOT/'index.html').read_text(encoding='utf-8').replace('__TOKEN__',TOKEN).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
        elif path in STATIC:
            body=(ROOT/'public'/path.lstrip('/')).read_bytes()
            self.send_response(200); self.send_header('Content-Type',STATIC[path]+'; charset=utf-8')
            self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store')
            self.end_headers(); self.wfile.write(body)
        elif path=='/api/capabilities':
            self.sendjson({**converter.capabilities(),'maxBytes':MAX_UPLOAD,'downloads':str(DATA),'platform':sys.platform})
        elif path=='/api/jobs':
            with LOCK: jobs=[dict(j, id=k) for k,j in JOBS.items()]
            self.sendjson({'jobs':jobs[::-1]})
        elif path.startswith('/file/'):
            jid=path.split('/')[-1]
            with LOCK: job=dict(JOBS.get(jid,{}))
            if job.get('status')!='complete': return self.sendjson({'error':'File unavailable'},404)
            file=DATA/jid/job['filename']
            if not file.is_file(): return self.sendjson({'error':'File was removed from disk'},404)
            from urllib.parse import quote
            self.send_response(200); self.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(file.name))
            self.send_header('Content-Length',str(file.stat().st_size)); self.end_headers()
            try:
                with file.open('rb') as f: shutil.copyfileobj(f,self.wfile)
            except (BrokenPipeError,ConnectionResetError): pass
        else: self.sendjson({'error':'Not found'},404)
    def do_POST(self):
        if self.headers.get('X-Token')!=TOKEN: return self.sendjson({'error':'Reload the app and try again.'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if self.path=='/api/convert' and self.headers.get('Content-Type','').startswith('application/octet-stream'):
                return self.upload(length)
            if length>8192: raise ValueError('Request too large')
            data=json.loads(self.rfile.read(length))
            if self.path=='/api/reveal':
                return self.sendjson(reveal(str(data.get('id','')), bool(data.get('open'))))
            if self.path=='/api/history/clear':
                with LOCK:
                    finished=[key for key,job in JOBS.items() if job['status'] in ('complete','error')]
                    for key in finished: del JOBS[key]
                return self.sendjson({'cleared':len(finished)})
            if self.path=='/api/convert':
                url=urlcheck(data.get('sourceUrl',''))
                target=str(data.get('target') or 'original').lower()
                if target!='original':
                    ext=converter.extension(Path(urlparse(url).path).name)
                    if ext and target not in converter.targets(ext): raise ValueError(f'Converting .{ext} to .{target} is not supported.')
                jid=new_job(url,target,'convert'); (DATA/jid).mkdir()
                threading.Thread(target=run_convert,args=(jid,{'sourceUrl':url,'target':target}),daemon=True).start()
                return self.sendjson({'id':jid},202)
            data['url']=urlcheck(data.get('url',''))
            if self.path=='/api/inspect':
                with yt_dlp.YoutubeDL(options(data.get('browser'))) as ydl: info=ydl.extract_info(data['url'],download=False)
                heights=sorted({f['height'] for f in info.get('formats',[]) if f.get('height')},reverse=True)
                return self.sendjson({'title':info.get('title'), 'duration':info.get('duration'), 'uploader':info.get('uploader'),
                                      'platform':info.get('extractor_key'), 'heights':heights})
            if self.path!='/api/download': return self.sendjson({'error':'Not found'},404)
            if data.get('format') not in FORMATS or data.get('quality') not in {'best','2160','1440','1080','720','480','360'}:
                raise ValueError('Choose a supported format and quality.')
            jid=new_job(data.get('title') or data['url'],data['format'])
            threading.Thread(target=run,args=(jid,data),daemon=True).start(); self.sendjson({'id':jid},202)
        except Exception as e: self.sendjson(download_error(e),400)
    def upload(self,length):
        name=Path(unquote(self.headers.get('X-Filename',''))).name[:160] or 'file'
        target=str(self.headers.get('X-Target','')).lower(); ext=converter.extension(name)
        if not length or length>MAX_UPLOAD: raise ValueError('Files up to 4 GB can be converted.')
        if target not in converter.targets(ext): raise ValueError(f'Converting .{ext or "?"} to .{target} is not supported on this computer.')
        jid=new_job(name,target,'convert'); folder=DATA/jid; folder.mkdir()
        source=folder/('source.'+(ext or 'bin')); remaining=length
        try:
            with source.open('wb') as out:
                while remaining:
                    chunk=self.rfile.read(min(remaining,1<<20))
                    if not chunk: raise ValueError('The upload was interrupted.')
                    out.write(chunk); remaining-=len(chunk)
        except Exception as e:
            shutil.rmtree(folder,ignore_errors=True)
            with LOCK: JOBS.pop(jid,None)
            raise
        threading.Thread(target=run_convert,args=(jid,{'input':str(source),'filename':name,'target':target}),daemon=True).start()
        self.sendjson({'id':jid},202)

def serve(port=None):
    port=int(port if port is not None else os.environ.get('PORT','8765'))
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'LinkDrop ready at http://127.0.0.1:{port}',flush=True)
    return server

if __name__=='__main__':
    serve().serve_forever()
