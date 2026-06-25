import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { API_URL, ApiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import { colors, styles } from '../lib/ui';

export default function LoginScreen() {
  const { token, login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (token) router.replace('/config');
  }, [token]);

  async function onSubmit() {
    setError(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      router.replace('/config');
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401
          ? 'Invalid email or password.'
          : 'Login failed. Check the server URL and try again.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.container}>
      <Text style={styles.h1}>Heracles Admin</Text>
      <Text style={styles.muted}>Backend: {API_URL}</Text>
      <View style={styles.card}>
        <View>
          <Text style={styles.label}>Email</Text>
          <TextInput
            style={styles.input}
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            keyboardType="email-address"
            placeholder="islamov.denis@gmail.com"
            placeholderTextColor={colors.muted}
          />
        </View>
        <View>
          <Text style={styles.label}>Password</Text>
          <TextInput
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            placeholder="••••••••"
            placeholderTextColor={colors.muted}
            onSubmitEditing={onSubmit}
          />
        </View>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <Pressable style={styles.btn} onPress={onSubmit} disabled={busy}>
          {busy ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.btnText}>Sign in</Text>
          )}
        </Pressable>
      </View>
    </ScrollView>
  );
}
