import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';
import {
  AdminConfig,
  AiProvider,
  ConfigPatch,
  api,
} from '../lib/api';
import { useAuth } from '../lib/auth';
import { colors, styles } from '../lib/ui';

const PROVIDERS: AiProvider[] = ['none', 'openai', 'claude'];

function ProviderCard({
  name,
  hasKey,
  model,
  onModel,
  onSaveKey,
  onClearKey,
}: {
  name: string;
  hasKey: boolean;
  model: string;
  onModel: (v: string) => void;
  onSaveKey: (key: string) => void;
  onClearKey: () => void;
}) {
  const [keyInput, setKeyInput] = useState('');
  return (
    <View style={styles.card}>
      <Text style={styles.h2}>{name}</Text>
      <View>
        <Text style={styles.label}>Model</Text>
        <TextInput style={styles.input} value={model} onChangeText={onModel} autoCapitalize="none" />
      </View>
      <View>
        <Text style={styles.label}>
          API key {hasKey ? '— key is set' : '— no key'}
        </Text>
        <TextInput
          style={styles.input}
          value={keyInput}
          onChangeText={setKeyInput}
          placeholder="Paste new key to save"
          placeholderTextColor={colors.muted}
          secureTextEntry
          autoCapitalize="none"
        />
      </View>
      <View style={styles.row}>
        <Pressable
          style={[styles.btn, !keyInput && { opacity: 0.5 }]}
          disabled={!keyInput}
          onPress={() => {
            onSaveKey(keyInput);
            setKeyInput('');
          }}
        >
          <Text style={styles.btnText}>Save key</Text>
        </Pressable>
        <Pressable
          style={[styles.btn, styles.btnGhost, !hasKey && { opacity: 0.5 }]}
          disabled={!hasKey}
          onPress={onClearKey}
        >
          <Text style={styles.btnTextGhost}>Clear key</Text>
        </Pressable>
      </View>
    </View>
  );
}

export default function ConfigScreen() {
  const { token, email, logout } = useAuth();
  const [config, setConfig] = useState<AdminConfig | null>(null);
  const [patch, setPatch] = useState<ConfigPatch>({});
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) {
      router.replace('/');
      return;
    }
    api
      .getConfig(token)
      .then(setConfig)
      .catch(() => setError('Failed to load config.'));
  }, [token]);

  if (!config) {
    return (
      <View style={[styles.screen, { justifyContent: 'center', alignItems: 'center' }]}>
        {error ? <Text style={styles.error}>{error}</Text> : <ActivityIndicator color={colors.accent} />}
      </View>
    );
  }

  const provider = patch.ai?.provider ?? config.ai.provider;

  function mergeAi(key: 'openai' | 'claude', value: { model?: string; apiKey?: string | null }) {
    setPatch((p) => ({
      ...p,
      ai: { ...p.ai, [key]: { ...p.ai?.[key], ...value } },
    }));
  }

  async function onSave() {
    if (!token) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const updated = await api.putConfig(token, patch);
      setConfig(updated);
      setPatch({});
      setMsg('Saved.');
    } catch {
      setError('Save failed.');
    } finally {
      setBusy(false);
    }
  }

  const openaiModel = patch.ai?.openai?.model ?? config.ai.openai.model;
  const claudeModel = patch.ai?.claude?.model ?? config.ai.claude.model;
  const systemVal = patch.prompts?.system ?? config.prompts.system;
  const templateVal = patch.prompts?.userTemplate ?? config.prompts.userTemplate;

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.container}>
      <View style={styles.row}>
        <Text style={styles.h1}>Remote config</Text>
        <View style={{ flex: 1 }} />
        <Pressable onPress={() => router.push('/admins')}>
          <Text style={styles.link}>Admins →</Text>
        </Pressable>
        <Pressable onPress={logout}>
          <Text style={styles.link}>Logout</Text>
        </Pressable>
      </View>
      <Text style={styles.muted}>
        Signed in as {email}. Last updated {new Date(config.updatedAt).toLocaleString()} by{' '}
        {config.updatedBy ?? '—'}.
      </Text>

      <View style={styles.card}>
        <Text style={styles.h2}>AI provider</Text>
        <View style={styles.row}>
          {PROVIDERS.map((p) => {
            const active = provider === p;
            return (
              <Pressable
                key={p}
                style={[styles.pill, active && styles.pillActive]}
                onPress={() => setPatch((prev) => ({ ...prev, ai: { ...prev.ai, provider: p } }))}
              >
                <Text style={[styles.pillText, active && styles.pillTextActive]}>{p}</Text>
              </Pressable>
            );
          })}
        </View>
        <Text style={styles.muted}>
          "none" → the app uses its local mock coach. Otherwise the backend calls the selected provider.
        </Text>
      </View>

      <ProviderCard
        name="OpenAI"
        hasKey={config.ai.openai.hasKey}
        model={openaiModel}
        onModel={(v) => mergeAi('openai', { model: v })}
        onSaveKey={(key) => mergeAi('openai', { apiKey: key })}
        onClearKey={() => mergeAi('openai', { apiKey: null })}
      />
      <ProviderCard
        name="Claude (Anthropic)"
        hasKey={config.ai.claude.hasKey}
        model={claudeModel}
        onModel={(v) => mergeAi('claude', { model: v })}
        onSaveKey={(key) => mergeAi('claude', { apiKey: key })}
        onClearKey={() => mergeAi('claude', { apiKey: null })}
      />

      <View style={styles.card}>
        <Text style={styles.h2}>Prompts</Text>
        <View>
          <Text style={styles.label}>System</Text>
          <TextInput
            style={[styles.input, styles.textarea]}
            value={systemVal}
            onChangeText={(v) => setPatch((p) => ({ ...p, prompts: { ...p.prompts, system: v } }))}
            multiline
          />
        </View>
        <View>
          <Text style={styles.label}>
            User template — placeholders: {'{{metrics}}'} {'{{evidence}}'} {'{{question}}'}
          </Text>
          <TextInput
            style={[styles.input, styles.textarea]}
            value={templateVal}
            onChangeText={(v) =>
              setPatch((p) => ({ ...p, prompts: { ...p.prompts, userTemplate: v } }))
            }
            multiline
          />
        </View>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}
      {msg ? <Text style={styles.success}>{msg}</Text> : null}
      <Pressable style={styles.btn} onPress={onSave} disabled={busy}>
        {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnText}>Save</Text>}
      </Pressable>
    </ScrollView>
  );
}
