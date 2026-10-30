const { createHmac, timingSafeEqual } = require('node:crypto');
const { presignUrl, issueSignedToken, copy } = require('@vercel/blob');
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
    if (typeof data.pathname!=='string') throw Error('Invalid file.');
    const match=/^downloads\/([a-f0-9]{32})\/[^/]+$/.exec(data.pathname);
    if (!match) throw Error('Invalid file.');
    let pathname=data.pathname;
    if (/[^\x20-\x7e]/.test(pathname)) {
      // Older tickets contain display filenames. Copy within the same job to an
      // ASCII key before signing; keep the original blob and its ticket valid.
      const extension=/\.([a-z0-9]{1,10})$/i.exec(pathname)?.[1].toLowerCase() || 'bin';
      const destination=`downloads/${match[1]}/media.${extension}`;
      const migrated=await copy(pathname,destination,{access:'private',allowOverwrite:true,addRandomSuffix:false});
      if(migrated.pathname!==destination) throw Error('Could not prepare the download. Please retry.');
      pathname=destination;
    }
    const validUntil=Math.min(data.expires*1000,Date.now()+15*60*1000);
    const signed=await issueSignedToken({pathname,operations:['get'],validUntil});
    const result=await presignUrl(signed,{operation:'get',pathname,access:'private',validUntil});
    res.statusCode=302;res.setHeader('Location',result.presignedUrl);res.end();
  } catch(e) {res.statusCode=400;res.setHeader('Content-Type','text/plain');res.end(e.message || 'File unavailable.');}
};
