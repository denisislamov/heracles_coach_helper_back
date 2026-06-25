import { randomUUID } from 'node:crypto';
import { hashPassword, randomPassword } from './crypto.js';
import { env } from './env.js';
import { store } from './store.js';

export async function ensureSeedAdmin(): Promise<void> {
  const data = await store.read();
  if (data.admins.length > 0) return;

  const email = env.SEED_ADMIN_EMAIL;
  const password = env.SEED_ADMIN_PASSWORD || randomPassword(18);
  const generated = !env.SEED_ADMIN_PASSWORD;

  await store.update((d) => {
    d.admins.push({
      id: randomUUID(),
      email: email.toLowerCase(),
      passwordHash: hashPassword(password),
      createdAt: new Date().toISOString(),
      disabled: false,
    });
  });

  if (generated) {
    // Printed exactly once. There is no email recovery in v1.
    console.log(
      `\n[seed] Created admin "${email}". Generated password (shown once): ${password}\n`,
    );
  } else {
    console.log(`[seed] Created admin "${email}" with SEED_ADMIN_PASSWORD.`);
  }
}

// Allow running directly: `npm run seed`
if (import.meta.url === `file://${process.argv[1]}`) {
  ensureSeedAdmin()
    .then(() => process.exit(0))
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
