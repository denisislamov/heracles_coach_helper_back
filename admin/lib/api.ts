export const API_URL =
  process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:4000';

export type AiProvider = 'none' | 'openai' | 'claude';

export interface ProviderConfigPublic {
  hasKey: boolean;
  model: string;
}

export interface AdminConfig {
  ai: {
    provider: AiProvider;
    openai: ProviderConfigPublic;
    claude: ProviderConfigPublic;
  };
  prompts: { system: string; userTemplate: string };
  updatedAt: string;
  updatedBy: string | null;
}

export interface AdminUserView {
  id: string;
  email: string;
  createdAt: string;
  disabled: boolean;
}

export interface ConfigPatch {
  ai?: {
    provider?: AiProvider;
    openai?: { model?: string; apiKey?: string | null };
    claude?: { model?: string; apiKey?: string | null };
  };
  prompts?: { system?: string; userTemplate?: string };
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type OnUnauthorized = () => void;
let onUnauthorized: OnUnauthorized | null = null;
export function setOnUnauthorized(cb: OnUnauthorized): void {
  onUnauthorized = cb;
}

async function request<T>(
  path: string,
  opts: { method?: string; body?: unknown; token?: string | null } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers['content-type'] = 'application/json';
  if (opts.token) headers['authorization'] = `Bearer ${opts.token}`;

  const res = await fetch(`${API_URL}${path}`, {
    method: opts.method ?? 'GET',
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });

  if (res.status === 401) {
    onUnauthorized?.();
    throw new ApiError(401, 'unauthorized');
  }

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new ApiError(res.status, (data && data.error) || `error_${res.status}`);
  }
  return data as T;
}

export const api = {
  login(email: string, password: string) {
    return request<{ token: string; admin: { id: string; email: string } }>(
      '/admin/auth/login',
      { method: 'POST', body: { email, password } },
    );
  },
  getConfig(token: string) {
    return request<AdminConfig>('/admin/config', { token });
  },
  putConfig(token: string, patch: ConfigPatch) {
    return request<AdminConfig>('/admin/config', {
      method: 'PUT',
      body: patch,
      token,
    });
  },
  listAdmins(token: string) {
    return request<AdminUserView[]>('/admin/admins', { token });
  },
  createAdmin(token: string, email: string, password: string) {
    return request<AdminUserView>('/admin/admins', {
      method: 'POST',
      body: { email, password },
      token,
    });
  },
  resetPassword(token: string, id: string, password?: string) {
    return request<{ ok: true; password?: string }>(
      `/admin/admins/${id}/reset-password`,
      { method: 'POST', body: password ? { password } : {}, token },
    );
  },
  setDisabled(token: string, id: string, disabled: boolean) {
    return request<AdminUserView>(`/admin/admins/${id}/disable`, {
      method: 'POST',
      body: { disabled },
      token,
    });
  },
};
