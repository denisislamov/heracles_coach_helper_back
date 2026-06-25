import cors from 'cors';
import express from 'express';
import { env } from './env.js';
import { adminRouter } from './routes/admin.js';
import { authRouter } from './routes/auth.js';
import { coachRouter } from './routes/coach.js';
import { ensureSeedAdmin } from './seed.js';

const app = express();

app.use(
  cors({
    origin: env.CORS_ORIGINS.length > 0 ? env.CORS_ORIGINS : true,
  }),
);
app.use(express.json({ limit: '256kb' }));

app.get('/health', (_req, res) => {
  res.json({ ok: true });
});

app.use('/admin/auth', authRouter);
app.use('/admin', adminRouter);
app.use('/api/coach', coachRouter);

// 404 fallback
app.use((_req, res) => {
  res.status(404).json({ error: 'not_found' });
});

async function main(): Promise<void> {
  await ensureSeedAdmin();
  app.listen(env.PORT, () => {
    console.log(`[server] listening on :${env.PORT}`);
  });
}

main().catch((err) => {
  console.error('[server] failed to start:', err);
  process.exit(1);
});
