import type {
  AdminUser,
  AdminUserView,
  RemoteConfig,
  RemoteConfigAdminView,
  RemoteConfigPublicView,
} from './types.js';

export function toAdminView(config: RemoteConfig): RemoteConfigAdminView {
  return {
    ai: {
      provider: config.ai.provider,
      openai: {
        hasKey: config.ai.openai.apiKeyEnc !== null,
        model: config.ai.openai.model,
      },
      claude: {
        hasKey: config.ai.claude.apiKeyEnc !== null,
        model: config.ai.claude.model,
      },
    },
    prompts: config.prompts,
    updatedAt: config.updatedAt,
    updatedBy: config.updatedBy,
  };
}

export function toPublicView(config: RemoteConfig): RemoteConfigPublicView {
  return { provider: config.ai.provider };
}

export function toAdminUserView(user: AdminUser): AdminUserView {
  return {
    id: user.id,
    email: user.email,
    createdAt: user.createdAt,
    disabled: user.disabled,
  };
}
