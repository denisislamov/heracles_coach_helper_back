import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { env } from './env.js';
import type { CoachPrompts, RemoteConfig, StoreData } from './types.js';

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
  cache = await readFromDisk();
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
