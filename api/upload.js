// Uploads for file conversion. Files go straight from the browser to private
// Blob storage (Vercel caps function bodies at 4.5 MB), then the converter reads
// them through a short-lived presigned URL scoped to that one upload.
const { handleUpload } = require('@vercel/blob/client');
const { issueSignedToken, presignUrl, del } = require('@vercel/blob');

const MAX_BYTES = 200 * 1024 * 1024;
const UPLOAD_PATH = /^uploads\/[a-f0-9]{32}\/[A-Za-z0-9._-]{1,140}$/;

async function readJson(req) {
  if (req.body && typeof req.body === 'object' && !Buffer.isBuffer(req.body)) return req.body;
  if (typeof req.body === 'string') return JSON.parse(req.body);
  const chunks = []; let size = 0;
  for await (const chunk of req) { size += chunk.length; if (size > 65536) throw Error('Request too large.'); chunks.push(chunk); }
  return JSON.parse(Buffer.concat(chunks).toString() || '{}');
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

module.exports = async function handler(req, res) {
  try {
    if (req.method !== 'POST') return send(res, 405, { error: 'Method not allowed.' });
    const body = await readJson(req);
    // Blob's own upload-completed webhook carries no Origin header and is verified by handleUpload.
    if (body.type !== 'blob.upload-completed' && !sameOrigin(req)) return send(res, 403, { error: 'Cross-site requests are not allowed.' });
    if (body.action === 'source' || body.action === 'delete') {
      if (typeof body.pathname !== 'string' || !UPLOAD_PATH.test(body.pathname)) throw Error('Invalid upload reference.');
      if (body.action === 'delete') { try { await del(body.pathname); } catch {} return send(res, 200, { deleted: true }); }
      const validUntil = Date.now() + 15 * 60 * 1000;
      const signed = await issueSignedToken({ pathname: body.pathname, operations: ['get'], validUntil });
      const result = await presignUrl(signed, { operation: 'get', pathname: body.pathname, access: 'private', validUntil });
      return send(res, 200, { url: result.presignedUrl });
    }
    const result = await handleUpload({
      body, request: req,
      onBeforeGenerateToken: async pathname => {
        if (!UPLOAD_PATH.test(pathname)) throw Error('Invalid upload name.');
        return { maximumSizeInBytes: MAX_BYTES, addRandomSuffix: false, allowOverwrite: false, validUntil: Date.now() + 30 * 60 * 1000 };
      },
      onUploadCompleted: async () => {}
    });
    return send(res, 200, result);
  } catch (e) {
    return send(res, 400, { error: (e && e.message) || 'Upload failed.' });
  }
};
module.exports.UPLOAD_PATH = UPLOAD_PATH;
