"""LinkDrop desktop app: runs the local server and shows LinkDrop in its own native window.

The window uses the operating system's web view (WebKit on macOS, Edge WebView2 on
Windows) through pywebview, so no browser is needed. Everything the window loads
comes from LinkDrop's own local server, so there are no cross-origin requests.
If a native window can't be created, LinkDrop falls back to opening the default
browser with a small control window.
"""
import json, os, socket, subprocess, sys, threading, urllib.request, webbrowser
from pathlib import Path

if getattr(sys, 'frozen', False):
    sys.path.insert(0, getattr(sys, '_MEIPASS'))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PORT = 8765  # The web app's "Try in the desktop app" link points here.
URL = f'http://127.0.0.1:{PORT}'

def already_running():
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(('127.0.0.1', PORT)) == 0

def open_folder(path):
    path = str(path)
    if sys.platform == 'darwin': subprocess.Popen(['open', path])
    elif os.name == 'nt': os.startfile(path)  # type: ignore[attr-defined]
    else: subprocess.Popen(['xdg-open', path])

def app_data():
    if sys.platform == 'darwin': base = Path.home() / 'Library' / 'Application Support'
    elif os.name == 'nt': base = Path(os.environ.get('APPDATA') or Path.home())
    else: base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    path = base / 'LinkDrop'; path.mkdir(parents=True, exist_ok=True)
    return path

def smoke_test():
    """Used by the release build: start the bundled server, convert files, exit 0 on success."""
    import tempfile, server
    from lib import convert
    httpd = server.serve(0); threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{httpd.server_port}'
    caps = json.load(urllib.request.urlopen(base + '/api/capabilities', timeout=10))
    assert caps['ffmpeg'] and 'pdf' in caps['formats']['md'] and 'png' in caps['formats']['pdf'], caps
    html = urllib.request.urlopen(base + '/?desktop=1', timeout=10).read().decode()
    assert 'convert.js' in html and 'DESKTOP' in html
    with tempfile.TemporaryDirectory() as work:
        src = Path(work) / 'تقرير.md'; src.write_text('# تقرير\n\nمرحبا 2026', encoding='utf-8')
        pdf = convert.convert(src, 'pdf', work, src.name)
        assert pdf.read_bytes().startswith(b'%PDF')
        wav = Path(work) / 'tone.wav'
        subprocess.run([convert.ffmpeg_path(), '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1', str(wav)], check=True)
        assert convert.convert(wav, 'mp3', work, wav.name).stat().st_size > 0
        png = convert.convert(pdf, 'png', work, pdf.name)
        assert png.stat().st_size > 0
    httpd.shutdown()
    print('LinkDrop smoke test passed')

def browser_fallback(httpd, server):
    threading.Timer(0.6, lambda: webbrowser.open(URL)).start()
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        try: threading.Event().wait()
        except KeyboardInterrupt: pass
        return
    root = tk.Tk(); root.title('LinkDrop'); root.resizable(False, False)
    frame = ttk.Frame(root, padding=18); frame.grid()
    ttk.Label(frame, text='LinkDrop is running', font=('', 14, 'bold')).grid(column=0, row=0, columnspan=3, sticky='w')
    ttk.Label(frame, text=f'{URL}\nFiles are saved in {server.DATA}', justify='left').grid(column=0, row=1, columnspan=3, sticky='w', pady=(6, 14))
    ttk.Button(frame, text='Open LinkDrop', command=lambda: webbrowser.open(URL)).grid(column=0, row=2, padx=(0, 6))
    ttk.Button(frame, text='Open downloads folder', command=lambda: open_folder(server.DATA)).grid(column=1, row=2, padx=6)
    def quit_app():
        root.destroy(); threading.Thread(target=httpd.shutdown, daemon=True).start()
    ttk.Button(frame, text='Quit', command=quit_app).grid(column=2, row=2, padx=(6, 0))
    root.protocol('WM_DELETE_WINDOW', quit_app)
    root.mainloop()

def main():
    if os.environ.get('LINKDROP_SMOKE'):
        try: smoke_test(); sys.exit(0)
        except Exception as exc:
            print('LinkDrop smoke test failed:', repr(exc), file=sys.stderr); sys.exit(1)
    httpd = None
    if not already_running():
        import server
        httpd = server.serve(PORT)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        import webview
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
        webview.create_window('LinkDrop', URL + '/?desktop=1', width=1180, height=880, min_size=(420, 600), text_select=True)
        webview.start(private_mode=False, storage_path=str(app_data() / 'webview'))
    except Exception as exc:  # no usable web view (e.g. WebView2 missing on old Windows): use the browser
        print('Native window unavailable, opening the browser instead:', exc, file=sys.stderr)
        if httpd is None: webbrowser.open(URL); return
        import server
        browser_fallback(httpd, server); return
    if httpd: httpd.shutdown()

if __name__ == '__main__':
    main()
