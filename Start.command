#!/bin/zsh
cd "${0:A:h}"
if [[ -x .venv-modern/bin/python ]]; then
  VENV=.venv-modern
else
  VENV=.venv
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV" || exit 1
fi
if ! "$VENV/bin/python" -c 'import yt_dlp, imageio_ffmpeg' 2>/dev/null; then
  "$VENV/bin/pip" install -r requirements.txt || exit 1
fi
open http://127.0.0.1:8765
"$VENV/bin/python" server.py
