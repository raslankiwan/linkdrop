"""Local/desktop app: upload -> convert -> download, and link -> download."""
import http.server, json, shutil, sys, tempfile, threading, time, types, unittest, urllib.request, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for name, attrs in (('yt_dlp', {'YoutubeDL': type('YoutubeDL', (), {})}), ('imageio_ffmpeg', {'get_ffmpeg_exe': staticmethod(lambda: shutil.which('ffmpeg'))})):
    try: __import__(name)
    except ImportError:
        module = types.ModuleType(name)
        for k, v in attrs.items(): setattr(module, k, v.__func__ if isinstance(v, staticmethod) else v)
        sys.modules[name] = module

DOWNLOADS = tempfile.mkdtemp(prefix='linkdrop-local-')
os.environ['LINKDROP_DOWNLOADS'] = DOWNLOADS
import server  # noqa: E402
server.DATA = Path(DOWNLOADS)  # in case another test imported server first

class LocalConvertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = server.serve(0); cls.port = cls.app.server_port
        threading.Thread(target=cls.app.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.port}'

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown(); cls.app.server_close(); shutil.rmtree(DOWNLOADS, ignore_errors=True)

    def post(self, path, body, headers):
        req = urllib.request.Request(self.base + path, data=body, headers={'X-Token': server.TOKEN, **headers})
        try:
            with urllib.request.urlopen(req) as r: return r.status, json.load(r)
        except urllib.error.HTTPError as e: return e.code, json.load(e)

    def wait(self, jid):
        for _ in range(200):
            with urllib.request.urlopen(self.base + '/api/jobs') as r: job = next(j for j in json.load(r)['jobs'] if j['id'] == jid)
            if job['status'] in ('complete', 'error'): return job
            time.sleep(0.05)
        self.fail('job did not finish')

    def test_upload_convert_and_download(self):
        status, result = self.post('/api/convert', b'# Hi\n\nThere', {'Content-Type': 'application/octet-stream', 'X-Filename': 'm%C3%B8te%20notes.md', 'X-Target': 'docx'})
        self.assertEqual(status, 202, result)
        job = self.wait(result['id'])
        self.assertEqual(job['status'], 'complete', job); self.assertEqual(job['filename'], 'møte notes.docx')
        with urllib.request.urlopen(self.base + '/file/' + result['id']) as r:
            self.assertIn('attachment', r.headers['Content-Disposition']); self.assertTrue(r.read().startswith(b'PK'))
        self.assertEqual(sorted(p.name for p in (Path(DOWNLOADS) / result['id']).iterdir()), ['møte notes.docx'])

    def test_rejects_bad_token_and_unsupported(self):
        req = urllib.request.Request(self.base + '/api/convert', data=b'x', headers={'Content-Type': 'application/octet-stream', 'X-Filename': 'a.txt', 'X-Target': 'pdf'})
        with self.assertRaises(urllib.error.HTTPError) as ctx: urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)
        status, result = self.post('/api/convert', b'x', {'Content-Type': 'application/octet-stream', 'X-Filename': 'a.exe', 'X-Target': 'pdf'})
        self.assertEqual(status, 400); self.assertIn('not supported', result['error'])

    def test_link_download_any_file(self):
        with tempfile.TemporaryDirectory() as site:
            Path(site, 'Report Q3.pdf').write_bytes(b'%PDF-1.4 fake')
            handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=site, **k)
            web = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler); web.RequestHandlerClass.log_message = lambda *a: None
            threading.Thread(target=web.serve_forever, daemon=True).start()
            try:
                status, result = self.post('/api/convert', json.dumps({'sourceUrl': f'http://127.0.0.1:{web.server_port}/Report%20Q3.pdf', 'target': 'original'}).encode(), {'Content-Type': 'application/json'})
                self.assertEqual(status, 202, result)
                job = self.wait(result['id'])
                self.assertEqual((job['status'], job['filename']), ('complete', 'Report Q3.pdf'), job)
            finally: web.shutdown(); web.server_close()

    def test_static_assets_and_capabilities(self):
        for path in ('/convert.js', '/convert.css'):
            with urllib.request.urlopen(self.base + path) as r: self.assertEqual(r.status, 200)
        with urllib.request.urlopen(self.base + '/api/capabilities') as r: caps = json.load(r)
        self.assertIn('pdf', caps['formats']['docx']); self.assertEqual(caps['downloads'], DOWNLOADS)

if __name__ == '__main__': unittest.main()
