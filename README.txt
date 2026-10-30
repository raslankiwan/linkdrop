LinkDrop — local video and audio downloader

Double-click Start.command in Finder. Leave its Terminal window open while using the app.
Open http://127.0.0.1:8765 if the browser opens before the server is ready.
Requires macOS with Python 3.10 or later for current yt-dlp releases. This copy includes an installed Python 3.12 environment. The first run installs yt-dlp and bundled FFmpeg into .venv.
Node.js is recommended for YouTube JavaScript challenges. The current Mac has Node installed.

Paste a URL, optionally click Find video to inspect source resolutions, select format and quality,
and click Download. Once complete, Save file copies the result through your browser.
Original files are in the downloads folder alongside server.py. You can remove them in Finder.
Two downloads run concurrently; up to ten unfinished jobs can be queued.
The job list is kept in memory and resets when the app restarts; downloaded files remain on disk.
Close the Terminal or press Control-C to stop the app.

Formats: original, MP4, MKV, WebM, MOV, MP3, M4A, WAV, FLAC, Opus.
Video quality choices are ceilings, not promises. Audio conversion uses 192 kbps where applicable.
Converting lossy audio to WAV or FLAC does not restore lost fidelity. Conversion may be slow.
Platform support is provided by yt-dlp and varies by URL, region, sign-in requirements, and platform changes.
Private/authenticated posts are not configured in this version. No DRM bypass. Individual videos only; no playlists.
Only download media you own or are permitted to save.

Keep the engine updated from Terminal in this folder:
.venv-modern/bin/pip install --upgrade 'yt-dlp[default]' imageio-ffmpeg

The app binds to localhost only and is intended for personal use on this Mac.
It does not provide an iOS app or public hosting. It contacts source platforms to retrieve media.
Conversion requires a local process and therefore cannot run on Sites' Cloudflare Worker hosting.
Implementation: standard-library Python HTTP server, yt-dlp, imageio-ffmpeg, plain HTML/CSS/JS.
