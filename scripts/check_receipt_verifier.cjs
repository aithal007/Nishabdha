const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const path = require('node:path');
const ctx = vm.createContext({ crypto: crypto.webcrypto, atob, Uint8Array, TextEncoder, TextDecoder, URL, Date, JSON });
vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/receipt-verifier.js'), 'utf8'), ctx);
const key = crypto.generateKeyPairSync('ec', {namedCurve:'prime256v1'});
const jwk = {...key.publicKey.export({format:'jwk'}), kid:'bank-test', alg:'ES256'};
const trust = {issuer:'https://bank.example', keys:[jwk]};
const payload = {schema:'nishabdha.decision.v1', decision_id:'decision_test', iss:trust.issuer, recorded_at:new Date().toISOString(), outcome:'denied', operation:'transfer_funds', mode:'simulated', reason_codes:['approval_required']};
function sign(p, header={alg:'ES256',kid:jwk.kid}) {
  const part = x => Buffer.from(JSON.stringify(x)).toString('base64url');
  const data = part(header)+'.'+part(p);
  return data+'.'+crypto.sign('sha256',Buffer.from(data),{key:key.privateKey,dsaEncoding:'ieee-p1363'}).toString('base64url');
}
(async()=> {
  const record = {payload, signature:sign(payload)};
  assert.equal((await ctx.NishabdhaReceipt.verify(record,trust,trust.issuer)).outcome,'denied');
  await assert.rejects(ctx.NishabdhaReceipt.verify({...record,payload:{...payload,outcome:'executed'}},trust,trust.issuer));
  await assert.rejects(ctx.NishabdhaReceipt.verify(record,trust,'https://other-bank.example'));
  const wrong = crypto.generateKeyPairSync('ec',{namedCurve:'prime256v1'}).publicKey.export({format:'jwk'});
  await assert.rejects(ctx.NishabdhaReceipt.verify(record,{...trust,keys:[{...wrong,kid:jwk.kid}]},trust.issuer));
  await assert.rejects(ctx.NishabdhaReceipt.verify({payload,signature:sign(payload,{alg:'HS256',kid:jwk.kid})},trust,trust.issuer));
  await assert.rejects(ctx.NishabdhaReceipt.verify({payload,signature:sign(payload,{alg:'ES256',kid:jwk.kid,jwk})},trust,trust.issuer));
  const tomorrow={...payload,recorded_at:new Date(Date.now()+86400000).toISOString()};
  await assert.rejects(ctx.NishabdhaReceipt.verify({payload:tomorrow,signature:sign(tomorrow)},trust,trust.issuer));
  const historical={...payload,recorded_at:'2024-01-01T00:00:00Z'};
  assert.equal((await ctx.NishabdhaReceipt.verify({payload:historical,signature:sign(historical)},trust,trust.issuer)).outcome,'denied');
  console.log('Receipt verifier: 8 checks passed with real P-256 signatures.');
})().catch(error=>{console.error(error);process.exitCode=1;});
