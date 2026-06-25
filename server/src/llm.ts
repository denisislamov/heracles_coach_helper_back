export interface LlmCall {
  apiKey: string;
  model: string;
  system: string;
  user: string;
  signal?: AbortSignal;
}

export async function callOpenAI(opts: LlmCall): Promise<string> {
  const res = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${opts.apiKey}`,
    },
    body: JSON.stringify({
      model: opts.model,
      messages: [
        { role: 'system', content: opts.system },
        { role: 'user', content: opts.user },
      ],
      temperature: 0.4,
      response_format: { type: 'json_object' },
    }),
    signal: opts.signal,
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`openai error ${res.status}: ${body}`);
  }

  const data = (await res.json()) as {
    choices?: { message?: { content?: string } }[];
  };
  return data.choices?.[0]?.message?.content ?? '';
}

export async function callClaude(opts: LlmCall): Promise<string> {
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': opts.apiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: opts.model,
      max_tokens: 1024,
      temperature: 0.4,
      system: opts.system,
      messages: [{ role: 'user', content: opts.user }],
    }),
    signal: opts.signal,
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`claude error ${res.status}: ${body}`);
  }

  const data = (await res.json()) as { content?: { text?: string }[] };
  return data.content?.[0]?.text ?? '';
}
