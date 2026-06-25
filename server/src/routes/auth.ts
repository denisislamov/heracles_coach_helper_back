import { Router } from 'express';
import { z } from 'zod';
import { signAdminToken } from '../auth.js';
import { verifyPassword } from '../crypto.js';
import { store } from '../store.js';

const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

export const authRouter = Router();

authRouter.post('/login', async (req, res) => {
  const parsed = loginSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: 'invalid_credentials' });
    return;
  }
  const { email, password } = parsed.data;
  const data = await store.read();
  const admin = data.admins.find((a) => a.email === email.toLowerCase());

  // Generic error: never reveal whether email/password/disabled was the cause.
  if (!admin || admin.disabled || !verifyPassword(password, admin.passwordHash)) {
    res.status(401).json({ error: 'invalid_credentials' });
    return;
  }

  const token = signAdminToken({ sub: admin.id, email: admin.email });
  res.json({ token, admin: { id: admin.id, email: admin.email } });
});
