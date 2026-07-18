import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { COACH_PROMPTS_SEED } from './data/coachPromptsSeed.js';
import { env } from './env.js';
import type { CoachPrompts, RemoteConfig, StoreData } from './types.js';

function seedCatalog() {
  return structuredClone(COACH_PROMPTS_SEED);
}

/** Compare dotted numeric catalogue versions (e.g. "1.2" > "1.1"). */
function isNewerVersion(candidate: string, current: string): boolean {
  const parse = (v: string) =>
    v.split('.').map((n) => Number.parseInt(n, 10) || 0);
  const a = parse(candidate);
  const b = parse(current);
  const len = Math.max(a.length, b.length);
  for (let i = 0; i < len; i++) {
    const x = a[i] ?? 0;
    const y = b[i] ?? 0;
    if (x !== y) return x > y;
  }
  return false;
}

export const DEFAULT_PROMPTS: CoachPrompts = {
  system: `You are the Heracles AI health coach. You give concise, practical recovery, sleep,
training and lifestyle guidance for adults on TRT/ED/weight-loss programmes. Ground
advice in the user's supplied metrics when relevant. Be supportive and specific, not
generic.
Safety: you are not a doctor; never diagnose, never change prescribed medication, and
advise contacting their clinician for medical concerns.
Citations: you may ONLY cite from the provided evidence list, using their ids. Never
invent sources.
Respond ONLY with JSON: {"text": string, "citationIds": string[]}.`,
  userTemplate: `User metrics:
{{metrics}}

Evidence you may cite (id — title):
{{evidence}}

User question:
{{question}}`,
};

export function defaultConfig(): RemoteConfig {
  return {
    ai: {
      provider: 'none',
      openai: { apiKeyEnc: null, model: 'gpt-4o-mini' },
      claude: { apiKeyEnc: null, model: 'claude-3-5-sonnet-latest' },
    },
    prompts: { ...DEFAULT_PROMPTS },
    promptCatalog: seedCatalog(),
    updatedAt: new Date().toISOString(),
    updatedBy: null,
  };
}

export function defaultData(): StoreData {
  return { admins: [], config: defaultConfig() };
}

let cache: StoreData | null = null;
let writeChain: Promise<unknown> = Promise.resolve();

async function readFromDisk(): Promise<StoreData> {
  try {
    const raw = await readFile(env.DATA_FILE, 'utf8');
    return JSON.parse(raw) as StoreData;
  } catch (err: unknown) {
    if ((err as NodeJS.ErrnoException).code === 'ENOENT') {
      return defaultData();
    }
    throw err;
  }
}

async function atomicWrite(data: StoreData): Promise<void> {
  const dir = dirname(env.DATA_FILE);
  await mkdir(dir, { recursive: true });
  const tmp = `${env.DATA_FILE}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(tmp, JSON.stringify(data, null, 2), 'utf8');
  await rename(tmp, env.DATA_FILE);
}

async function read(): Promise<StoreData> {
  if (cache) return cache;
  const data = await readFromDisk();
  // Soft migration: older stores have no prompt catalogue.
  if (!data.config.promptCatalog) {
    data.config.promptCatalog = seedCatalog();
    cache = data;
    await atomicWrite(data).catch(() => undefined);
    return cache;
  }
  // Forward-only catalogue upgrade: when the bundled seed is a newer version
  // than what is persisted, adopt it so deploys pick up catalogue changes
  // (e.g. systemPrompt fixes) without a manual PUT /admin/coach/catalog.
  if (isNewerVersion(COACH_PROMPTS_SEED.version, data.config.promptCatalog.version)) {
    const from = data.config.promptCatalog.version;
    data.config.promptCatalog = seedCatalog();
    cache = data;
    await atomicWrite(data).catch(() => undefined);
    console.log(
      `[store] prompt catalogue upgraded ${from} -> ${COACH_PROMPTS_SEED.version} from bundled seed`,
    );
    return cache;
  }
  cache = data;
  return cache;
}

/** Read -> mutate -> atomic write -> refresh cache. Serialized to avoid races. */
async function update(
  mutator: (data: StoreData) => void | Promise<void>,
): Promise<StoreData> {
  const run = async (): Promise<StoreData> => {
    const data = await read();
    await mutator(data);
    await atomicWrite(data);
    cache = data;
    return data;
  };
  const result = writeChain.then(run, run);
  writeChain = result.catch(() => undefined);
  return result;
}

export const store = { read, update };
