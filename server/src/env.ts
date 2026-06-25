import 'dotenv/config';

function required(name: string): string {
  const value = process.env[name];
  if (!value || value.trim() === '') {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function optional(name: string, fallback: string): string {
  const value = process.env[name];
  return value && value.trim() !== '' ? value : fallback;
}

export const env = {
  PORT: Number(optional('PORT', '4000')),
  CORS_ORIGINS: optional('CORS_ORIGINS', '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean),
  JWT_SECRET: required('JWT_SECRET'),
  SECRETS_MASTER_KEY: required('SECRETS_MASTER_KEY'),
  SEED_ADMIN_EMAIL: optional('SEED_ADMIN_EMAIL', 'islamov.denis@gmail.com'),
  SEED_ADMIN_PASSWORD: process.env.SEED_ADMIN_PASSWORD ?? '',
  DATA_FILE: optional('DATA_FILE', './data/store.json'),
} as const;

// Fail fast: the master key must decode to exactly 32 bytes for AES-256-GCM.
try {
  const keyLen = Buffer.from(env.SECRETS_MASTER_KEY, 'base64').length;
  if (keyLen !== 32) {
    throw new Error(
      `SECRETS_MASTER_KEY must be exactly 32 bytes (base64). Got ${keyLen} bytes.`,
    );
  }
} catch (err) {
  if (err instanceof Error && err.message.includes('32 bytes')) throw err;
  throw new Error('SECRETS_MASTER_KEY must be valid base64 of exactly 32 bytes.');
}
