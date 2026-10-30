const fs=require('node:fs');
const binary=require.resolve('node/bin/node');
fs.copyFileSync(binary,'lib/runtime-node');
fs.chmodSync('lib/runtime-node',0o755);
console.log('Prepared static frontend and standalone JavaScript runtime.');
