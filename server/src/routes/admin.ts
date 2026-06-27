import { randomUUID } from 'node:crypto';
import { Router } from 'express';
import { z } from 'zod';
import { requireAdmin } from '../auth.js';
import { encryptSecret, hashPassword, randomPassword } from '../crypto.js';
import { store } from '../store.js';
import { toAdminUserView, toAdminView } from '../views.js';

export const adminRouter = Router();
adminRouter.use(requireAdmin);

// ---- Config ----

const providerPatchSchema = z.object({
  model: z.string().min(1).optional(),
  apiKey: z.string().min(1).nullable().optional(),
});

const configPatchSchema = z.object({
  ai: z
    .object({
      provider: z.enum(['none', 'openai', 'claude']).optional(),
      openai: providerPatchSchema.optional(),
      claude: providerPatchSchema.optional(),
    })
    .optional(),
  prompts: z
    .object({
      system: z.string().optional(),
      userTemplate: z.string().optional(),
    })
    .optional(),
});

adminRouter.get('/config', async (_req, res) => {
  const { config } = await store.read();
  res.json(toAdminView(config));
});

adminRouter.put('/config', async (req, res) => {
  const parsed = configPatchSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: 'invalid_body', details: parsed.error.flatten() });
    return;
  }
  const patch = parsed.data;

  const data = await store.update((d) => {
    const c = d.config;
    if (patch.ai?.provider) c.ai.provider = patch.ai.provider;

    for (const key of ['openai', 'claude'] as const) {
      const p = patch.ai?.[key];
      if (!p) continue; // omit -> leave untouched
      if (p.model !== undefined) c.ai[key].model = p.model;
      if (p.apiKey !== undefined) {
        // string -> encrypt & store; null -> clear
        c.ai[key].apiKeyEnc = p.apiKey === null ? null : encryptSecret(p.apiKey);
      }
    }

    if (patch.prompts?.system !== undefined) c.prompts.system = patch.prompts.system;
    if (patch.prompts?.userTemplate !== undefined)
      c.prompts.userTemplate = patch.prompts.userTemplate;

    c.updatedAt = new Date().toISOString();
    c.updatedBy = req.admin?.email ?? null;
  });

  res.json(toAdminView(data.config));
});

// ---- Admins ----

const createAdminSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
});

const resetSchema = z.object({
  password: z.string().min(8).optional(),
});

const disableSchema = z.object({
  disabled: z.boolean(),
});

adminRouter.get('/admins', async (_req, res) => {
  const data = await store.read();
  res.json(data.admins.map(toAdminUserView));
});

adminRouter.post('/admins', async (req, res) => {
  const parsed = createAdminSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: 'invalid_body' });
    return;
  }
  const email = parsed.data.email.toLowerCase();
  const existing = await store.read();
  if (existing.admins.some((a) => a.email === email)) {
    res.status(409).json({ error: 'email_exists' });
    return;
  }
  let created = toAdminUserView({
    id: '',
    email,
    passwordHash: '',
    createdAt: '',
    disabled: false,
  });
  await store.update((d) => {
    const user = {
      id: randomUUID(),
      email,
      passwordHash: hashPassword(parsed.data.password),
      createdAt: new Date().toISOString(),
      disabled: false,
    };
    d.admins.push(user);
    created = toAdminUserView(user);
  });
  res.status(201).json(created);
});

adminRouter.post('/admins/:id/reset-password', async (req, res) => {
  const parsed = resetSchema.safeParse(req.body ?? {});
  if (!parsed.success) {
    res.status(400).json({ error: 'invalid_body' });
    return;
  }
  const generated = !parsed.data.password;
  const password = parsed.data.password ?? randomPassword(18);

  let found = false;
  await store.update((d) => {
    const admin = d.admins.find((a) => a.id === req.params.id);
    if (!admin) return;
    found = true;
    admin.passwordHash = hashPassword(password);
  });

  if (!found) {
    res.status(404).json({ error: 'not_found' });
    return;
  }
  // Generated password is returned exactly once.
  res.json(generated ? { ok: true, password } : { ok: true });
});

// ---- Coach prompt catalogue ----

const ALLOWED_INTENTS = [
  'levels',
  'general',
  'test',
  'train',
  'recovery',
  'workout',
  'eat',
  'sleep',
] as const;

const evidenceQuerySchema = z.object({
  domains: z.array(z.string()),
  tags: z.array(z.string()),
  limit: z.number().int().min(0).max(10),
});

const promptEntrySchema = z.object({
  id: z.string().min(1),
  intent: z.enum(ALLOWED_INTENTS),
  title: z.string().min(1),
  keywords: z.array(z.string()),
  evidence: evidenceQuerySchema,
  task: z.string().min(1),
});

const catalogSchema = z
  .object({
    version: z.string(),
    updatedAt: z.string().optional(),
    description: z.string().optional(),
    placeholders: z.record(z.string()),
    outputContract: z.unknown(),
    systemPrompt: z.object({
      openai: z.string().min(1),
      claude: z.string().min(1),
    }),
    contextBlockTemplate: z.string().min(1),
    responseExamples: z.array(z.unknown()).optional(),
    offTopic: z.object({
      id: z.string().min(1),
      intent: z.string().min(1),
      title: z.string().min(1),
      description: z.string().optional(),
      task: z.string().min(1),
    }),
    routing: z.object({
      strategy: z.string(),
      defaultEvidenceLimit: z.number().int().min(0).max(10),
    }),
    prompts: z.array(promptEntrySchema),
  })
  .superRefine((cat, ctx) => {
    // unique prompt ids
    const ids = cat.prompts.map((p) => p.id);
    const dupes = ids.filter((id, i) => ids.indexOf(id) !== i);
    if (dupes.length) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `duplicate prompt ids: ${[...new Set(dupes)].join(', ')}`,
        path: ['prompts'],
      });
    }
    // context template must contain every declared placeholder
    for (const key of Object.keys(cat.placeholders)) {
      if (!cat.contextBlockTemplate.includes(`{{${key}}}`)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `contextBlockTemplate is missing placeholder {{${key}}}`,
          path: ['contextBlockTemplate'],
        });
      }
    }
  });

adminRouter.get('/coach/catalog', async (_req, res) => {
  const { config } = await store.read();
  res.json(config.promptCatalog);
});

adminRouter.put('/coach/catalog', async (req, res) => {
  const parsed = catalogSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: 'invalid_catalog', details: parsed.error.flatten() });
    return;
  }
  const data = await store.update((d) => {
    d.config.promptCatalog = {
      ...parsed.data,
      updatedAt: new Date().toISOString(),
    };
    d.config.updatedAt = new Date().toISOString();
    d.config.updatedBy = req.admin?.email ?? null;
  });
  res.json(data.config.promptCatalog);
});

adminRouter.post('/admins/:id/disable', async (req, res) => {
  const parsed = disableSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: 'invalid_body' });
    return;
  }
  const data = await store.read();
  const target = data.admins.find((a) => a.id === req.params.id);
  if (!target) {
    res.status(404).json({ error: 'not_found' });
    return;
  }

  // Never disable the last active admin.
  if (parsed.data.disabled) {
    const activeCount = data.admins.filter((a) => !a.disabled).length;
    if (activeCount <= 1 && !target.disabled) {
      res.status(409).json({ error: 'cannot_disable_last_admin' });
      return;
    }
  }

  const updated = await store.update((d) => {
    const admin = d.admins.find((a) => a.id === req.params.id);
    if (admin) admin.disabled = parsed.data.disabled;
  });
  const view = updated.admins.find((a) => a.id === req.params.id);
  res.json(view ? toAdminUserView(view) : { ok: true });
});
