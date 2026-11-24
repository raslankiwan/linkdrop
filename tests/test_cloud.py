"""Exercise the hosted /api/convert path with FastAPI, Blob and yt-dlp stubbed out."""
import asyncio, base64, json, os, shutil, sys, types, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def stub_modules():
    saved = {}
    def put(name, module):
        saved[name] = sys.modules.get(name); sys.modules[name] = module
    fastapi = types.ModuleType('fastapi'); responses = types.ModuleType('fastapi.responses')
    class FastAPI:
        def get(self, *_a, **_k): return lambda f: f
        post = get
    class JSONResponse:
        def __init__(self, content, status_code=200, headers=None): self.content, self.status_code, self.headers = content, status_code, headers or {}
    class StreamingResponse:
        def __init__(self, body, media_type=None, headers=None): self.body, self.status_code = body, 200
    fastapi.FastAPI = FastAPI; fastapi.Request = object
    responses.JSONResponse = JSONResponse; responses.StreamingResponse = StreamingResponse
    put('fastapi', fastapi); put('fastapi.responses', responses)
    vercel = types.ModuleType('vercel'); blob = types.ModuleType('vercel.blob'); sync = types.ModuleType('vercel.blob.sync')
    sync.uploaded = []
    def put_blob(pathname, body, **options):
        sync.uploaded.append((pathname, body.read(), options)); return types.SimpleNamespace(pathname=pathname)
    sync.put_blob = put_blob; blob.sync = sync; vercel.blob = blob
    put('vercel', vercel); put('vercel.blob', blob); put('vercel.blob.sync', sync)
    if 'yt_dlp' not in sys.modules or saved.get('yt_dlp') is None:
        try: import yt_dlp  # noqa
        except ImportError:
            fake = types.ModuleType('yt_dlp'); fake.YoutubeDL = type('YoutubeDL', (), {}); put('yt_dlp', fake)
    try: import imageio_ffmpeg  # noqa
    except ImportError:
        fake = types.ModuleType('imageio_ffmpeg'); fake.get_ffmpeg_exe = lambda: shutil.which('ffmpeg'); put('imageio_ffmpeg', fake)
    return sync

class FakeRequest:
    def __init__(self, path, body, headers):
        self.url = types.SimpleNamespace(path=path); self._body = body
        self.headers = {k.lower(): v for k, v in headers.items()}; self.base_url = 'https://linkdrop.test/'
    async def body(self): return self._body

class CloudConvertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob = stub_modules()
        os.environ['LINKDROP_SECRET'] = 'test-secret'
        sys.modules.pop('api.cloud', None)
        sys.path.insert(0, str(ROOT / 'api'))
        import importlib; cls.cloud = importlib.import_module('cloud')

    def call(self, request):
        response = asyncio.run(self.cloud.handler(request))
        if hasattr(response, 'body'): return [json.loads(line) for line in response.body]
        return response

    def test_direct_upload_converts_and_stores_private_named_file(self):
        events = self.call(FakeRequest('/api/convert', b'name,age\nAda,36\n',
                                       {'Content-Type': 'application/octet-stream', 'X-Filename': 'R%C3%A9sum%C3%A9%20data.csv', 'X-Target': 'json',
                                        'Origin': 'https://linkdrop.test'}))
        final = events[-1]
        self.assertEqual(final['status'], 'complete', events)
        self.assertEqual(final['filename'], 'Résumé data.json'); self.assertNotIn('path', final)
        pathname, body, options = self.blob.uploaded[-1]
        self.assertRegex(pathname, r'^downloads/[a-f0-9]{32}/R-sum-data\.json$')
        self.assertEqual(json.loads(body), [{'name': 'Ada', 'age': '36'}]); self.assertEqual(options['access'], 'private')
        payload = final['fileUrl'].split('ticket=')[1].split('.')[0]
        self.assertEqual(json.loads(base64.urlsafe_b64decode(payload + '==='))['pathname'], pathname)

    def test_rejects_unsupported_pairs_cross_site_and_foreign_upload_hosts(self):
        r = self.call(FakeRequest('/api/convert', b'x', {'Content-Type': 'application/octet-stream', 'X-Filename': 'a.txt', 'X-Target': 'mp3'}))
        self.assertEqual(r.status_code, 400); self.assertIn('not supported', r.content['error'])
        r = self.call(FakeRequest('/api/convert', b'x', {'Content-Type': 'application/octet-stream', 'X-Filename': 'a.txt', 'X-Target': 'pdf', 'Origin': 'https://evil.test'}))
        self.assertEqual(r.status_code, 403)
        body = json.dumps({'source': 'upload', 'sourceUrl': 'https://example.com/a.csv', 'filename': 'a.csv', 'target': 'json'}).encode()
        r = self.call(FakeRequest('/api/convert', body, {'Content-Type': 'application/json'}))
        self.assertEqual(r.status_code, 400); self.assertIn('Invalid upload', r.content['error'])
        body = json.dumps({'source': 'link', 'sourceUrl': 'http://169.254.169.254/latest', 'target': 'original'}).encode()
        self.assertEqual(self.call(FakeRequest('/api/convert', body, {'Content-Type': 'application/json'})).status_code, 400)
        big = b'x' * (4 * 1024 * 1024 + 1)
        r = self.call(FakeRequest('/api/convert', big, {'Content-Type': 'application/octet-stream', 'X-Filename': 'a.txt', 'X-Target': 'pdf'}))
        self.assertEqual(r.status_code, 400)

    def test_capabilities_endpoint(self):
        r = self.cloud.health('api/capabilities')
        self.assertEqual(r.content['directUploadBytes'], 4 * 1024 * 1024)
        self.assertIn('json', r.content['formats']['csv'])

if __name__ == '__main__': unittest.main()
