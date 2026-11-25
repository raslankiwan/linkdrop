import io, json, shutil, subprocess, sys, tarfile, tempfile, unittest, zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lib import convert as c

def has(module):
    try: __import__(module); return True
    except Exception: return False

class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='linkdrop-test-'))
        cls.files = {}
        t = cls.tmp
        (t / 'notes.md').write_text('# Title\n\nHello **world** with [link](https://x.test).\n\n- one\n- two\n\n```\ncode()\n```\n')
        (t / 'plain.txt').write_text('First paragraph.\n\nSecond paragraph é.')
        (t / 'page.html').write_text('<html><head><style>x{}</style></head><body><h1>Head</h1><p>Para <b>bold</b></p><ul><li>a</li></ul></body></html>')
        (t / 'table.csv').write_text('name,age\nAda,36\nLin,"4,2"\n')
        (t / 'list.json').write_text(json.dumps([{'a': 1, 'b': {'x': 2}}, {'a': 3, 'c': 'z'}]))
        with zipfile.ZipFile(t / 'bundle.zip', 'w') as z: z.writestr('dir/a.txt', 'A'); z.writestr('b.txt', 'B')
        if has('PIL'):
            from PIL import Image
            Image.new('RGBA', (40, 30), (200, 10, 10, 128)).save(t / 'pic.png')
            frames = [Image.new('P', (20, 20), i * 40) for i in range(3)]
            frames[0].save(t / 'anim.gif', save_all=True, append_images=frames[1:], duration=100, loop=0)
        if c.ffmpeg_path():
            ff = c.ffmpeg_path()
            subprocess.run([ff, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x120:rate=10', '-f', 'lavfi', '-i', 'sine=frequency=440',
                            '-t', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(t / 'clip.mp4')], check=True)
            subprocess.run([ff, '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1', str(t / 'tone.wav')], check=True)

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_all(self, name, expected=None, office=False):
        src = self.tmp / name
        with mock.patch.object(c, 'office_path', return_value=shutil.which('soffice') if office else None):
            outs = c.targets(c.extension(name))
            if expected: self.assertTrue(set(expected) <= set(outs), (name, outs))
            for target in outs:
                with self.subTest(src=name, target=target):
                    outdir = self.tmp / 'out' / f'{name}-{target}'.replace('.', '_'); outdir.mkdir(parents=True, exist_ok=True)
                    result = c.convert(src, target, outdir, name)
                    self.assertTrue(result.is_file() and result.stat().st_size > 0)
                    self.assertTrue(result.name.endswith('.' + target) or result.suffix == '.zip', result.name)
        return outs

class ConvertTest(Fixtures):
    def test_documents(self):
        self.run_all('notes.md', ['pdf', 'docx', 'html', 'txt'])
        self.run_all('plain.txt', ['pdf', 'docx', 'html', 'md'])
        self.run_all('page.html', ['md', 'txt', 'docx', 'pdf'])

    def test_document_content_roundtrip(self):
        out = self.tmp / 'rt'; out.mkdir(exist_ok=True)
        docx = c.convert(self.tmp / 'notes.md', 'docx', out, 'notes.md')
        md = c.convert(docx, 'md', out, 'notes2.docx')
        text = md.read_text()
        self.assertIn('# Title', text); self.assertIn('Hello world with link.', text); self.assertIn('- one', text)
        html_md = c.convert(self.tmp / 'page.html', 'md', out, 'page.html').read_text()
        self.assertIn('# Head', html_md); self.assertNotIn('x{}', html_md)
        pdf = c.convert(self.tmp / 'notes.md', 'pdf', out, 'notes.md')
        self.assertIn('Hello world', c.convert(pdf, 'txt', out, 'notes3.pdf').read_text())
        if has('docx'):  # our stdlib .docx must open in python-docx (Word-compatible structure)
            import docx as pydocx
            doc = pydocx.Document(str(docx))
            self.assertEqual([p.style.name for p in doc.paragraphs][:2], ['Heading 1', 'Normal'])

    def test_long_pdf_wraps_and_paginates(self):
        from pypdf import PdfReader
        out = self.tmp / 'wrap'; out.mkdir(exist_ok=True)
        src = self.tmp / 'wrap.txt'; src.write_text('\n\n'.join(f'Paragraph {i} ' + 'lorem ipsum dolor sit amet ' * 30 + 'supercalifragilisticexpialidocious' * 5 for i in range(60)) + '\n\nCafé – naïve “quotes”')
        reader = PdfReader(str(c.convert(src, 'pdf', out, 'wrap.txt')))
        self.assertGreater(len(reader.pages), 5)
        text = ''.join(page.extract_text() for page in reader.pages)
        self.assertIn('Paragraph 59', text); self.assertIn('Café', text)

    def test_pdf_pages_to_images(self):
        if not has('pypdfium2'): self.skipTest('pypdfium2 missing')
        out = self.tmp / 'pages'; out.mkdir(exist_ok=True)
        long = self.tmp / 'long.txt'; long.write_text('\n\n'.join(f'Paragraph {i} ' * 20 for i in range(120)))
        pdf = c.convert(long, 'pdf', out, 'long.txt')
        pages = c.convert(pdf, 'png', out, 'long.pdf')
        self.assertEqual(pages.suffix, '.zip')
        self.assertGreater(len(zipfile.ZipFile(pages).namelist()), 1)

    def test_data(self):
        self.run_all('table.csv', ['json', 'xlsx', 'yaml', 'tsv', 'md', 'html'])
        self.run_all('list.json', ['csv', 'xlsx'])
        out = self.tmp / 'data'; out.mkdir(exist_ok=True)
        rows = json.loads(c.convert(self.tmp / 'table.csv', 'json', out, 'table.csv').read_text())
        self.assertEqual(rows[1], {'name': 'Lin', 'age': '4,2'})
        xlsx = c.convert(self.tmp / 'list.json', 'xlsx', out, 'list.json')
        back = c.convert(xlsx, 'csv', out, 'list2.xlsx').read_text(encoding='utf-8-sig').splitlines()
        self.assertEqual(back[0], 'a,b,c'); self.assertIn('"{""x"": 2}"', back[1])

    def test_images(self):
        if not has('PIL'): self.skipTest('Pillow missing')
        self.run_all('pic.png', ['jpg', 'webp', 'gif', 'bmp', 'tiff', 'ico', 'pdf'])
        self.run_all('anim.gif', ['png', 'pdf'] + (['mp4', 'webm'] if c.ffmpeg_path() else []))

    def test_media(self):
        if not c.ffmpeg_path(): self.skipTest('ffmpeg missing')
        self.run_all('clip.mp4', ['mkv', 'webm', 'mov', 'avi', 'gif', 'mp3', 'wav', 'flac', 'opus', 'ogg', 'aac', 'm4a'])
        self.run_all('tone.wav', ['mp3', 'flac', 'ogg'])

    def test_archives(self):
        outs = self.run_all('bundle.zip', ['tar', 'tar.gz', 'tar.xz'])
        out = self.tmp / 'arc'; out.mkdir(exist_ok=True)
        tgz = c.convert(self.tmp / 'bundle.zip', 'tar.gz', out, 'bundle.zip')
        self.assertEqual(sorted(tarfile.open(tgz).getnames()), ['b.txt', 'dir/a.txt'])
        self.assertEqual(c.extension('x.TAR.GZ'), 'tar.gz')

    def test_archive_traversal_rejected(self):
        evil = self.tmp / 'evil.zip'
        with zipfile.ZipFile(evil, 'w') as z: z.writestr('../../escape.txt', 'x')
        with self.assertRaises(c.ConversionError): c.convert(evil, 'tar', self.tmp, 'evil.zip')

    @unittest.skipUnless(shutil.which('soffice'), 'LibreOffice missing')
    def test_office_when_installed(self):
        out = self.tmp / 'office'; out.mkdir(exist_ok=True)
        docx = c.convert(self.tmp / 'notes.md', 'docx', out, 'notes.md')
        with mock.patch.object(c, 'office_path', return_value=shutil.which('soffice')):
            self.assertIn('odt', c.targets('docx'))
            self.assertIn('pptx', c.targets('odp'))
            odt = c.convert(docx, 'odt', out, 'notes.docx')
            pdf = c.convert(odt, 'pdf', out, 'notes.odt')
            self.assertTrue(pdf.read_bytes().startswith(b'%PDF'))
        with mock.patch.object(c, 'office_path', return_value=None):
            self.assertNotIn('odt', c.targets('docx'))
            self.assertEqual(c.targets('pptx'), [])

    def test_unsupported(self):
        with self.assertRaises(c.ConversionError): c.convert(self.tmp / 'plain.txt', 'mp3', self.tmp, 'plain.txt')
        self.assertEqual(c.targets('exe'), [])
        self.assertIn('pdf', c.capabilities()['formats']['md'])

    def test_names(self):
        self.assertEqual(c.stem('../a<b>.tar.gz'), 'a_b_')
        self.assertEqual(c.filename_from('https://x.test/files/report%20v2.pdf?x=1', {}), 'report v2.pdf')
        self.assertEqual(c.filename_from('https://x.test/dl', {'Content-Disposition': "attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.docx"}), 'résumé.docx')
        self.assertEqual(c.filename_from('https://x.test/', {'Content-Type': 'application/pdf'}), 'download.pdf')

class ArabicTest(Fixtures):
    def test_shaping_and_order(self):
        from lib import arabic
        self.assertEqual(arabic.shape('سلام'), '\ufeb3\ufefc\ufee1')  # initial seen, lam-alef final, isolated meem
        self.assertEqual(arabic.shape('لا'), '\ufefb')
        self.assertEqual(arabic.visual(arabic.shape('عام 2026'), 'rtl'), '2026 ' + arabic.shape('عام')[::-1])
        self.assertEqual(arabic.visual('abc', 'ltr'), 'abc')
        self.assertEqual(arabic.base_direction('مرحبا world'), 'rtl'); self.assertEqual(arabic.base_direction('Hi مرحبا'), 'ltr')

    def test_arabic_documents(self):
        import unicodedata
        from pypdf import PdfReader
        out = self.tmp / 'ar'; out.mkdir(exist_ok=True)
        src = self.tmp / 'ar.md'; src.write_text('# تقرير\n\nمرحبا بكم في لينك دروب 2026.\n\n- بند أول\n', encoding='utf-8')
        pdf = c.convert(src, 'pdf', out, 'تقرير.md')
        self.assertEqual(pdf.name, 'تقرير.pdf')
        text = unicodedata.normalize('NFKC', PdfReader(str(pdf)).pages[0].extract_text())
        for word in ('تقرير', 'مرحبا', 'بند'): self.assertIn(word, text)
        docx = c.convert(src, 'docx', out, 'ar.md')
        xml = zipfile.ZipFile(docx).read('word/document.xml').decode()
        self.assertIn('<w:bidi/>', xml); self.assertIn('مرحبا بكم', xml)
        self.assertIn('dir="auto"', c.convert(src, 'html', out, 'ar.md').read_text(encoding='utf-8'))
        latin = c.convert(self.tmp / 'notes.md', 'pdf', out, 'notes.md')
        self.assertLess(latin.stat().st_size, 20_000)  # Latin-only PDFs stay small (no embedded fonts)

    def test_legacy_arabic_csv_and_excel_bom(self):
        out = self.tmp / 'arcsv'; out.mkdir(exist_ok=True)
        src = self.tmp / 'old.csv'; src.write_bytes('الاسم,المدينة\nأحمد,نابلس\n'.encode('cp1256'))
        rows = json.loads(c.convert(src, 'json', out, 'old.csv').read_text(encoding='utf-8'))
        self.assertEqual(rows, [{'الاسم': 'أحمد', 'المدينة': 'نابلس'}])
        csv_out = c.convert(c.convert(src, 'xlsx', out, 'old.csv'), 'csv', out, 'old2.xlsx')
        self.assertTrue(csv_out.read_bytes().startswith(b'\xef\xbb\xbf'))
        western = self.tmp / 'w.csv'; western.write_bytes('name,city\nJosé,Zürich\n'.encode('cp1252'))
        self.assertIn('Zürich', c.convert(western, 'json', out, 'w.csv').read_text(encoding='utf-8'))

class FetchTest(unittest.TestCase):
    def test_private_links_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            for url in ('http://127.0.0.1/x', 'http://localhost/x', 'ftp://example.com/x', 'http://169.254.169.254/latest'):
                with self.subTest(url=url), self.assertRaises(ValueError): c.fetch(url, d, 1000)

    def test_worker_downloads_and_converts(self):
        import http.server, threading
        with tempfile.TemporaryDirectory() as site:
            Path(site, 'data.csv').write_text('a,b\n1,2\n')
            handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=site, **k)
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler); server.RequestHandlerClass.log_message = lambda *a: None
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with tempfile.TemporaryDirectory() as work:
                    req = {'sourceUrl': f'http://127.0.0.1:{server.server_port}/data.csv', 'target': 'json', 'folder': work,
                           'maxBytes': 10_000, 'guard': False}
                    proc = subprocess.run([sys.executable, str(ROOT / 'lib' / 'convert.py')], input=json.dumps(req) + '\n',
                                          capture_output=True, text=True, timeout=60)
                    events = [json.loads(l) for l in proc.stdout.splitlines()]
                    self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                    self.assertEqual(events[-1]['filename'], 'data.json')
                    self.assertEqual(json.loads(Path(events[-1]['path']).read_text()), [{'a': '1', 'b': '2'}])
                    parts = {'sourceUrls': [f'http://127.0.0.1:{server.server_port}/p1', f'http://127.0.0.1:{server.server_port}/p2'],
                             'filename': 'joined.csv', 'target': 'json', 'folder': work, 'maxBytes': 10_000, 'guard': False}
                    Path(site, 'p1').write_bytes(b'x,y\n1,'); Path(site, 'p2').write_bytes(b'2\n')
                    proc = subprocess.run([sys.executable, str(ROOT / 'lib' / 'convert.py')], input=json.dumps(parts) + '\n',
                                          capture_output=True, text=True, timeout=60)
                    last = json.loads(proc.stdout.splitlines()[-1])
                    self.assertEqual(json.loads(Path(last['path']).read_text()), [{'x': '1', 'y': '2'}], proc.stdout)
                    req.update(target='original', maxBytes=3)
                    proc = subprocess.run([sys.executable, str(ROOT / 'lib' / 'convert.py')], input=json.dumps(req) + '\n',
                                          capture_output=True, text=True, timeout=60)
                    self.assertEqual(proc.returncode, 1); self.assertIn('limit', proc.stdout)
            finally: server.shutdown()

if __name__ == '__main__': unittest.main()
