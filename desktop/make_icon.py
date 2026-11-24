"""Draw the LinkDrop app icon and write .icns (macOS), .ico (Windows) and .png."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

def draw(size=1024):
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    pad = size * 0.06
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=size * 0.22, fill=(217, 244, 104, 255))
    ink = (38, 57, 44, 255); w = size * 0.085; cx = size / 2
    d.line([(cx, size * 0.24), (cx, size * 0.62)], fill=ink, width=int(w))
    d.polygon([(size * 0.30, size * 0.52), (size * 0.70, size * 0.52), (cx, size * 0.76)], fill=ink)
    d.rounded_rectangle([size * 0.27, size * 0.79, size * 0.73, size * 0.79 + w], radius=w / 2, fill=ink)
    return image

if __name__ == '__main__':
    out = Path(sys.argv[1] if len(sys.argv) > 1 else 'build/icon'); out.parent.mkdir(parents=True, exist_ok=True)
    icon = draw()
    icon.save(out.with_suffix('.png'))
    icon.save(out.with_suffix('.ico'), sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    icon.save(out.with_suffix('.icns'))
    print('wrote', out.with_suffix('.icns'), out.with_suffix('.ico'))
