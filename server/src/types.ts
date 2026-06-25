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

export interface RemoteConfig {
  ai: {
    provider: AiProvider;
    openai: ProviderConfig;
    claude: ProviderConfig;
  };
  prompts: CoachPrompts;
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
