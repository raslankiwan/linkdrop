// Keep file delivery separate from the app page so a download cannot navigate it away.
(function(root){
  const requested=new Set();
  root.LinkDropAutoSave={
    has:id=>requested.has(id),
    request(id,url){
      if(requested.has(id)||typeof url!=='string'||!(url.startsWith('/api/file?ticket=')||/^\/file\/[a-f0-9]{32}$/.test(url)))return false;
      const frame=document.createElement('iframe');
      frame.hidden=true;frame.title='Download file';frame.src=url;
      document.body.appendChild(frame);
      requested.add(id);
      return true;
    }
  };
})(globalThis);
