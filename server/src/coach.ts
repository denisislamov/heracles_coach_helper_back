import { z } from 'zod';
import { decryptSecret } from './crypto.js';
import { callClaude, callOpenAI } from './llm.js';
import { store } from './store.js';

export const evidenceItemSchema = z.object({
  id: z.string(),
  title: z.string().optional(),
  summary: z.string().optional(),
  url: z.string().optional(),
});

export const coachRequestSchema = z.object({
  message: z.string().min(1).max(4000),
  context: z
    .object({
      metrics: z.record(z.unknown()).optional(),
      questionClass: z.string().optional(),
      evidence: z.array(evidenceItemSchema).max(50).optional(),
    })
    .default({}),
});

export type CoachRequest = z.infer<typeof coachRequestSchema>;
export type EvidenceItem = z.infer<typeof evidenceItemSchema>;

export interface CoachReply {
  text: string;
  citationIds: string[];
}

export class CoachUnavailableError extends Error {
  constructor(message = 'coach_unavailable') {
    super(message);
    this.name = 'CoachUnavailableError';
  }
}

export function renderTemplate(
  tpl: string,
  vars: Record<string, string>,
): string {
  return tpl.replace(/\{\{(\w+)\}\}/g, (_m, key: string) =>
    Object.prototype.hasOwnProperty.call(vars, key) ? vars[key]! : '',
  );
}

export function formatEvidence(items: EvidenceItem[]): string {
  if (!items.length) return '(none)';
  return items
    .map((e) => {
      const title = e.title ?? '';
      const summary = e.summary ? ` — ${e.summary}` : '';
      const url = e.url ? ` (${e.url})` : '';
      return `[${e.id}] ${title}${summary}${url}`.trim();
    })
    .join('\n');
}

/** Tolerant extraction of the first balanced JSON object from a text blob. */
function extractJson(raw: string): string | null {
  const start = raw.indexOf('{');
  if (start === -1) return null;
  let depth = 0;
  let inStr = false;
  let escape = false;
  for (let i = start; i < raw.length; i++) {
    const ch = raw[i]!;
    if (escape) {
      escape = false;
      continue;
    }
    if (ch === '\\') {
      escape = true;
      continue;
    }
    if (ch === '"') inStr = !inStr;
    if (inStr) continue;
    if (ch === '{') depth++;
    else if (ch === '}') {
      depth--;
      if (depth === 0) return raw.slice(start, i + 1);
    }
  }
  return null;
}

export function parseReply(raw: string, allowedIds: string[]): CoachReply {
  const jsonStr = extractJson(raw) ?? raw;
  let parsed: unknown;
  try {
    parsed = JSON.parse(jsonStr);
  } catch {
    throw new Error('Failed to parse coach reply JSON.');
  }
  const obj = parsed as { text?: unknown; citationIds?: unknown };
  if (typeof obj.text !== 'string' || obj.text.trim() === '') {
    throw new Error('Coach reply missing "text".');
  }
  const allowed = new Set(allowedIds);
  const citationIds = Array.isArray(obj.citationIds)
    ? obj.citationIds.filter(
        (id): id is string => typeof id === 'string' && allowed.has(id),
      )
    : [];
  return { text: obj.text, citationIds };
}

export async function runCoach(
  req: CoachRequest,
  signal?: AbortSignal,
): Promise<CoachReply> {
  const { config } = await store.read();
  const provider = config.ai.provider;

  if (provider === 'none') throw new CoachUnavailableError();

  const providerConfig =
    provider === 'openai' ? config.ai.openai : config.ai.claude;
  if (!providerConfig.apiKeyEnc) throw new CoachUnavailableError();

  const apiKey = decryptSecret(providerConfig.apiKeyEnc);

  const evidence = req.context.evidence ?? [];
  const allowedIds = evidence.map((e) => e.id);

  const system = config.prompts.system;
  const user = renderTemplate(config.prompts.userTemplate, {
    metrics: req.context.metrics
      ? JSON.stringify(req.context.metrics, null, 2)
      : '(none)',
    evidence: formatEvidence(evidence),
    question: req.message,
  });

  const raw =
    provider === 'openai'
      ? await callOpenAI({ apiKey, model: providerConfig.model, system, user, signal })
      : await callClaude({ apiKey, model: providerConfig.model, system, user, signal });

  return parseReply(raw, allowedIds);
}
