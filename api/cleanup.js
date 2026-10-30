const {list,del}=require('@vercel/blob');
module.exports=async function handler(req,res){
  res.setHeader('Cache-Control','no-store');
  if(!process.env.CRON_SECRET || req.headers.authorization!==`Bearer ${process.env.CRON_SECRET}`){res.statusCode=401;return res.end('Unauthorized')}
  try{
    let cursor;let deleted=0;const cutoff=Date.now()-24*60*60*1000;
    do{
      const page=await list({prefix:'downloads/',limit:1000,cursor});
      const old=page.blobs.filter(b=>new Date(b.uploadedAt).getTime()<cutoff).map(b=>b.url);
      if(old.length){await del(old);deleted+=old.length}
      cursor=page.hasMore?page.cursor:undefined;
    }while(cursor);
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify({deleted}));
  }catch{res.statusCode=500;res.end('Cleanup failed')}
};
