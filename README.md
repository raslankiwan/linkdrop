# LinkDrop

Video and audio downloader with a Mac-local app and a responsive Vercel web app.

## Hosted web app

- Paste a public video URL, inspect source resolutions, select format and quality.
- MP4, MKV, WebM, MOV, MP3, M4A, WAV, FLAC, Opus, or original.
- Two concurrent downloads per browser and up to ten active/queued entries.
- Streaming progress; keep the page open until processing finishes.
- History is stored only in that browser. **Clear history** removes completed and failed entries, preserving active jobs and downloaded files.
- Files are uploaded into private Vercel Blob storage; HMAC-signed application tickets expire in 24 hours. Each save action issues a 15-minute URL scoped to that file.
- Daily cleanup removes cloud files older than 24 hours (actual retention up to 48 hours).
- **Hosted limits: 200 MB per file, roughly four minutes for download/conversion**, bounded by Vercel Hobby function limits. Very long downloads/conversions require the local app.
- Some platforms block datacenter IP addresses, require sign-in, or change their extractors. No guaranteed support for every URL, DRM bypass, authenticated posts, or playlists.
- Downloads consume Vercel compute, storage, and transfer quotas. The public app has per-job limits, but no account-based quota. Monitor usage before broad distribution.

## Local Mac app

Double-click `Start.command`, then open http://127.0.0.1:8765. Leave Terminal open.
The local backend binds only to loopback and stores files in `downloads/`.
Local history resets on restart; downloaded files remain on disk.
The local clear-history action hides finished/failed jobs without deleting files.
Python 3.12+ is recommended. First-run dependencies are installed into a local virtual environment.
Node.js is recommended for YouTube JavaScript challenges.

## Deploy

1. Install Python 3.12+, Node.js 22+ and Vercel CLI. Run `npm ci`.
2. `vercel link` and create a **private** Blob store connected to production and preview.
3. Configure `BLOB_READ_WRITE_TOKEN`, `LINKDROP_SECRET`, and `CRON_SECRET` in Vercel environment variables. Secrets must stay server-side.
4. `vercel --prod`, then `vercel git connect` to enable GitHub deployments.

Frontend: `public/`. Python function: `api/cloud.py`. Bounded yt-dlp subprocess: `lib/engine.py`.
Private download signing: `api/file.js`. Daily retention cleanup: `api/cleanup.js`.
No job state is held in server memory across requests; each job keeps its function request open.
Actual network connections in the download worker reject private/loopback destinations, including redirects.

Run `npm test` for browser-history and file-ticket tests.
Only download media you own or have permission to save. Converting lossy audio to FLAC/WAV cannot recover lost detail.
