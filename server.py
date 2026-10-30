import json, os, secrets, threading, time, uuid, mimetypes, shutil
from pathlib import Path
from urllib.parse import urlparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import yt_dlp
import imageio_ffmpeg
from lib.errors import download_error

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'downloads'
DATA.mkdir(exist_ok=True)
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
        raise ValueError('Paste a valid public HTTP or HTTPS video link.')
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
            body=(ROOT/'index.html').read_text().replace('__TOKEN__',TOKEN).encode()
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
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
            if length>8192: raise ValueError('Request too large')
            data=json.loads(self.rfile.read(length))
            if self.path=='/api/history/clear':
                with LOCK:
                    finished=[key for key,job in JOBS.items() if job['status'] in ('complete','error')]
                    for key in finished: del JOBS[key]
                return self.sendjson({'cleared':len(finished)})
            data['url']=urlcheck(data.get('url',''))
            if self.path=='/api/inspect':
                with yt_dlp.YoutubeDL(options(data.get('browser'))) as ydl: info=ydl.extract_info(data['url'],download=False)
                heights=sorted({f['height'] for f in info.get('formats',[]) if f.get('height')},reverse=True)
                return self.sendjson({'title':info.get('title'), 'duration':info.get('duration'), 'uploader':info.get('uploader'),
                                      'platform':info.get('extractor_key'), 'heights':heights})
            if self.path!='/api/download': return self.sendjson({'error':'Not found'},404)
            if data.get('format') not in FORMATS or data.get('quality') not in {'best','2160','1440','1080','720','480','360'}:
                raise ValueError('Choose a supported format and quality.')
            with LOCK:
                if sum(j['status'] not in ('complete','error') for j in JOBS.values())>=10: raise ValueError('Queue is full. Wait for a download to finish.')
                jid=uuid.uuid4().hex; JOBS[jid]={'status':'queued','title':data.get('title') or data['url'], 'format':data['format'], 'progress':0}
            threading.Thread(target=run,args=(jid,data),daemon=True).start(); self.sendjson({'id':jid},202)
        except Exception as e: self.sendjson(download_error(e),400)

if __name__=='__main__':
    port=int(os.environ.get('PORT','8765'))
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'LinkDrop ready at http://127.0.0.1:{port}',flush=True)
    server.serve_forever()
