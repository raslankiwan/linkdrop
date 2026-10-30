const fs=require('node:fs');
const zlib=require('node:zlib');
const binary=require.resolve('node/bin/node');
fs.writeFileSync('lib/runtime-node.gz',zlib.gzipSync(fs.readFileSync(binary),{level:9}));
if(fs.existsSync('lib/runtime-node'))fs.unlinkSync('lib/runtime-node');
console.log('Prepared static frontend and compressed JavaScript runtime.');
