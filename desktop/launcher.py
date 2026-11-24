"""LinkDrop desktop app: runs the local server and shows a small control window."""
import os, socket, subprocess, sys, threading, webbrowser
from pathlib import Path

if getattr(sys, 'frozen', False):
    sys.path.insert(0, getattr(sys, '_MEIPASS'))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PORT = 8765  # The web app's "Try on this computer" link points here.
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

def main():
    if already_running():
        webbrowser.open(URL); return
    import server
    httpd = server.serve(PORT)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
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
    if sys.platform == 'darwin':
        try: root.createcommand('::tk::mac::ReopenApplication', lambda: webbrowser.open(URL))
        except Exception: pass
    root.mainloop()

if __name__ == '__main__':
    main()
