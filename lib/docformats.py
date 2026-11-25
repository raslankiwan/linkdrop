"""Dependency-free .docx reading/writing and simple text PDFs.

Kept in the standard library on purpose: python-docx (with lxml) and reportlab
pushed the hosted Vercel function past its 225 MB bundle limit.
"""
import re, zipfile, zlib
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
q = lambda tag: f'{{{W}}}{tag}'

# ---------------------------------------------------------------- docx

def read_docx(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read('word/document.xml'))
        names = {}
        if 'word/styles.xml' in z.namelist():
            for style in ET.fromstring(z.read('word/styles.xml')).iter(q('style')):
                name = style.find(q('name'))
                names[style.get(q('styleId'))] = (name.get(q('val')) if name is not None else '') or ''
    blocks = []
    for para in root.iter(q('p')):
        parts = []
        for node in para.iter():
            if node.tag == q('t'): parts.append(node.text or '')
            elif node.tag == q('tab'): parts.append('\t')
            elif node.tag in (q('br'), q('cr')): parts.append('\n')
        text = ''.join(parts).strip()
        if not text: continue
        props = para.find(q('pPr'))
        style_id = ''
        if props is not None and props.find(q('pStyle')) is not None: style_id = props.find(q('pStyle')).get(q('val')) or ''
        style = (names.get(style_id) or style_id).lower()
        m = re.match(r'(heading|title)\s*(\d?)', style)
        if style == 'code': kind = 'code'
        elif style.startswith('title'): kind = 'h1'
        elif m: kind = 'h' + str(min(3, int(m.group(2) or 1)))
        elif 'list' in style or (props is not None and props.find(q('numPr')) is not None): kind = 'li'
        else: kind = 'p'
        if kind == 'li': text = re.sub(r'^[•\-\*·]\s*', '', text)
        blocks.append((kind, text))
    return blocks

_CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
       '<Default Extension="xml" ContentType="application/xml"/>'
       '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
       '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
       '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
       '</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
         '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
         '</Relationships>')
_DOC_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
             '</Relationships>')

def _style(style_id, name, size, bold=False, font=None, indent=False, space=120):
    run = (f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>' if font else '') + ('<w:b/>' if bold else '') + f'<w:sz w:val="{size}"/>'
    ppr = f'<w:spacing w:before="{space if bold else 0}" w:after="120"/>' + ('<w:ind w:left="360" w:hanging="360"/>' if indent else '')
    return (f'<w:style w:type="paragraph" w:styleId="{style_id}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/>'
            f'<w:pPr>{ppr}</w:pPr><w:rPr>{run}</w:rPr></w:style>')

_STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:styles xmlns:w="{W}">'
           '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Arial"/><w:sz w:val="22"/><w:szCs w:val="24"/></w:rPr></w:rPrDefault>'
           '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
           '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
           + _style('Heading1', 'heading 1', 36, True, space=360) + _style('Heading2', 'heading 2', 30, True, space=240)
           + _style('Heading3', 'heading 3', 26, True, space=200) + _style('ListBullet', 'List Bullet', 22, indent=True)
           + _style('Code', 'Code', 20, font='Courier New') + '</w:styles>')

def _runs(text, rtl=False):
    rpr = '<w:rPr><w:rtl/></w:rPr>' if rtl else ''
    out = []
    for i, line in enumerate(text.split('\n')):
        if i: out.append(f'<w:r>{rpr}<w:br/></w:r>')
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(line)}</w:t></w:r>')
    return ''.join(out)

def _rtl(text):
    try: from . import arabic
    except ImportError: import arabic
    return arabic.base_direction(text) == 'rtl'

def write_docx(blocks, dst, title):
    styles = {'h1':'Heading1','h2':'Heading2','h3':'Heading3','li':'ListBullet','code':'Code'}
    body = []
    for kind, text in blocks:
        style = styles.get(kind)
        rtl = _rtl(text)  # right-to-left paragraph (Arabic, Hebrew): Word shapes and orders it
        inner = (f'<w:pStyle w:val="{style}"/>' if style else '') + ('<w:bidi/><w:jc w:val="right"/>' if rtl else '')
        ppr = f'<w:pPr>{inner}</w:pPr>' if inner else ''
        body.append(f'<w:p>{ppr}{_runs(("• " + text) if kind == "li" else text, rtl)}</w:p>')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}"><w:body>' + ''.join(body) +
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
                '</w:body></w:document>')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            f'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{escape(title)}</dc:title><dc:creator>LinkDrop</dc:creator></cp:coreProperties>')
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', _CT); z.writestr('_rels/.rels', _RELS)
        z.writestr('word/_rels/document.xml.rels', _DOC_RELS); z.writestr('word/document.xml', document)
        z.writestr('word/styles.xml', _STYLES); z.writestr('docProps/core.xml', core)

# ---------------------------------------------------------------- pdf
# Text is drawn with embedded DejaVu fonts (Latin, Greek, Cyrillic, Arabic,
# Hebrew) using Identity-H glyph encoding, so any of those scripts render and
# can be copied back out of the PDF. Arabic is shaped and ordered right to left.

import struct
from pathlib import Path
try: from . import arabic
except ImportError: import arabic  # launched as a script (hosted worker)

FONT_DIR = Path(__file__).resolve().parent / 'fonts'

class TrueType:
    """The few TrueType tables a PDF needs: glyph ids, advance widths and metrics."""
    def __init__(self, path):
        self.path = Path(path); self.data = data = self.path.read_bytes()
        count = struct.unpack('>H', data[4:6])[0]
        self.tables = {data[12 + 16 * i:16 + 16 * i].decode('latin-1'): struct.unpack('>II', data[20 + 16 * i:28 + 16 * i]) for i in range(count)}
        head = self.table('head'); self.upem = struct.unpack('>H', head[18:20])[0]
        self.bbox = struct.unpack('>hhhh', head[36:44])
        hhea = self.table('hhea'); self.ascent, self.descent = struct.unpack('>hh', hhea[4:8])
        metrics = struct.unpack('>H', hhea[34:36])[0]; hmtx = self.table('hmtx')
        self.advances = [struct.unpack('>H', hmtx[4 * i:4 * i + 2])[0] for i in range(metrics)]
        self.italic = struct.unpack('>i', self.table('post')[4:8])[0] / 65536
        self.cmap = self._cmap()
    def table(self, tag):
        offset, length = self.tables[tag]; return self.data[offset:offset + length]
    def _cmap(self):
        cmap = self.table('cmap'); count = struct.unpack('>H', cmap[2:4])[0]; subtables = {}
        for i in range(count):
            platform, encoding, offset = struct.unpack('>HHI', cmap[4 + 8 * i:12 + 8 * i])
            subtables[(platform, encoding)] = offset
        mapping = {}
        for key in ((3, 10), (0, 4), (3, 1), (0, 3)):
            if key not in subtables: continue
            offset = subtables[key]; fmt = struct.unpack('>H', cmap[offset:offset + 2])[0]
            if fmt == 12:
                groups = struct.unpack('>I', cmap[offset + 12:offset + 16])[0]
                for g in range(groups):
                    start, end, glyph = struct.unpack('>III', cmap[offset + 16 + 12 * g:offset + 28 + 12 * g])
                    for cp in range(start, end + 1): mapping[cp] = glyph + cp - start
                return mapping
            if fmt == 4:
                segs = struct.unpack('>H', cmap[offset + 6:offset + 8])[0] // 2
                arr = lambda base: struct.unpack(f'>{segs}H', cmap[base:base + 2 * segs])
                ends = arr(offset + 14); starts = arr(offset + 16 + 2 * segs)
                deltas = struct.unpack(f'>{segs}h', cmap[offset + 16 + 4 * segs:offset + 16 + 6 * segs])
                ro_base = offset + 16 + 6 * segs; ranges = arr(ro_base)
                for s_ in range(segs):
                    for cp in range(starts[s_], ends[s_] + 1):
                        if cp == 0xFFFF: continue
                        if ranges[s_] == 0: glyph = (cp + deltas[s_]) & 0xFFFF
                        else:
                            at = ro_base + 2 * s_ + ranges[s_] + 2 * (cp - starts[s_])
                            glyph = struct.unpack('>H', cmap[at:at + 2])[0]
                            if glyph: glyph = (glyph + deltas[s_]) & 0xFFFF
                        if glyph: mapping[cp] = glyph
                return mapping
        return mapping
    def glyph(self, ch): return self.cmap.get(ord(ch), 0)
    def advance(self, glyph): return self.advances[min(glyph, len(self.advances) - 1)] * 1000 / self.upem
    def width(self, text, size): return sum(self.advance(self.glyph(c)) for c in text) * size / 1000

_FONTS = {}
def _font(name):
    if name not in _FONTS: _FONTS[name] = TrueType(FONT_DIR / name)
    return _FONTS[name]

def _wrap(text, size, font, width):
    lines = []
    for raw in text.split('\n'):
        words = raw.split(' '); line = ''
        for word in words:
            trial = f'{line} {word}' if line else word
            if font.width(trial, size) <= width or not line: line = trial
            else: lines.append(line); line = word
            while font.width(line, size) > width and len(line) > 1:  # break very long words
                cut = len(line)
                while cut > 1 and font.width(line[:cut], size) > width: cut -= 1
                lines.append(line[:cut]); line = line[cut:]
        lines.append(line)
    return lines

def _latin_only(blocks, title):
    try:
        for _, text in blocks: text.encode('cp1252')
        title.encode('cp1252'); return True
    except UnicodeEncodeError: return False

def write_pdf(blocks, dst, title):
    """Western European text uses the built-in PDF fonts (small files); anything else embeds DejaVu."""
    if _latin_only(blocks, title): return _write_pdf_latin(blocks, dst, title)
    return _write_pdf_unicode(blocks, dst, title)

def _write_pdf_unicode(blocks, dst, title):
    """A4 PDF with embedded fonts: Arabic shaped and right-to-left, plus Latin, Greek, Cyrillic, Hebrew."""
    W_, H_, M = 595.28, 841.89, 56.7
    names = {'F1': 'DejaVuSans.ttf', 'F2': 'DejaVuSans-Bold.ttf', 'F3': 'DejaVuSansMono.ttf'}
    style = {'h1': ('F2', 18, 10), 'h2': ('F2', 15, 8), 'h3': ('F2', 13, 6), 'p': ('F1', 10.5, 4), 'li': ('F1', 10.5, 2), 'code': ('F3', 9, 4)}
    used = {key: set() for key in names}
    pages = [[]]; y = H_ - M
    for kind, text in blocks or [('p', '(empty document)')]:
        key, size, gap = style.get(kind, style['p'])
        if key == 'F3' and arabic.has_rtl(text): key = 'F1'
        font = _font(names[key]); direction = arabic.base_direction(text)
        shaped = arabic.shape(text); indent = 16 if kind == 'li' else 0
        lead = size * 1.45
        lines = _wrap(shaped, size, font, W_ - 2 * M - indent)
        if kind.startswith('h'): y -= size * 0.6
        for i, line in enumerate(lines):
            if y - lead < M: pages.append([]); y = H_ - M
            y -= lead
            drawn = arabic.visual(line, direction); line_width = font.width(drawn, size)
            x = W_ - M - indent - line_width if direction == 'rtl' else M + indent
            if kind == 'li' and i == 0:
                bullet_x = W_ - M - 10 if direction == 'rtl' else M + 3
                pages[-1].append(('F1', size, bullet_x, y, '•')); used['F1'].add('•')
            pages[-1].append((key, size, x, y, drawn)); used[key].update(drawn)
    objects = []
    def add(body): objects.append(body); return len(objects)
    font_refs = {}
    for key, name in names.items():
        if not used[key]: continue
        font = _font(name); scale = 1000 / font.upem
        glyphs = {}
        for ch in used[key]: glyphs.setdefault(font.glyph(ch), ch)
        data = zlib.compress(font.data)
        file_ref = add(f'<< /Length {len(data)} /Length1 {len(font.data)} /Filter /FlateDecode >>\nstream\n'.encode() + data + b'\nendstream')
        bbox = ' '.join(str(round(v * scale)) for v in font.bbox)
        base = 'LinkDrop+' + name.rsplit('.', 1)[0].replace('-', '')
        descriptor = add(f'<< /Type /FontDescriptor /FontName /{base} /Flags 32 /FontBBox [{bbox}] /ItalicAngle {font.italic:g} '
                         f'/Ascent {round(font.ascent * scale)} /Descent {round(font.descent * scale)} /CapHeight {round(font.ascent * scale)} /StemV 80 /FontFile2 {file_ref} 0 R >>')
        widths = ' '.join(f'{g} [{round(font.advance(g))}]' for g in sorted(glyphs))
        cid = add(f'<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{base} /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> '
                  f'/FontDescriptor {descriptor} 0 R /DW 600 /W [{widths}] /CIDToGIDMap /Identity >>')
        def utf16(ch): return ''.join(f'{u:04X}' for u in struct.unpack(f'>{len(ch.encode("utf-16-be")) // 2}H', ch.encode('utf-16-be')))
        entries = [f'<{g:04X}> <{utf16(ch)}>' for g, ch in sorted(glyphs.items()) if g]
        chunks = [entries[i:i + 100] for i in range(0, len(entries), 100)]
        cmap = ('/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def '
                '/CMapName /Adobe-Identity-UCS def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange\n'
                + ''.join(f'{len(c)} beginbfchar\n' + '\n'.join(c) + '\nendbfchar\n' for c in chunks)
                + 'endcmap CMapName currentdict /CMap defineresource pop end end').encode()
        to_unicode = add(f'<< /Length {len(cmap)} >>\nstream\n'.encode() + cmap + b'\nendstream')
        font_refs[key] = add(f'<< /Type /Font /Subtype /Type0 /BaseFont /{base} /Encoding /Identity-H /DescendantFonts [{cid} 0 R] /ToUnicode {to_unicode} 0 R >>')
    pages_id = len(objects) + 1; objects.append(None)
    resources = '<< /Font << ' + ' '.join(f'/{k} {v} 0 R' for k, v in font_refs.items()) + ' >> >>'
    kids = []
    for page in pages:
        ops = ''.join(f'/{k} {s} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm <{"".join(f"{_font(names[k]).glyph(c):04X}" for c in t)}> Tj\n' for k, s, x, y, t in page if t)
        data = zlib.compress(('BT\n' + ops + 'ET').encode('latin-1'))
        content = add(f'<< /Length {len(data)} /Filter /FlateDecode >>\nstream\n'.encode() + data + b'\nendstream')
        kids.append(add(f'<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {W_} {H_}] /Contents {content} 0 R /Resources {resources} >>'))
    objects[pages_id - 1] = f'<< /Type /Pages /Kids [{" ".join(f"{k} 0 R" for k in kids)}] /Count {len(kids)} >>'
    title_hex = 'FEFF' + title.encode('utf-16-be').hex().upper()
    info = add(f'<< /Title <{title_hex}> /Producer (LinkDrop) >>')
    catalog = add(f'<< /Type /Catalog /Pages {pages_id} 0 R >>')
    out = bytearray(b'%PDF-1.5\n%\xe2\xe3\xcf\xd3\n'); offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f'{number} 0 obj\n'.encode() + (body if isinstance(body, bytes) else body.encode('latin-1')) + b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode() + ''.join(f'{o:010d} 00000 n \n' for o in offsets).encode()
    out += f'trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    with open(dst, 'wb') as f: f.write(out)

# ---------------------------------------------------------------- pdf, Western European only

# Helvetica widths (1/1000 em) for printable ASCII; other characters use 556.
_HELV = [278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278]+[556]*10+[278,278,584,584,584,556,1015,667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,667,778,722,667,611,722,667,944,667,667,611,278,278,278,469,556,333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,556,556,333,500,278,556,500,722,500,500,500,334,260,334,584]
_HELV_BOLD = [278,333,474,556,556,889,722,238,333,333,389,584,278,333,278,278]+[556]*10+[333,333,584,584,584,611,975,722,722,722,722,667,611,778,722,278,556,722,611,833,722,778,667,778,722,667,611,722,667,944,667,667,611,333,278,333,584,556,333,556,611,556,611,556,333,611,611,278,278,556,278,889,611,611,611,611,389,556,333,611,556,778,556,556,500,389,280,389,584]

def _latin_width(text, size, font):
    if font == 'F3': return len(text) * 600 * size / 1000
    table = _HELV_BOLD if font == 'F2' else _HELV
    return sum(table[ord(c) - 32] if 32 <= ord(c) < 127 else 556 for c in text) * size / 1000

def _latin_wrap(text, size, font, width):
    lines = []
    for raw in text.split('\n'):
        words = raw.split(' ') if font != 'F3' else [raw]
        line = ''
        for word in words:
            trial = f'{line} {word}' if line else word
            if _latin_width(trial, size, font) <= width or not line: line = trial
            else: lines.append(line); line = word
            while font != 'F3' and _latin_width(line, size, font) > width and len(line) > 1:  # break very long words
                cut = len(line)
                while cut > 1 and _latin_width(line[:cut], size, font) > width: cut -= 1
                lines.append(line[:cut]); line = line[cut:]
        if font == 'F3':
            while _latin_width(line, size, font) > width:
                cut = int(width / (0.6 * size)); lines.append(line[:cut]); line = line[cut:]
        lines.append(line)
    return lines

def _pdf_text(s):
    data = s.encode('cp1252', 'replace')
    return '(' + data.decode('latin-1').replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)') + ')'

def _write_pdf_latin(blocks, dst, title):
    """Small PDF using the 14 standard PDF fonts (no embedding); Western European text only."""
    W_, H_, M = 595.28, 841.89, 56.7
    style = {'h1': ('F2', 18, 10), 'h2': ('F2', 15, 8), 'h3': ('F2', 13, 6), 'p': ('F1', 11, 4), 'li': ('F1', 11, 2), 'code': ('F3', 9.5, 4)}
    pages = [[]]; y = H_ - M
    for kind, text in blocks or [('p', '(empty document)')]:
        font, size, gap = style.get(kind, style['p'])
        indent = 18 if kind == 'li' else 0
        lead = size * 1.35
        lines = _latin_wrap(text, size, font, W_ - 2 * M - indent)
        if kind.startswith('h'): y -= size * 0.6
        for i, line in enumerate(lines):
            if y - lead < M: pages.append([]); y = H_ - M
            y -= lead
            if kind == 'li' and i == 0: pages[-1].append(('F1', size, M + 4, y, '•'))
            pages[-1].append((font, size, M + indent, y, line))
        y -= gap
    objects = []
    def add(body): objects.append(body); return len(objects)
    fonts = [add(f'<< /Type /Font /Subtype /Type1 /BaseFont /{name} /Encoding /WinAnsiEncoding >>') for name in ('Helvetica', 'Helvetica-Bold', 'Courier')]
    pages_id = len(objects) + 1; objects.append(None)
    kids = []
    for page in pages:
        stream = 'BT\n' + ''.join(f'/{f} {s} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm {_pdf_text(t)} Tj\n' for f, s, x, y, t in page) + 'ET'
        data = zlib.compress(stream.encode('latin-1'))
        content = add((f'<< /Length {len(data)} /Filter /FlateDecode >>\nstream\n'.encode() + data + b'\nendstream'))
        kids.append(add(f'<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {W_} {H_}] /Contents {content} 0 R '
                        f'/Resources << /Font << /F1 {fonts[0]} 0 R /F2 {fonts[1]} 0 R /F3 {fonts[2]} 0 R >> >> >>'))
    objects[pages_id - 1] = f'<< /Type /Pages /Kids [{" ".join(f"{k} 0 R" for k in kids)}] /Count {len(kids)} >>'
    info = add(f'<< /Title {_pdf_text(title)} /Producer (LinkDrop) >>')
    catalog = add(f'<< /Type /Catalog /Pages {pages_id} 0 R >>')
    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n'); offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f'{number} 0 obj\n'.encode() + (body if isinstance(body, bytes) else body.encode('latin-1')) + b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode() + ''.join(f'{o:010d} 00000 n \n' for o in offsets).encode()
    out += f'trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    with open(dst, 'wb') as f: f.write(out)
