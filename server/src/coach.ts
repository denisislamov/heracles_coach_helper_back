import { z } from 'zod';
import { decryptSecret } from './crypto.js';
import { callClaude, callOpenAI } from './llm.js';
import { store } from './store.js';
import type {
  AiProvider,
  CoachPromptCatalog,
  CoachPromptEntry,
} from './types.js';

export const evidenceItemSchema = z.object({
  id: z.string(),
  title: z.string().optional(),
  summary: z.string().optional(),
  url: z.string().optional(),
});

export const chatTurnSchema = z.object({
  role: z.enum(['user', 'assistant']),
  content: z.string(),
});

// Max characters kept per history turn (matches the client-side cap).
const HISTORY_CONTENT_MAX = 2000;
// Max number of prior turns fed into the prompt.
const HISTORY_TURNS_MAX = 12;

/**
 * Sanitize raw client history into clean, capped turns. Never throws: garbage
 * items are dropped, oversized content is truncated (not rejected), and the
 * array is capped to the most recent turns. This runs as a zod preprocess so an
 * oversized/malformed `history` degrades gracefully instead of 400-ing the
 * whole request.
 */
function sanitizeHistory(raw: unknown): { role: 'user' | 'assistant'; content: string }[] {
  if (!Array.isArray(raw)) return [];
  const out: { role: 'user' | 'assistant'; content: string }[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const rec = item as Record<string, unknown>;
    const role = rec.role === 'assistant' ? 'assistant' : rec.role === 'user' ? 'user' : null;
    if (!role) continue;
    if (typeof rec.content !== 'string') continue;
    const content = rec.content.trim().slice(0, HISTORY_CONTENT_MAX);
    if (content.length === 0) continue;
    out.push({ role, content });
  }
  return out.slice(-HISTORY_TURNS_MAX);
}

export const coachRequestSchema = z.object({
  message: z.string().min(1).max(4000),
  // Never trust the client: preprocess drops empty/garbage turns, truncates
  // oversized content, and keeps only the most recent turns so a malformed or
  // oversized client can't blow up the prompt or error the request.
  history: z.preprocess(sanitizeHistory, z.array(chatTurnSchema)).default([]),
  context: z
    .object({
      // routing hints from the app (optional)
      promptId: z.string().optional(),
      questionClass: z.string().optional(),
      // extended patient parameters (all optional)
      profile: z.record(z.unknown()).optional(),
      biomarkers: z.array(z.record(z.unknown())).optional(),
      bioAge: z.record(z.unknown()).optional(),
      healthScore: z.record(z.unknown()).optional(),
      wearable: z.record(z.unknown()).optional(),
      treatment: z.record(z.unknown()).optional(),
      // legacy WHOOP metrics, still supported
      metrics: z.record(z.unknown()).optional(),
      evidence: z.array(evidenceItemSchema).max(50).optional(),
    })
    .default({}),
});

export type CoachRequest = z.infer<typeof coachRequestSchema>;
export type EvidenceItem = z.infer<typeof evidenceItemSchema>;
export type ChatTurn = z.infer<typeof chatTurnSchema>;

/**
 * Anthropic requires the messages array to start with a `user` turn and to
 * alternate roles. Stored history should already satisfy this, but guard
 * against a malformed client: drop a leading `assistant` turn, collapse any
 * accidental consecutive same-role turns (keeping the latest of each run), and
 * drop a trailing `user` turn — the current question is appended as the final
 * `user` turn, so history must end on `assistant` to preserve alternation.
 */
export function normalizeClaudeHistory(history: ChatTurn[]): ChatTurn[] {
  const out: ChatTurn[] = [];
  for (const turn of history) {
    if (out.length === 0) {
      // The conversation must open with a user turn.
      if (turn.role !== 'user') continue;
      out.push(turn);
      continue;
    }
    const prev = out[out.length - 1]!;
    if (prev.role === turn.role) {
      // Consecutive same-role turn: keep the most recent one.
      out[out.length - 1] = turn;
    } else {
      out.push(turn);
    }
  }
  // The current user question is appended after this history, so a trailing
  // user turn would create two consecutive user turns — drop it.
  if (out.length && out[out.length - 1]!.role === 'user') out.pop();
  return out;
}

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
      const parts = [e.id, e.title, e.summary, e.url].filter(Boolean);
      return parts.join(' — ');
    })
    .join('\n');
}

// ---- Prompt selection (routing) ----

/**
 * Pick the catalogue entry whose intent/keywords best fit the question.
 * Falls back to the off-topic prompt when nothing matches.
 */
export function selectPrompt(
  catalog: CoachPromptCatalog,
  message: string,
  questionClass?: string,
  promptId?: string,
): CoachPromptEntry {
  const offTopicEntry: CoachPromptEntry = {
    id: catalog.offTopic.id,
    intent: catalog.offTopic.intent,
    title: catalog.offTopic.title,
    keywords: [],
    evidence: { domains: [], tags: [], limit: 0 },
    task: catalog.offTopic.task,
  };

  // 1) explicit id from the app
  if (promptId) {
    const byId = catalog.prompts.find((p) => p.id === promptId);
    if (byId) return byId;
  }

  const lower = message.toLowerCase();
  const score = (p: CoachPromptEntry) =>
    p.keywords.reduce((n, k) => (lower.includes(k.toLowerCase()) ? n + 1 : n), 0);

  // 2) best keyword match, optionally constrained to the given intent
  const pool =
    questionClass && catalog.prompts.some((p) => p.intent === questionClass)
      ? catalog.prompts.filter((p) => p.intent === questionClass)
      : catalog.prompts;

  let best: CoachPromptEntry | null = null;
  let bestScore = 0;
  for (const p of pool) {
    const s = score(p);
    if (s > bestScore) {
      best = p;
      bestScore = s;
    }
  }
  if (best) return best;

  // 3) no keyword hit but a known intent → first prompt of that intent
  if (questionClass) {
    const byIntent = catalog.prompts.find((p) => p.intent === questionClass);
    if (byIntent) return byIntent;
  }

  // 4) nothing fits
  return offTopicEntry;
}

// ---- Placeholder formatting ----

function asProfile(p?: Record<string, unknown>): string {
  if (!p) return 'not provided';
  const name = p.firstName ?? p.name ?? '';
  const sex = p.sex ?? '';
  const age = p.ageYears ?? p.age ?? '';
  const out = [name, sex, age !== '' ? `${age}y` : '']
    .filter((x) => x !== '' && x != null)
    .join(', ');
  return out || 'not provided';
}

function asBiomarkers(items?: Record<string, unknown>[]): string {
  if (!items || !items.length) return 'not yet measured';
  return items
    .map((b) => {
      const label = String(b.label ?? b.code ?? b.name ?? 'marker');
      const value = b.value ?? '';
      const unit = b.unit ?? '';
      const meta: string[] = [];
      if (b.ref && typeof b.ref === 'object') {
        const r = b.ref as Record<string, unknown>;
        if (r.min != null || r.max != null) meta.push(`ref ${r.min}–${r.max}`);
      }
      if (b.status) meta.push(String(b.status));
      const tail = meta.length ? ` (${meta.join(', ')})` : '';
      return `${label}: ${value} ${unit}`.replace(/\s+/g, ' ').trim() + tail;
    })
    .join('\n');
}

function asBioAge(b?: Record<string, unknown>): string {
  if (!b) return 'not computed';
  const pheno = b.phenoAge;
  const chrono = b.chronological;
  const delta = typeof b.deltaYears === 'number' ? b.deltaYears : undefined;
  const dir =
    delta === undefined
      ? ''
      : delta < 0
        ? ` (${Math.abs(delta)}y younger)`
        : delta > 0
          ? ` (${delta}y older)`
          : ' (on par)';
  if (pheno == null && chrono == null) return 'not computed';
  return `PhenoAge ${pheno}y vs chronological ${chrono}y${dir}`;
}

function asHealthScore(h?: Record<string, unknown>): string {
  if (!h || !Object.keys(h).length) return 'not yet measured';
  // v1.13 shape: { pillars: [{ pillar, label, state, score }], notYetMeasured: [] }
  if (Array.isArray(h.pillars)) {
    const lines = (h.pillars as Record<string, unknown>[]).map((p) => {
      const label = String(p.label ?? p.pillar ?? 'pillar');
      const score = p.score == null ? 'n/a' : p.score;
      const state = p.state ? ` (${p.state})` : '';
      return `${label} ${score}${state}`;
    });
    let out = lines.join(', ');
    if (Array.isArray(h.notYetMeasured) && h.notYetMeasured.length) {
      out += `; not yet measured: ${(h.notYetMeasured as unknown[]).join(', ')}`;
    }
    return out || 'not yet measured';
  }
  // fallback: flat object
  return Object.entries(h)
    .map(([k, v]) => `${k} ${v}`)
    .join(', ');
}

function asWearable(w?: Record<string, unknown>, metrics?: Record<string, unknown>): string {
  const src = w && Object.keys(w).length ? w : metrics;
  if (!src || !Object.keys(src).length) return 'no wearable data';
  return Object.entries(src)
    .map(([k, v]) => `${k}: ${v}`)
    .join(', ');
}

function asTreatment(t?: Record<string, unknown>): string {
  if (!t || !Object.keys(t).length) return 'not provided';
  return Object.entries(t)
    .map(([k, v]) => `${k}: ${v}`)
    .join(', ');
}

// ---- Reply parsing ----

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

// ---- Prompt assembly ----

export interface AssembledPrompt {
  entryId: string;
  system: string;
  user: string;
  history: ChatTurn[];
  allowedIds: string[];
}

/**
 * Build the final system + user prompt from the catalogue and the request
 * context. Maps the v1.13 context contract into the template placeholders.
 * Pure and side-effect free, so it is unit-testable without a network call.
 */
export function buildCoachPrompt(
  catalog: CoachPromptCatalog,
  provider: 'openai' | 'claude',
  message: string,
  ctx: CoachRequest['context'],
  history: ChatTurn[] = [],
): AssembledPrompt {
  const entry = selectPrompt(catalog, message, ctx.questionClass, ctx.promptId);
  const evidence = ctx.evidence ?? [];

  const system = catalog.systemPrompt[provider];
  const userBlock = renderTemplate(catalog.contextBlockTemplate, {
    USER_QUESTION: message,
    PROFILE: asProfile(ctx.profile),
    BIOMARKERS: asBiomarkers(ctx.biomarkers),
    BIO_AGE: asBioAge(ctx.bioAge),
    HEALTH_SCORE: asHealthScore(ctx.healthScore),
    WEARABLE: asWearable(ctx.wearable, ctx.metrics),
    TREATMENT: asTreatment(ctx.treatment),
    EVIDENCE: formatEvidence(evidence),
    DATE: new Date().toISOString().slice(0, 10),
  });

  return {
    entryId: entry.id,
    system,
    user: `${userBlock}${entry.task}`,
    history,
    allowedIds: evidence.map((e) => e.id),
  };
}

// ---- Orchestration ----

export async function runCoach(
  req: CoachRequest,
  signal?: AbortSignal,
): Promise<CoachReply> {
  const { config } = await store.read();
  const provider: AiProvider = config.ai.provider;

  if (provider === 'none') throw new CoachUnavailableError();

  const providerConfig =
    provider === 'openai' ? config.ai.openai : config.ai.claude;
  if (!providerConfig.apiKeyEnc) throw new CoachUnavailableError();

  const apiKey = decryptSecret(providerConfig.apiKeyEnc);

  const providerName = provider as 'openai' | 'claude';
  const { system, user, history, allowedIds } = buildCoachPrompt(
    config.promptCatalog,
    providerName,
    req.message,
    req.context,
    req.history,
  );

  // Claude requires the array to start with a user turn and alternate; OpenAI
  // is lenient but we still only ever pass sanitized user/assistant turns.
  const claudeHistory = normalizeClaudeHistory(history);

  // One log line per request to confirm history is wired through: on turn 2+
  // historyTurns should be > 0 and roles should alternate ending in assistant.
  const assembledHistory = provider === 'openai' ? history : claudeHistory;
  console.log('[coach] assembled messages', {
    provider,
    historyTurns: assembledHistory.length,
    roles: assembledHistory.map((h) => h.role),
    // +1 for the current filled context block (user turn).
    totalMessages: assembledHistory.length + 1,
  });

  const raw =
    provider === 'openai'
      ? await callOpenAI({
          apiKey,
          model: providerConfig.model,
          system,
          user,
          history,
          signal,
        })
      : await callClaude({
          apiKey,
          model: providerConfig.model,
          system,
          user,
          history: claudeHistory,
          signal,
        });

  return parseReply(raw, allowedIds);
}
