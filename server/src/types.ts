export type AiProvider = 'none' | 'openai' | 'claude';

export interface ProviderConfig {
  apiKeyEnc: string | null;
  model: string;
}

export interface CoachPrompts {
  /** persona + safety rules + citation rules */
  system: string;
  /** placeholders {{metrics}} {{evidence}} {{question}} */
  userTemplate: string;
}

export interface PromptEvidenceQuery {
  domains: string[];
  tags: string[];
  limit: number;
}

export interface CoachPromptEntry {
  id: string;
  intent: string;
  title: string;
  keywords: string[];
  evidence: PromptEvidenceQuery;
  task: string;
}

export interface CoachPromptOffTopic {
  id: string;
  intent: string;
  title: string;
  description?: string;
  task: string;
}

export interface CoachPromptCatalog {
  version: string;
  updatedAt: string;
  description?: string;
  placeholders: Record<string, string>;
  outputContract?: unknown; // stored as-is; not sent to the LLM
  systemPrompt: { openai: string; claude: string };
  contextBlockTemplate: string;
  responseExamples?: unknown[];
  offTopic: CoachPromptOffTopic;
  routing: { strategy: string; defaultEvidenceLimit: number };
  prompts: CoachPromptEntry[];
}

export interface RemoteConfig {
  ai: {
    provider: AiProvider;
    openai: ProviderConfig;
    claude: ProviderConfig;
  };
  prompts: CoachPrompts; // LEGACY single-prompt — kept for rollback
  promptCatalog: CoachPromptCatalog; // catalogue from coach-prompts.v1.json
  updatedAt: string;
  updatedBy: string | null;
}

export interface AdminUser {
  id: string;
  email: string;
  passwordHash: string;
  createdAt: string;
  disabled: boolean;
}

export interface StoreData {
  admins: AdminUser[];
  config: RemoteConfig;
}

// Public / admin DTOs
export interface ProviderConfigPublic {
  hasKey: boolean;
  model: string;
}

export interface RemoteConfigAdminView {
  ai: {
    provider: AiProvider;
    openai: ProviderConfigPublic;
    claude: ProviderConfigPublic;
  };
  prompts: CoachPrompts;
  updatedAt: string;
  updatedBy: string | null;
}

export interface RemoteConfigPublicView {
  provider: AiProvider;
}

export interface AdminUserView {
  id: string;
  email: string;
  createdAt: string;
  disabled: boolean;
}
