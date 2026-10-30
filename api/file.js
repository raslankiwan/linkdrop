const { createHmac, timingSafeEqual } = require('node:crypto');
const { presignUrl, issueSignedToken } = require('@vercel/blob');
module.exports = async function handler(req,res) {
  res.setHeader('Cache-Control','no-store');
  try {
    const ticket = new URL(req.url,'https://linkdrop.invalid').searchParams.get('ticket') || '';
    const [payload,signature] = ticket.split('.');
    if (!payload || !/^[a-f0-9]{64}$/.test(signature || '') || !process.env.LINKDROP_SECRET) throw Error('Invalid download link.');
    const expected=createHmac('sha256',process.env.LINKDROP_SECRET).update(payload).digest();
    if (!timingSafeEqual(expected,Buffer.from(signature,'hex'))) throw Error('Invalid download link.');
    const data=JSON.parse(Buffer.from(payload,'base64url').toString());
    if (!Number.isFinite(data.expires) || data.expires<Date.now()/1000) throw Error('This download link has expired. Download the video again.');
    if (typeof data.pathname!=='string' || !/^downloads\/[a-f0-9]{32}\//.test(data.pathname)) throw Error('Invalid file.');
    const validUntil=Math.min(data.expires*1000,Date.now()+15*60*1000);
    const signed=await issueSignedToken({pathname:data.pathname,operations:['get'],validUntil});
    const result=await presignUrl(signed,{operation:'get',pathname:data.pathname,access:'private',validUntil});
    res.statusCode=302;res.setHeader('Location',result.presignedUrl);res.end();
  } catch(e) {res.statusCode=400;res.setHeader('Content-Type','text/plain');res.end(e.message || 'File unavailable.');}
};
