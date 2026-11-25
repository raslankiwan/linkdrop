// Uploads for file conversion, kept on LinkDrop's own origin (no cross-origin
// requests, so no CORS). Vercel caps function request bodies at 4.5 MB, so the
// browser sends larger files in parts of at most 4 MB. Each part is stored in
// private Blob storage; the converter then reads the parts through short-lived
// presigned URLs and joins them.
const { put, issueSignedToken, presignUrl, del } = require('@vercel/blob');

const PART_BYTES = 4 * 1000 * 1000;
const MAX_PARTS = 50; // 200 MB
const ID = /^[a-f0-9]{32}$/;
const partPath = (id, n) => `uploads/${id}/part-${String(n).padStart(4, '0')}`;

async function readBody(req, limit) {
  if (Buffer.isBuffer(req.body)) return req.body;
  if (typeof req.body === 'string') return Buffer.from(req.body);
  if (req.body && typeof req.body === 'object') return Buffer.from(JSON.stringify(req.body));
  const chunks = []; let size = 0;
  for await (const chunk of req) { size += chunk.length; if (size > limit) throw Error('Upload part too large.'); chunks.push(chunk); }
  return Buffer.concat(chunks);
}

function sameOrigin(req) {
  const origin = req.headers.origin;
  if (!origin) return true;
  try { return new URL(origin).host === req.headers.host; } catch { return false; }
}

function send(res, status, body) {
  res.statusCode = status; res.setHeader('Content-Type', 'application/json'); res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify(body));
}

function checkRef(id, parts) {
  if (typeof id !== 'string' || !ID.test(id)) throw Error('Invalid upload reference.');
  if (!Number.isInteger(parts) || parts < 1 || parts > MAX_PARTS) throw Error('Invalid upload size.');
}

module.exports = async function handler(req, res) {
  try {
    if (req.method !== 'POST') return send(res, 405, { error: 'Method not allowed.' });
    if (!sameOrigin(req)) return send(res, 403, { error: 'Cross-site requests are not allowed.' });
    const query = new URL(req.url, 'https://linkdrop.invalid').searchParams;
    if ((req.headers['content-type'] || '').startsWith('application/octet-stream')) {
      const id = query.get('id'); const part = Number(query.get('part'));
      checkRef(id, part + 1);
      const body = await readBody(req, PART_BYTES);
      if (!body.length || body.length > PART_BYTES) throw Error('Upload part too large.');
      await put(partPath(id, part), body, { access: 'private', addRandomSuffix: false, allowOverwrite: true, contentType: 'application/octet-stream' });
      return send(res, 200, { ok: true, part, bytes: body.length });
    }
    const data = JSON.parse((await readBody(req, 65536)).toString() || '{}');
    checkRef(data.id, data.parts);
    const pathnames = Array.from({ length: data.parts }, (_, n) => partPath(data.id, n));
    if (data.action === 'delete') { try { await del(pathnames); } catch {} return send(res, 200, { deleted: true }); }
    if (data.action !== 'source') throw Error('Unknown action.');
    const validUntil = Date.now() + 15 * 60 * 1000;
    const urls = [];
    for (const pathname of pathnames) {
      const signed = await issueSignedToken({ pathname, operations: ['get'], validUntil });
      urls.push((await presignUrl(signed, { operation: 'get', pathname, access: 'private', validUntil })).presignedUrl);
    }
    return send(res, 200, { urls });
  } catch (e) {
    return send(res, 400, { error: (e && e.message) || 'Upload failed.' });
  }
};
module.exports.PART_BYTES = PART_BYTES;
