"""Bounded cloud worker. Emits NDJSON events on stdout; no persistent background jobs."""
import ipaddress, json, os, socket, sys, time
from pathlib import Path
from urllib.parse import urlparse
import imageio_ffmpeg
import shutil
import yt_dlp

MAX_BYTES = 200 * 1024 * 1024
FORMATS = {'original','mp4','mkv','webm','mov','mp3','m4a','wav','flac','opus'}
AUDIO = {'mp3','m4a','wav','flac','opus'}
QUALITY = {'best','2160','1440','1080','720','480','360'}

def public_url(url):
    if not isinstance(url,str) or len(url)>4096: raise ValueError('Enter a valid video URL.')
    p=urlparse(url)
    if p.scheme not in ('https','http') or not p.hostname or p.username or p.password or p.port not in (None,80,443):
        raise ValueError('Use a public HTTP or HTTPS link on a standard port.')
    addresses=socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Local and private network addresses are not supported.')
    return url

class PublicDL(yt_dlp.YoutubeDL):
    def urlopen(self,req):
        public_url(req if isinstance(req,str) else req.url)
        return super().urlopen(req)

class QuietLogger:
    def debug(self,msg): pass
    def warning(self,msg): pass
    def error(self,msg): pass

def options():
    return {'quiet':True,'no_warnings':True,'noprogress':True,'logger':QuietLogger(), 'noplaylist':True,
            'socket_timeout':15,'retries':1,'fragment_retries':1,'cachedir':False,
            'ffmpeg_location':imageio_ffmpeg.get_ffmpeg_exe(), 'js_runtimes':{'node':{'path':str(Path(__file__).with_name('runtime-node')) if Path(__file__).with_name('runtime-node').exists() else (shutil.which('node') or 'node')}}, 'max_filesize':MAX_BYTES,
            'extractor_args':{'generic':{'impersonate':['']}}}

def emit(event):
    print(json.dumps(event),flush=True)

def protect_network():
    # Guard actual connections too, including redirects and DNS rebinding.
    original=socket.socket.connect
    def connect(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):
            host,port=address[:2]
            entries=socket.getaddrinfo(host,port,family=sock.family,type=socket.SOCK_STREAM)
            if not entries or any(not ipaddress.ip_address(item[4][0]).is_global for item in entries):
                raise OSError('Private network connections are blocked.')
            address=entries[0][4]
        return original(sock,address)
    socket.socket.connect=connect

def main():
    protect_network()
    data=json.loads(sys.stdin.readline()); url=public_url(data['url'])
    opts=options()
    if data['action']=='inspect':
        with PublicDL(opts) as dl: info=dl.extract_info(url,download=False)
        emit({'title':info.get('title'),'duration':info.get('duration'),'uploader':info.get('uploader'),
              'platform':info.get('extractor_key'),'heights':sorted({f['height'] for f in info.get('formats',[]) if f.get('height')},reverse=True)})
        return
    fmt=data['format']; quality=data['quality']
    if fmt not in FORMATS or quality not in QUALITY: raise ValueError('Unsupported format or quality.')
    folder=Path(data['folder']); last=[0]
    def progress(d):
        size=d.get('downloaded_bytes',0); total=d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        if size>MAX_BYTES or sum(p.stat().st_size for p in folder.iterdir() if p.is_file())>MAX_BYTES:
            raise ValueError('Hosted downloads are limited to 200 MB. Use the local app for larger files.')
        if time.monotonic()-last[0]>1 or d['status']=='finished':
            last[0]=time.monotonic()
            emit({'status':'processing' if d['status']=='finished' else 'downloading','progress':round(size/total*100,1) if total else 0})
    opts.update(outtmpl=str(folder/'%(title).120B.%(ext)s'),progress_hooks=[progress],windowsfilenames=True)
    if fmt in AUDIO:
        opts.update(format='bestaudio/best',postprocessors=[{'key':'FFmpegExtractAudio','preferredcodec':fmt,'preferredquality':'192'}])
    else:
        ceiling='' if quality=='best' else '[height<=?'+quality+']'
        opts['format']=f'bv*{ceiling}+ba/b{ceiling}'
        if fmt!='original':
            opts.update(merge_output_format='mkv',postprocessors=[{'key':'FFmpegVideoConvertor','preferedformat':fmt}])
            if fmt=='webm': opts['postprocessor_args']={'videoconvertor+ffmpeg_o':['-deadline','realtime','-cpu-used','6','-threads','2']}
    with PublicDL(opts) as dl: info=dl.extract_info(url,download=True)
    files=[p for p in folder.iterdir() if p.is_file() and p.suffix not in {'.part','.ytdl','.temp'}]
    if not files: raise ValueError('No downloadable file was returned. The source may exceed the 200 MB hosted limit.')
    file=max(files,key=lambda p:p.stat().st_size)
    if file.stat().st_size>MAX_BYTES: raise ValueError('The converted file exceeds the 200 MB hosted limit.')
    emit({'status':'uploading','title':info.get('title') or file.stem,'filename':file.name,'size':file.stat().st_size})

if __name__=='__main__':
    try: main()
    except Exception as exc:
        emit({'status':'error','error':str(exc)[:1200]});sys.exit(1)
