// Host-only Ed25519 identity for one instance's frontend adapter. Never emits a private key.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const directory = process.argv[2];
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
const parent = fs.lstatSync(directory);
if (!parent.isDirectory() || parent.isSymbolicLink() || parent.uid !== process.getuid() || (parent.mode & 0o777) !== 0o700) throw new Error('Unsafe identity directory');
const keyPath = path.join(directory, 'identity.pem');
if (!fs.existsSync(keyPath)) {
  const { privateKey } = crypto.generateKeyPairSync('ed25519');
  const temporary = path.join(directory, crypto.randomUUID() + '.tmp');
  fs.writeFileSync(temporary, privateKey.export({ type: 'pkcs8', format: 'pem' }), { flag: 'wx', mode: 0o600 });
  try { fs.linkSync(temporary, keyPath); } catch (error) { if (error.code !== 'EEXIST') throw error; }
  finally { fs.unlinkSync(temporary); }
}
const info = fs.lstatSync(keyPath);
if (!info.isFile() || info.isSymbolicLink() || info.uid !== process.getuid() || (info.mode & 0o777) !== 0o600) throw new Error('Unsafe identity file');
const privateKey = crypto.createPrivateKey(fs.readFileSync(keyPath));
const publicKey = crypto.createPublicKey(privateKey).export({ format: 'jwk' }).x;
const id = crypto.createHash('sha256').update(Buffer.from(publicKey, 'base64url')).digest('hex');
const signedAt = Date.now();
const payload = ['v3', id, 'openclaw-control-ui', 'ui', 'operator', input.scopes.join(','), String(signedAt), '', input.nonce, 'server', ''].join('|');
const signature = crypto.sign(null, Buffer.from(payload), privateKey).toString('base64url');
process.stdout.write(JSON.stringify({ id, publicKey, signature, signedAt, nonce: input.nonce }));
