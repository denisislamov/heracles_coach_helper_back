import {
  createCipheriv,
  createDecipheriv,
  randomBytes,
  scryptSync,
  timingSafeEqual,
} from 'node:crypto';
import { env } from './env.js';

const ALGO = 'aes-256-gcm';
const SCRYPT_N = 16384;
const SCRYPT_KEYLEN = 64;

function masterKey(): Buffer {
  const key = Buffer.from(env.SECRETS_MASTER_KEY, 'base64');
  if (key.length !== 32) {
    throw new Error('SECRETS_MASTER_KEY must decode to exactly 32 bytes.');
  }
  return key;
}

/** AES-256-GCM. Output: v1:<ivB64>:<tagB64>:<cipherB64> */
export function encryptSecret(plain: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv(ALGO, masterKey(), iv);
  const enc = Buffer.concat([cipher.update(plain, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `v1:${iv.toString('base64')}:${tag.toString('base64')}:${enc.toString('base64')}`;
}

export function decryptSecret(enc: string): string {
  const parts = enc.split(':');
  if (parts.length !== 4 || parts[0] !== 'v1') {
    throw new Error('Invalid secret format.');
  }
  const [, ivB64, tagB64, cipherB64] = parts;
  const iv = Buffer.from(ivB64!, 'base64');
  const tag = Buffer.from(tagB64!, 'base64');
  const data = Buffer.from(cipherB64!, 'base64');
  const decipher = createDecipheriv(ALGO, masterKey(), iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(data), decipher.final()]).toString('utf8');
}

/** scrypt password hash. Output: scrypt:<saltB64>:<hashB64> */
export function hashPassword(pw: string): string {
  const salt = randomBytes(16);
  const hash = scryptSync(pw, salt, SCRYPT_KEYLEN, { N: SCRYPT_N });
  return `scrypt:${salt.toString('base64')}:${hash.toString('base64')}`;
}

export function verifyPassword(pw: string, stored: string): boolean {
  const parts = stored.split(':');
  if (parts.length !== 3 || parts[0] !== 'scrypt') return false;
  const [, saltB64, hashB64] = parts;
  const salt = Buffer.from(saltB64!, 'base64');
  const expected = Buffer.from(hashB64!, 'base64');
  const actual = scryptSync(pw, salt, expected.length, { N: SCRYPT_N });
  if (actual.length !== expected.length) return false;
  return timingSafeEqual(actual, expected);
}

/** URL-safe random password (base64url). */
export function randomPassword(len = 18): string {
  return randomBytes(len).toString('base64url').slice(0, len);
}
