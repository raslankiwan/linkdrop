"""File conversion and direct file downloads for LinkDrop.

Used by the local/desktop app (in-process) and by the hosted app (as a bounded
subprocess, see `main`). Each family of formats has a reader and writers:

* media     video/audio through FFmpeg
* image     raster images through Pillow (and images -> PDF)
* document  txt / md / html / docx / pdf through a small block model, plus
            LibreOffice for office formats when it is installed on the machine
* data      csv / tsv / json / yaml / xlsx / html / md tables
* archive   zip / tar / tar.gz / tar.bz2 / tar.xz
"""
import csv, html, io, json, os, re, shutil, subprocess, sys, tarfile, tempfile, time, zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

VIDEO_IN = {'mp4','mkv','webm','mov','avi','m4v','flv','wmv','mpeg','mpg','3gp','ts','mts','m2ts','ogv','vob'}
AUDIO_IN = {'mp3','m4a','wav','flac','opus','ogg','oga','aac','wma','aiff','aif','amr','ac3','caf','mka'}
VIDEO_OUT = ['mp4','mkv','webm','mov','avi','gif']
AUDIO_OUT = ['mp3','m4a','wav','flac','opus','ogg','aac']
IMAGE_IN = {'png','jpg','jpeg','webp','gif','bmp','tiff','tif','ico','ppm','pgm','pbm','tga','jfif','avif'}
IMAGE_OUT = ['png','jpg','webp','gif','bmp','tiff','ico','pdf']
DOC_IN = {'txt','md','markdown','html','htm','docx','pdf'}
DOC_OUT = ['pdf','docx','html','md','txt']
OFFICE_IN = {'doc','docx','odt','rtf','pptx','ppt','odp','xlsx','xls','ods','pages','key','numbers','epub'}
OFFICE_OUT = {'text':['pdf','docx','odt','rtf','txt','html'], 'slides':['pdf','pptx','odp'], 'sheet':['pdf','xlsx','ods','csv']}
DATA_IN = {'csv','tsv','json','yaml','yml','xlsx'}
DATA_OUT = ['csv','tsv','json','yaml','xlsx','html','md']
ARCHIVE_OUT = ['zip','tar','tar.gz','tar.bz2','tar.xz']
ARCHIVE_IN = set(ARCHIVE_OUT) | {'tgz','tbz2','txz'}
MAX_ARCHIVE_EXPANDED = 1024 * 1024 * 1024
MAX_PDF_PAGES = 200

class ConversionError(ValueError):
    pass

def extension(name):
    lower = name.lower()
    for compound in ('tar.gz','tar.bz2','tar.xz'):
        if lower.endswith('.' + compound): return compound
    return Path(lower).suffix.lstrip('.')

def stem(name):
    ext = extension(name)
    base = Path(name).name
    base = base[:-(len(ext) + 1)] if ext and base.lower().endswith('.' + ext) else base
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', base).strip(' .') or 'file'
    return base[:120]

# ---------------------------------------------------------------- capabilities

def ffmpeg_path():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which('ffmpeg')

def office_path():
    found = shutil.which('soffice') or shutil.which('libreoffice')
    if found: return found
    for candidate in ('/Applications/LibreOffice.app/Contents/MacOS/soffice',
                      r'C:\Program Files\LibreOffice\program\soffice.exe',
                      r'C:\Program Files (x86)\LibreOffice\program\soffice.exe'):
        if os.path.exists(candidate): return candidate
    return None

def _has(module):
    try:
        __import__(module); return True
    except Exception:
        return False

NORMAL = {'jpeg':'jpg','jfif':'jpg','htm':'html','markdown':'md','yml':'yaml','tif':'tiff','tgz':'tar.gz','tbz2':'tar.bz2','txz':'tar.xz','aif':'aiff','oga':'ogg'}

def normal(ext):
    ext = ext.lower().lstrip('.')
    return NORMAL.get(ext, ext)

def office_kind(ext):
    if ext in {'pptx','ppt','odp','key'}: return 'slides'
    if ext in {'xlsx','xls','ods','numbers'}: return 'sheet'
    return 'text'

def targets(ext, office=None):
    """Output formats available for an input extension on this machine."""
    ext = normal(ext)
    office = office_path() if office is None else office
    out = []
    def add(items):
        for item in items:
            if item != ext and item not in out: out.append(item)
    if ext in VIDEO_IN: add(VIDEO_OUT + AUDIO_OUT)
    if ext in AUDIO_IN: add(AUDIO_OUT)
    if ext in IMAGE_IN and _has('PIL'):
        add(IMAGE_OUT)
        if ext == 'gif': add(['mp4','webm'])
    if ext in ('txt','md','markdown','html','htm'): add(DOC_OUT)
    if ext == 'docx' and _has('docx'): add(DOC_OUT)
    if ext == 'pdf':
        add(['txt','md','html','docx'])
        if _has('pypdfium2'): add(['png','jpg'])
    if office and ext in OFFICE_IN: add(OFFICE_OUT[office_kind(ext)])
    if ext in DATA_IN and (ext != 'xlsx' or _has('openpyxl')): add(DATA_OUT)
    if ext in ARCHIVE_IN: add(ARCHIVE_OUT)
    if not _has('reportlab'): out = [t for t in out if t != 'pdf' or ext in IMAGE_IN or (office and ext in OFFICE_IN)]
    if not _has('openpyxl'): out = [t for t in out if t != 'xlsx' or (office and ext in OFFICE_IN)]
    if not _has('docx'): out = [t for t in out if t != 'docx' or (office and ext in OFFICE_IN)]
    if not _has('yaml'): out = [t for t in out if t != 'yaml']
    if not ffmpeg_path(): out = [t for t in out if t not in VIDEO_OUT + AUDIO_OUT or ext in IMAGE_IN and t == 'gif']
    return out

def capabilities():
    office = office_path()
    inputs = sorted(VIDEO_IN | AUDIO_IN | IMAGE_IN | DOC_IN | DATA_IN | ARCHIVE_IN | (OFFICE_IN if office else set()))
    return {'office': bool(office), 'ffmpeg': bool(ffmpeg_path()),
            'formats': {ext: targets(ext, office) for ext in inputs if targets(ext, office)}}

# ---------------------------------------------------------------- media

def _ffmpeg(args, timeout):
    exe = ffmpeg_path()
    if not exe: raise ConversionError('FFmpeg is not available for audio and video conversion.')
    proc = subprocess.run([exe, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', *args],
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        detail = (proc.stderr or '').strip().splitlines()[-1:] or ['unknown error']
        raise ConversionError('FFmpeg could not convert this file: ' + detail[0][:300])

H264 = ['-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-vf','scale=trunc(iw/2)*2:trunc(ih/2)*2']
AUDIO_ARGS = {'mp3':['-c:a','libmp3lame','-b:a','192k'], 'm4a':['-c:a','aac','-b:a','192k'], 'wav':['-c:a','pcm_s16le'],
              'flac':['-c:a','flac'], 'opus':['-c:a','libopus','-b:a','160k'], 'ogg':['-c:a','libvorbis','-q:a','5'],
              'aac':['-c:a','aac','-b:a','192k','-f','adts']}

def convert_media(src, dst, target, timeout):
    i = ['-i', str(src)]
    if target in AUDIO_ARGS:
        return _ffmpeg([*i, '-vn', '-map', '0:a:0', *AUDIO_ARGS[target], str(dst)], timeout)
    if target == 'gif':
        graph = "fps=12,scale='min(640,iw)':-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse"
        return _ffmpeg([*i, '-t', '60', '-vf', graph, '-loop', '0', str(dst)], timeout)
    audio = ['-map', '0:v:0', '-map', '0:a:0?']
    if target in ('mp4', 'mov'):
        return _ffmpeg([*i, *audio, *H264, '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(dst)], timeout)
    if target == 'webm':
        return _ffmpeg([*i, *audio, '-c:v', 'libvpx-vp9', '-deadline', 'realtime', '-cpu-used', '6', '-row-mt', '1',
                        '-b:v', '0', '-crf', '34', '-c:a', 'libopus', '-b:a', '128k', str(dst)], timeout)
    if target == 'mkv':
        try: return _ffmpeg([*i, '-map', '0', '-c', 'copy', str(dst)], timeout)
        except ConversionError: return _ffmpeg([*i, *audio, *H264, '-c:a', 'aac', '-b:a', '160k', str(dst)], timeout)
    if target == 'avi':
        return _ffmpeg([*i, *audio, '-c:v', 'mpeg4', '-q:v', '4', '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
                        '-c:a', 'libmp3lame', '-b:a', '192k', str(dst)], timeout)
    raise ConversionError('Unsupported media format.')

# ---------------------------------------------------------------- images

def convert_image(src, dst, target):
    from PIL import Image, ImageOps, ImageSequence
    Image.MAX_IMAGE_PIXELS = 180_000_000
    with Image.open(src) as image:
        if target == 'pdf':
            frames = [ImageOps.exif_transpose(f.copy()).convert('RGB') for f in ImageSequence.Iterator(image)][:MAX_PDF_PAGES]
            frames[0].save(dst, 'PDF', save_all=True, append_images=frames[1:], resolution=150)
            return
        if target == 'gif' and getattr(image, 'is_animated', False):
            image.save(dst, save_all=True, loop=image.info.get('loop', 0)); return
        frame = ImageOps.exif_transpose(image.copy())
        if target in ('jpg', 'bmp') or (target == 'gif' and frame.mode not in ('P', 'L')):
            if frame.mode in ('RGBA', 'LA', 'P'):
                frame = frame.convert('RGBA'); base = Image.new('RGB', frame.size, (255, 255, 255))
                base.paste(frame, mask=frame.split()[-1]); frame = base
            frame = frame.convert('RGB')
        if target == 'jpg': return frame.save(dst, 'JPEG', quality=92, optimize=True)
        if target == 'webp': return frame.save(dst, 'WEBP', quality=90)
        if target == 'ico':
            frame.thumbnail((256, 256)); return frame.save(dst, 'ICO', sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256) if s <= max(frame.size)])
        if target == 'tiff': return frame.save(dst, 'TIFF', compression='tiff_lzw')
        frame.save(dst, {'png':'PNG','gif':'GIF','bmp':'BMP'}[target])

# ---------------------------------------------------------------- documents
# A document is a list of blocks: (kind, text) with kind in h1..h3, p, li, code.

class _HTMLBlocks(HTMLParser):
    BLOCK = {'p':'p','div':'p','h1':'h1','h2':'h2','h3':'h3','h4':'h3','h5':'h3','h6':'h3','li':'li','pre':'code',
             'blockquote':'p','tr':'p','br':None,'title':None}
    def __init__(self):
        super().__init__(convert_charrefs=True); self.blocks=[]; self.kind='p'; self.buf=[]; self.skip=0; self.pre=0
    def flush(self):
        text=''.join(self.buf); self.buf=[]
        text=text.strip('\n') if self.pre else re.sub(r'\s+',' ',text).strip()
        if text: self.blocks.append((self.kind,text))
        self.kind='p'
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','head','noscript','template'): self.skip+=1; return
        if tag=='br': self.buf.append('\n' if self.pre else ' '); return
        if tag in ('td','th'): self.buf.append(' | ' if self.buf else ''); return
        if tag in self.BLOCK: self.flush(); self.kind=self.BLOCK[tag] or 'p'
        if tag=='pre': self.pre+=1
    def handle_endtag(self,tag):
        if tag in ('script','style','head','noscript','template'): self.skip=max(0,self.skip-1); return
        if tag in self.BLOCK and tag!='br':
            self.flush()
            if tag=='pre': self.pre=max(0,self.pre-1)
    def handle_data(self,data):
        if not self.skip: self.buf.append(data)

def _md_inline(text):
    text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    return re.sub(r'(\*\*|__|`|\*|_)(.+?)\1', r'\2', text)

def read_blocks(path, ext, timeout):
    if ext in ('txt',):
        text = _read_text(path)
        return [('p', part.strip()) for part in re.split(r'\n\s*\n', text) if part.strip()]
    if ext in ('md', 'markdown'):
        return _md_blocks(_read_text(path))
    if ext in ('html', 'htm'):
        parser = _HTMLBlocks(); parser.feed(_read_text(path)); parser.flush(); return parser.blocks
    if ext == 'docx':
        import docx
        blocks = []
        for para in docx.Document(str(path)).paragraphs:
            text = para.text.strip(); style = (para.style.name if para.style is not None else '').lower()
            if not text: continue
            m = re.match(r'(heading|title)\s*(\d?)', style)
            kind = 'h1' if style.startswith('title') else ('h' + str(min(3, int(m.group(2) or 1)))) if m else ('li' if 'list' in style else 'p')
            blocks.append((kind, text))
        return blocks
    if ext == 'pdf':
        from pypdf import PdfReader
        reader = PdfReader(str(path)); blocks = []; started = time.monotonic()
        for number, page in enumerate(reader.pages[:2000], 1):
            if time.monotonic() - started > timeout: raise ConversionError('PDF text extraction took too long.')
            text = (page.extract_text() or '').strip()
            if len(reader.pages) > 1: blocks.append(('h2', f'Page {number}'))
            blocks += [('p', re.sub(r'[ \t]*\n[ \t]*', ' ', part).strip()) for part in re.split(r'\n\s*\n', text) if part.strip()]
        if not any(kind == 'p' for kind, _ in blocks):
            raise ConversionError('This PDF has no selectable text (it may be scanned images). Convert it to PNG or JPG instead.')
        return blocks
    raise ConversionError('Unsupported document format.')

def _md_blocks(text):
    blocks = []; para = []; code = None
    def flush():
        if para: blocks.append(('p', _md_inline(' '.join(para)))); para.clear()
    for line in text.splitlines():
        if line.strip().startswith('```'):
            if code is None: flush(); code = []
            else: blocks.append(('code', '\n'.join(code))); code = None
            continue
        if code is not None: code.append(line); continue
        m = re.match(r'(#{1,6})\s+(.*)', line)
        if m: flush(); blocks.append(('h' + str(min(3, len(m.group(1)))), _md_inline(m.group(2).strip('# ')))); continue
        m = re.match(r'\s*(?:[-*+]|\d+[.)])\s+(.*)', line)
        if m: flush(); blocks.append(('li', _md_inline(m.group(1)))); continue
        if not line.strip(): flush(); continue
        para.append(line.strip())
    flush()
    if code: blocks.append(('code', '\n'.join(code)))
    return blocks

def _read_text(path):
    raw = Path(path).read_bytes()
    for encoding in ('utf-8-sig', 'utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else ('utf-8-sig', 'cp1252', 'latin-1'):
        try: return raw.decode(encoding)
        except UnicodeDecodeError: continue
    return raw.decode('utf-8', 'replace')

def write_blocks(blocks, dst, target, title):
    if target == 'txt':
        out = []
        for kind, text in blocks:
            out.append(('• ' + text) if kind == 'li' else text.upper() if kind == 'h1' else text)
        return Path(dst).write_text('\n\n'.join(out) + '\n', encoding='utf-8')
    if target == 'md':
        prefix = {'h1':'# ','h2':'## ','h3':'### ','li':'- ','p':''}
        out = [f'```\n{t}\n```' if k == 'code' else prefix[k] + t for k, t in blocks]
        return Path(dst).write_text('\n\n'.join(out) + '\n', encoding='utf-8')
    if target == 'html':
        body = []; in_list = False
        for kind, text in blocks:
            if kind == 'li' and not in_list: body.append('<ul>'); in_list = True
            if kind != 'li' and in_list: body.append('</ul>'); in_list = False
            tag = {'code':'pre'}.get(kind, kind)
            body.append(f'<{tag}>{html.escape(text)}</{tag}>')
        if in_list: body.append('</ul>')
        page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{html.escape(title)}</title><style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;'
                'padding:0 20px;line-height:1.6}pre{background:#f4f4f4;padding:12px;overflow:auto}</style><body>\n' + '\n'.join(body) + '\n</body></html>\n')
        return Path(dst).write_text(page, encoding='utf-8')
    if target == 'docx':
        import docx
        document = docx.Document()
        for kind, text in blocks:
            if kind in ('h1', 'h2', 'h3'): document.add_heading(text, level=int(kind[1]))
            elif kind == 'li': document.add_paragraph(text, style='List Bullet')
            elif kind == 'code':
                run = document.add_paragraph().add_run(text); run.font.name = 'Courier New'
            else: document.add_paragraph(text)
        return document.save(str(dst))
    if target == 'pdf':
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import ListFlowable, ListItem, Paragraph, Preformatted, SimpleDocTemplate, Spacer
        styles = getSampleStyleSheet(); story = []; items = []
        def flush_list():
            if items: story.append(ListFlowable([ListItem(i) for i in items], bulletType='bullet')); items.clear()
        for kind, text in blocks:
            safe = html.escape(text).replace('\n', '<br/>')
            if kind == 'li': items.append(Paragraph(safe, styles['BodyText'])); continue
            flush_list()
            if kind == 'code': story.append(Preformatted(text, styles['Code']))
            else: story.append(Paragraph(safe, styles[{'h1':'Heading1','h2':'Heading2','h3':'Heading3'}.get(kind, 'BodyText')]))
            story.append(Spacer(1, 4))
        flush_list()
        if not story: story.append(Paragraph('(empty document)', styles['BodyText']))
        SimpleDocTemplate(str(dst), pagesize=A4, title=title, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm).build(story)
        return
    raise ConversionError('Unsupported document format.')

def pdf_to_images(src, dst, target, name):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(src))
    count = min(len(pdf), MAX_PDF_PAGES)
    if not count: raise ConversionError('This PDF has no pages.')
    def render(index):
        image = pdf[index].render(scale=2).to_pil()
        buffer = io.BytesIO()
        if target == 'jpg': image.convert('RGB').save(buffer, 'JPEG', quality=90)
        else: image.save(buffer, 'PNG')
        return buffer.getvalue()
    if count == 1:
        Path(dst).write_bytes(render(0)); return Path(dst)
    archive = Path(dst).with_name(f'{name}-{target}-pages.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as out:
        for index in range(count): out.writestr(f'{name}-page-{index + 1:03d}.{target}', render(index))
    return archive

def convert_office(src, dst, target, timeout):
    exe = office_path()
    if not exe: raise ConversionError('Office conversions need LibreOffice installed on this computer.')
    filters = {'txt':'txt:Text (encoded):UTF8', 'csv':'csv:Text - txt - csv (StarCalc):44,34,76', 'html':'html'}
    with tempfile.TemporaryDirectory(prefix='linkdrop-office-') as work:
        profile = Path(work) / 'profile'
        proc = subprocess.run([exe, f'-env:UserInstallation={profile.as_uri()}', '--headless', '--norestore',
                               '--convert-to', filters.get(target, target), '--outdir', work, str(src)],
                              capture_output=True, text=True, timeout=timeout)
        produced = [p for p in Path(work).iterdir() if p.is_file() and extension(p.name) == target]
        if proc.returncode or not produced:
            raise ConversionError('LibreOffice could not convert this file.')
        shutil.move(str(produced[0]), dst)

# ---------------------------------------------------------------- data

def read_rows(path, ext):
    if ext in ('csv', 'tsv'):
        text = _read_text(path)
        dialect = 'excel-tab' if ext == 'tsv' else 'excel'
        if ext == 'csv' and text.strip():
            try: dialect = csv.Sniffer().sniff(text[:4096], ',;|\t')
            except csv.Error: pass  # the sniffer gives up on some valid files; plain commas are the safe default
        return [row for row in csv.reader(io.StringIO(text), dialect)]
    if ext == 'json':
        return _tabular(json.loads(_read_text(path)))
    if ext in ('yaml', 'yml'):
        import yaml
        return _tabular(yaml.safe_load(_read_text(path)))
    if ext == 'xlsx':
        import openpyxl
        book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        rows = [['' if v is None else v for v in row] for row in book.active.iter_rows(values_only=True)]
        while rows and not any(str(v).strip() for v in rows[-1]): rows.pop()
        return rows
    raise ConversionError('Unsupported data format.')

def _tabular(value):
    if isinstance(value, dict):
        lists = [v for v in value.values() if isinstance(v, list)]
        value = lists[0] if len(lists) == 1 else [value]
    if not isinstance(value, list): value = [value]
    if all(isinstance(v, dict) for v in value):
        header = []
        for item in value:
            for key in item:
                if key not in header: header.append(key)
        return [header] + [[_cell(item.get(key, '')) for key in header] for item in value]
    if all(isinstance(v, list) for v in value):
        return [[_cell(c) for c in row] for row in value]
    return [['value']] + [[_cell(v)] for v in value]

def _cell(value):
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value

def _records(rows):
    if not rows: return []
    header = [str(h) if str(h) else f'column_{i + 1}' for i, h in enumerate(rows[0])]
    return [{header[i]: (row[i] if i < len(row) else '') for i in range(len(header))} for row in rows[1:]]

def write_rows(rows, dst, target, title):
    if target in ('csv', 'tsv'):
        with open(dst, 'w', newline='', encoding='utf-8') as out:
            csv.writer(out, 'excel-tab' if target == 'tsv' else 'excel').writerows(rows)
        return
    if target == 'json':
        return Path(dst).write_text(json.dumps(_records(rows), ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    if target == 'yaml':
        import yaml
        return Path(dst).write_text(yaml.safe_dump(_records(rows), allow_unicode=True, sort_keys=False, default_flow_style=False), encoding='utf-8')
    if target == 'xlsx':
        import openpyxl
        book = openpyxl.Workbook(write_only=True); sheet = book.create_sheet(title[:31] or 'Sheet1')
        for row in rows: sheet.append([v if isinstance(v, (int, float, bool)) or v is None else str(v) for v in row])
        return book.save(str(dst))
    if target == 'html':
        cells = lambda row, tag: ''.join(f'<{tag}>{html.escape(str(v))}</{tag}>' for v in row)
        body = (f'<thead><tr>{cells(rows[0], "th")}</tr></thead>' if rows else '') + '<tbody>' + ''.join(f'<tr>{cells(r, "td")}</tr>' for r in rows[1:]) + '</tbody>'
        return Path(dst).write_text(f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{html.escape(title)}</title>'
                                    '<style>table{border-collapse:collapse;font-family:system-ui,sans-serif}td,th{border:1px solid #ccc;padding:4px 8px}</style>'
                                    f'<table>{body}</table></html>\n', encoding='utf-8')
    if target == 'md':
        if not rows: return Path(dst).write_text('', encoding='utf-8')
        width = max(len(r) for r in rows)
        esc = lambda v: str(v).replace('|', '\\|').replace('\n', ' ')
        line = lambda r: '| ' + ' | '.join(esc(r[i]) if i < len(r) else '' for i in range(width)) + ' |'
        return Path(dst).write_text('\n'.join([line(rows[0]), '|' + '---|' * width] + [line(r) for r in rows[1:]]) + '\n', encoding='utf-8')
    raise ConversionError('Unsupported data format.')

# ---------------------------------------------------------------- archives

def convert_archive(src, dst, ext, target, work):
    extracted = Path(work) / 'extracted'; extracted.mkdir()
    total = 0
    def safe_target(name):
        path = (extracted / name).resolve()
        if extracted.resolve() not in path.parents: raise ConversionError('The archive contains unsafe paths.')
        return path
    if ext == 'zip':
        with zipfile.ZipFile(src) as archive:
            for info in archive.infolist():
                total += info.file_size
                if total > MAX_ARCHIVE_EXPANDED: raise ConversionError('The archive expands beyond 1 GB.')
                path = safe_target(info.filename)
                if info.is_dir(): path.mkdir(parents=True, exist_ok=True); continue
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, open(path, 'wb') as out: shutil.copyfileobj(source, out)
    else:
        with tarfile.open(src, 'r:*') as archive:
            for member in archive.getmembers():
                if not (member.isfile() or member.isdir()): continue
                total += member.size
                if total > MAX_ARCHIVE_EXPANDED: raise ConversionError('The archive expands beyond 1 GB.')
                path = safe_target(member.name)
                if member.isdir(): path.mkdir(parents=True, exist_ok=True); continue
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, open(path, 'wb') as out: shutil.copyfileobj(source, out)
    files = sorted(p for p in extracted.rglob('*') if p.is_file())
    if target == 'zip':
        with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as out:
            for p in files: out.write(p, p.relative_to(extracted).as_posix())
    else:
        mode = {'tar':'w','tar.gz':'w:gz','tar.bz2':'w:bz2','tar.xz':'w:xz'}[target]
        with tarfile.open(dst, mode) as out:
            for p in files: out.add(p, p.relative_to(extracted).as_posix())

# ---------------------------------------------------------------- dispatch

def convert(src, target, outdir, name=None, timeout=240):
    """Convert `src` to `target` inside `outdir`; return the produced Path."""
    src = Path(src); name = name or src.name
    ext = extension(name); target = target.lower().lstrip('.')
    ext = normal(ext)
    office = office_path()
    if target not in targets(ext, office): raise ConversionError(f'Converting .{ext or "?"} to .{target} is not supported here.')
    base = stem(name); dst = Path(outdir) / f'{base}.{target}'
    if dst.resolve() == src.resolve(): dst = Path(outdir) / f'{base}-converted.{target}'
    media_out = set(VIDEO_OUT + AUDIO_OUT)
    with tempfile.TemporaryDirectory(prefix='linkdrop-work-') as work:
        if ext in VIDEO_IN | AUDIO_IN or (ext == 'gif' and target in ('mp4', 'webm')):
            convert_media(src, dst, target, timeout)
        elif ext in IMAGE_IN:
            convert_image(src, dst, target)
        elif ext == 'pdf' and target in ('png', 'jpg'):
            dst = pdf_to_images(src, dst, target, base)
        elif office and ext in OFFICE_IN and (target == 'pdf' or not ((ext in DOC_IN and target in DOC_OUT) or (ext in DATA_IN and target in DATA_OUT))):
            convert_office(src, dst, target, timeout)
        elif ext in DATA_IN:
            write_rows(read_rows(src, ext), dst, target, base)
        elif ext in DOC_IN:
            write_blocks(read_blocks(src, ext, timeout), dst, target, base)
        elif ext in ARCHIVE_IN:
            convert_archive(src, dst, 'zip' if ext == 'zip' else 'tar', target, work)
        elif target in media_out:
            convert_media(src, dst, target, timeout)
        else:
            raise ConversionError(f'Converting .{ext} to .{target} is not supported here.')
    if not dst.is_file() or not dst.stat().st_size: raise ConversionError('The conversion produced an empty file.')
    return dst

# ---------------------------------------------------------------- direct downloads

def filename_from(url, headers):
    disposition = headers.get('Content-Disposition') or ''
    m = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)", disposition) or re.search(r'filename\s*=\s*"?([^";]+)"?', disposition)
    name = unquote(m.group(1)) if m else unquote(Path(urlparse(url).path).name)
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', name).strip(' .')
    if not name or '.' not in name:
        import mimetypes
        guessed = mimetypes.guess_extension((headers.get('Content-Type') or '').split(';')[0].strip()) or ''
        name = (name or 'download') + guessed
    return name[:160]

def fetch(url, outdir, max_bytes, guard=True, progress=None):
    """Download any file from a public link. Returns (Path, original name)."""
    if guard:
        try: from .netguard import public_url, protect_network
        except ImportError: from netguard import public_url, protect_network  # launched as a script
        public_url(url); protect_network()
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0 (LinkDrop file downloader)', 'Accept': '*/*'})
    with urlopen(request, timeout=30) as response:
        name = filename_from(response.geturl(), response.headers)
        declared = int(response.headers.get('Content-Length') or 0)
        if max_bytes and declared > max_bytes:
            raise ConversionError(f'This file is larger than the {max_bytes // 1048576} MB limit.')
        path = Path(outdir) / ('source.' + (extension(name) or 'bin')); done = 0; last = 0
        with open(path, 'wb') as out:
            while True:
                chunk = response.read(1 << 20)
                if not chunk: break
                done += len(chunk)
                if max_bytes and done > max_bytes:
                    raise ConversionError(f'This file is larger than the {max_bytes // 1048576} MB limit.')
                out.write(chunk)
                if progress and time.monotonic() - last > 1:
                    last = time.monotonic(); progress(done, declared)
    if not done: raise ConversionError('The link returned an empty file.')
    return path, name

# ---------------------------------------------------------------- hosted worker

def main():
    """NDJSON worker: reads one JSON request on stdin, emits events on stdout."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    data = json.loads(sys.stdin.readline())
    emit = lambda event: print(json.dumps(event), flush=True)
    folder = Path(data['folder']); max_bytes = int(data.get('maxBytes') or 0)
    if data.get('action') == 'capabilities':
        return emit(capabilities())
    if data.get('sourceUrl'):
        def progress(done, total): emit({'status':'downloading','progress':round(done / total * 100, 1) if total else 0})
        emit({'status':'downloading','progress':0})
        source, name = fetch(data['sourceUrl'], folder, max_bytes, guard=data.get('guard', True), progress=progress)
        name = data.get('filename') or name
    else:
        source = Path(data['input']); name = data.get('filename') or source.name
    target = data.get('target') or 'original'
    if target == 'original':
        result = folder / ('out-' + Path(name).name); shutil.move(str(source), result)
        final = Path(name).name
    else:
        emit({'status':'processing','progress':100})
        outdir = folder / 'out'; outdir.mkdir(exist_ok=True)
        result = convert(source, target, outdir, name, timeout=int(data.get('timeout') or 230)); final = result.name
    size = result.stat().st_size
    if max_bytes and size > max_bytes: raise ConversionError(f'The converted file exceeds the {max_bytes // 1048576} MB limit.')
    emit({'status':'uploading','title':final,'filename':final,'path':str(result),'size':size})

if __name__ == '__main__':
    try: main()
    except subprocess.TimeoutExpired:
        print(json.dumps({'status':'error','error':'The conversion took too long. Try a smaller file or the desktop app.'}), flush=True); sys.exit(1)
    except Exception as exc:
        print(json.dumps({'status':'error','error':str(exc)[:1200] or exc.__class__.__name__}), flush=True); sys.exit(1)
