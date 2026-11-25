# PyInstaller spec for the LinkDrop desktop app (macOS .app and Windows folder build).
# Build from the repository root:  pyinstaller desktop/linkdrop.spec --noconfirm
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parent
VERSION = __import__('os').environ.get('LINKDROP_VERSION', '1.1.0')

datas = [(str(ROOT / 'index.html'), '.'), (str(ROOT / 'public'), 'public')]
binaries = []
hiddenimports = ['server', 'lib.convert', 'lib.engine', 'lib.errors', 'lib.netguard', 'lib.storage']
for package in ('yt_dlp', 'yt_dlp_ejs', 'imageio_ffmpeg', 'pypdfium2', 'pypdfium2_raw'):
    try:
        d, b, h = collect_all(package)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass
datas += collect_data_files('openpyxl')

a = Analysis([str(ROOT / 'desktop' / 'launcher.py')], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=['fastapi', 'vercel', 'pandas', 'numpy', 'matplotlib'], noarchive=False)
pyz = PYZ(a.pure)
icon = str(ROOT / 'build' / ('icon.icns' if sys.platform == 'darwin' else 'icon.ico'))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LinkDrop', console=False, icon=icon,
          version=None, upx=False, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name='LinkDrop', upx=False)
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='LinkDrop.app', icon=icon, bundle_identifier='io.github.raslankiwan.linkdrop',
                 info_plist={'CFBundleShortVersionString': VERSION, 'CFBundleVersion': VERSION, 'NSHighResolutionCapable': True,
                             'LSApplicationCategoryType': 'public.app-category.utilities'})
