import { Router } from 'express';
import {
  CoachUnavailableError,
  coachRequestSchema,
  runCoach,
} from '../coach.js';
import { store } from '../store.js';
import { toPublicView } from '../views.js';

export const coachRouter = Router();

// Public: no keys, only { provider }.
coachRouter.get('/config', async (_req, res) => {
  const { config } = await store.read();
  res.json(toPublicView(config));
});

// TODO before prod: protect with app user auth + rate-limit.
coachRouter.post('/messages', async (req, res) => {
  const parsed = coachRequestSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: 'invalid_body', details: parsed.error.flatten() });
    return;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);

  try {
    const reply = await runCoach(parsed.data, controller.signal);
    res.json(reply);
  } catch (err) {
    if (err instanceof CoachUnavailableError) {
      res.status(409).json({ error: 'coach_unavailable' });
      return;
    }
    console.error('[coach] failed:', err);
    res.status(502).json({ error: 'coach_failed' });
  } finally {
    clearTimeout(timeout);
  }
});
