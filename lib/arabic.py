"""Arabic shaping and right-to-left line ordering for LinkDrop's PDF writer.

Arabic letters change shape with their neighbours. PDF has no text shaping, so
letters are replaced by their Unicode presentation forms (isolated, final,
initial, medial, and lam-alef ligatures) and each line is put in visual order
with a simplified version of the Unicode bidi algorithm: runs of right-to-left
text are reversed, numbers and Latin text keep their order, and neutral
characters take the direction of the text around them.
"""
import unicodedata

# letter: (isolated, final, initial, medial); right-joining letters have no initial/medial.
FORMS = {
    0x0621: (0xFE80, None, None, None),
    0x0622: (0xFE81, 0xFE82, None, None), 0x0623: (0xFE83, 0xFE84, None, None),
    0x0624: (0xFE85, 0xFE86, None, None), 0x0625: (0xFE87, 0xFE88, None, None),
    0x0626: (0xFE89, 0xFE8A, 0xFE8B, 0xFE8C), 0x0627: (0xFE8D, 0xFE8E, None, None),
    0x0628: (0xFE8F, 0xFE90, 0xFE91, 0xFE92), 0x0629: (0xFE93, 0xFE94, None, None),
    0x062A: (0xFE95, 0xFE96, 0xFE97, 0xFE98), 0x062B: (0xFE99, 0xFE9A, 0xFE9B, 0xFE9C),
    0x062C: (0xFE9D, 0xFE9E, 0xFE9F, 0xFEA0), 0x062D: (0xFEA1, 0xFEA2, 0xFEA3, 0xFEA4),
    0x062E: (0xFEA5, 0xFEA6, 0xFEA7, 0xFEA8), 0x062F: (0xFEA9, 0xFEAA, None, None),
    0x0630: (0xFEAB, 0xFEAC, None, None), 0x0631: (0xFEAD, 0xFEAE, None, None),
    0x0632: (0xFEAF, 0xFEB0, None, None), 0x0633: (0xFEB1, 0xFEB2, 0xFEB3, 0xFEB4),
    0x0634: (0xFEB5, 0xFEB6, 0xFEB7, 0xFEB8), 0x0635: (0xFEB9, 0xFEBA, 0xFEBB, 0xFEBC),
    0x0636: (0xFEBD, 0xFEBE, 0xFEBF, 0xFEC0), 0x0637: (0xFEC1, 0xFEC2, 0xFEC3, 0xFEC4),
    0x0638: (0xFEC5, 0xFEC6, 0xFEC7, 0xFEC8), 0x0639: (0xFEC9, 0xFECA, 0xFECB, 0xFECC),
    0x063A: (0xFECD, 0xFECE, 0xFECF, 0xFED0), 0x0641: (0xFED1, 0xFED2, 0xFED3, 0xFED4),
    0x0642: (0xFED5, 0xFED6, 0xFED7, 0xFED8), 0x0643: (0xFED9, 0xFEDA, 0xFEDB, 0xFEDC),
    0x0644: (0xFEDD, 0xFEDE, 0xFEDF, 0xFEE0), 0x0645: (0xFEE1, 0xFEE2, 0xFEE3, 0xFEE4),
    0x0646: (0xFEE5, 0xFEE6, 0xFEE7, 0xFEE8), 0x0647: (0xFEE9, 0xFEEA, 0xFEEB, 0xFEEC),
    0x0648: (0xFEED, 0xFEEE, None, None), 0x0649: (0xFEEF, 0xFEF0, None, None),
    0x064A: (0xFEF1, 0xFEF2, 0xFEF3, 0xFEF4),
    0x067E: (0xFB56, 0xFB57, 0xFB58, 0xFB59), 0x0686: (0xFB7A, 0xFB7B, 0xFB7C, 0xFB7D),
    0x0698: (0xFB8A, 0xFB8B, None, None), 0x06A9: (0xFB8E, 0xFB8F, 0xFB90, 0xFB91),
    0x06AF: (0xFB92, 0xFB93, 0xFB94, 0xFB95), 0x06CC: (0xFBFC, 0xFBFD, 0xFBFE, 0xFBFF),
}
LAM_ALEF = {0x0622: (0xFEF5, 0xFEF6), 0x0623: (0xFEF7, 0xFEF8), 0x0625: (0xFEF9, 0xFEFA), 0x0627: (0xFEFB, 0xFEFC)}
TATWEEL = 0x0640
MIRROR = str.maketrans('()[]{}<>«»', ')(][}{><»«')

def _transparent(ch):
    return unicodedata.category(ch) == 'Mn'

def _dual(cp):  # joins on both sides
    return cp == TATWEEL or (cp in FORMS and FORMS[cp][2] is not None)

def _joins(cp):  # can join to the previous letter
    return cp == TATWEEL or (cp in FORMS and FORMS[cp][1] is not None)

def has_rtl(text):
    return any(unicodedata.bidirectional(ch) in ('R', 'AL') for ch in text)

def shape(text):
    """Replace Arabic letters with their contextual presentation forms (logical order kept)."""
    if not any(0x0600 <= ord(ch) <= 0x06FF for ch in text): return text
    chars = list(text); out = []; i = 0
    def neighbour(index, step):
        index += step
        while 0 <= index < len(chars) and _transparent(chars[index]): index += step
        return ord(chars[index]) if 0 <= index < len(chars) else None
    while i < len(chars):
        cp = ord(chars[i])
        if cp not in FORMS and cp != TATWEEL: out.append(chars[i]); i += 1; continue
        prev = neighbour(i, -1); after = neighbour(i, 1)
        joined_prev = _joins(cp) and prev is not None and _dual(prev)
        if cp == 0x0644 and after in LAM_ALEF:  # lam + alef ligature
            j = i + 1
            while _transparent(chars[j]): j += 1
            marks = chars[i + 1:j]
            out.append(chr(LAM_ALEF[after][1 if joined_prev else 0])); out.extend(marks); i = j + 1; continue
        if cp == TATWEEL: out.append(chars[i]); i += 1; continue
        joined_next = _dual(cp) and after is not None and _joins(after)
        iso, fin, ini, med = FORMS[cp]
        form = med if joined_prev and joined_next else fin if joined_prev else ini if joined_next else iso
        out.append(chr(form or iso)); i += 1
    return ''.join(out)

def _kind(ch):
    b = unicodedata.bidirectional(ch)
    if b in ('R', 'AL'): return 'R'
    if b in ('L', 'EN', 'AN'): return 'L'
    return 'N'

def base_direction(text):
    for ch in text:
        kind = _kind(ch)
        if kind == 'R': return 'rtl'
        if kind == 'L' and unicodedata.bidirectional(ch) == 'L': return 'ltr'
    return 'ltr'

def visual(line, direction):
    """Reorder one shaped line from logical to visual (left-to-right drawing) order."""
    if not has_rtl(line) and direction == 'ltr': return line
    kinds = [_kind(ch) for ch in line]
    # neutrals take the surrounding direction when both sides agree, else the paragraph direction
    base = 'R' if direction == 'rtl' else 'L'
    for i, k in enumerate(kinds):
        if k != 'N': continue
        j = i
        while j < len(kinds) and kinds[j] == 'N': j += 1
        left = next((kinds[x] for x in range(i - 1, -1, -1) if kinds[x] != 'N'), base)
        right = kinds[j] if j < len(kinds) else base
        resolved = left if left == right else base
        for x in range(i, j): kinds[x] = resolved
    runs = []
    for ch, k in zip(line, kinds):
        if runs and runs[-1][0] == k: runs[-1][1].append(ch)
        else: runs.append([k, [ch]])
    pieces = [''.join(reversed(chars)).translate(MIRROR) if k == 'R' else ''.join(chars) for k, chars in runs]
    return ''.join(reversed(pieces)) if direction == 'rtl' else ''.join(pieces)
