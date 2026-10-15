// Runs browser security logic with Node WebCrypto and a minimal DOM. No server or model needed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const path = require('node:path');
const elements = new Map();
const banners = [];
const context = vm.createContext({
  Uint8Array, TextEncoder, TextDecoder, Number, Date, Object, Array, JSON, console,
  atob, btoa, crypto: crypto.webcrypto,
  $: id => { if (!elements.has(id)) elements.set(id, {}); return elements.get(id); },
  document: {createElement: () => ({}), body: {prepend: el => banners.push(el)}},
  api: async () => ({voice: {chain: ['mock']}}),
  cust: () => ({id: 'cus_test'}),
  appH: () => ({}), staffH: () => ({}),
  location: {origin: 'http://localhost:8000'},
});
const source = fs.readFileSync(path.join(__dirname, '../app/static/security.js'), 'utf8');
vm.runInContext(source + '\nglobalThis.security = Security;', context);

(async () => {
  const keys = crypto.generateKeyPairSync('ec', {namedCurve: 'prime256v1'});
  const jwk = {...keys.publicKey.export({format:'jwk'}), kid:'test-bank', alg:'ES256', use:'sig'};
  const now = Math.floor(Date.now()/1000);
  const sign = payload => {
    const part = x => Buffer.from(JSON.stringify(x)).toString('base64url');
    const body = part({alg:'ES256', kid:jwk.kid}) + '.' + part(payload);
    return body + '.' + crypto.sign('sha256', Buffer.from(body), {key:keys.privateKey, dsaEncoding:'ieee-p1363'}).toString('base64url');
  };
  const valid = sign({iss:'bank', aud:'cus_test', iat:now, exp:now+60});
  assert.equal((await context.security.verifyJwt(valid,jwk,{iss:'bank',aud:'cus_test'})).aud,'cus_test');
  await assert.rejects(context.security.verifyJwt(sign({iat:now}),jwk),/invalid or expired/);
  await assert.rejects(context.security.verifyJwt(sign({iat:now,exp:now-1}),jwk),/invalid or expired/);
  await assert.rejects(context.security.verifyJwt(valid,jwk,{aud:'another-customer'}),/invalid or expired/);
  const body={subject:'Please help with my card',action:'support_ticket.create'};
  const expected=crypto.createHash('sha256').update(JSON.stringify({action:body.action,subject:body.subject})).digest('hex');
  assert.equal(await context.security.hash(body),expected);
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(banners.some(b=>b.textContent.includes('SIMULATED VOICE RESULTS')));
  console.log('Browser security contract: 6 checks passed (real WebCrypto signatures, expiry, audience, canonical hash, mock disclosure).');
})().catch(error=>{console.error(error);process.exitCode=1;});
