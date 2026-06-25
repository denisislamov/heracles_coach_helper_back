import { router } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';
import { AdminUserView, api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { colors, styles } from '../lib/ui';

export default function AdminsScreen() {
  const { token } = useAuth();
  const [admins, setAdmins] = useState<AdminUserView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [newEmail, setNewEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');

  async function refresh() {
    if (!token) return;
    try {
      setAdmins(await api.listAdmins(token));
    } catch {
      setError('Failed to load admins.');
    }
  }

  useEffect(() => {
    if (!token) {
      router.replace('/');
      return;
    }
    refresh();
  }, [token]);

  async function onCreate() {
    if (!token) return;
    setError(null);
    setNotice(null);
    try {
      await api.createAdmin(token, newEmail.trim(), newPassword);
      setNewEmail('');
      setNewPassword('');
      setNotice('Admin created.');
      refresh();
    } catch (e) {
      setError('Could not create admin (email may already exist; password min 8).');
    }
  }

  async function onReset(id: string) {
    if (!token) return;
    setError(null);
    setNotice(null);
    try {
      const res = await api.resetPassword(token, id);
      setNotice(
        res.password
          ? `New password (shown once): ${res.password}`
          : 'Password reset.',
      );
    } catch {
      setError('Reset failed.');
    }
  }

  async function onToggle(a: AdminUserView) {
    if (!token) return;
    setError(null);
    setNotice(null);
    try {
      await api.setDisabled(token, a.id, !a.disabled);
      refresh();
    } catch {
      setError('Could not change status (cannot disable the last active admin).');
    }
  }

  if (!admins) {
    return (
      <View style={[styles.screen, { justifyContent: 'center', alignItems: 'center' }]}>
        {error ? <Text style={styles.error}>{error}</Text> : <ActivityIndicator color={colors.accent} />}
      </View>
    );
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.container}>
      <View style={styles.row}>
        <Text style={styles.h1}>Admins</Text>
        <View style={{ flex: 1 }} />
        <Pressable onPress={() => router.push('/config')}>
          <Text style={styles.link}>← Config</Text>
        </Pressable>
      </View>

      <View style={styles.card}>
        <Text style={styles.h2}>Create admin</Text>
        <TextInput
          style={styles.input}
          value={newEmail}
          onChangeText={setNewEmail}
          placeholder="email"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          keyboardType="email-address"
        />
        <TextInput
          style={styles.input}
          value={newPassword}
          onChangeText={setNewPassword}
          placeholder="password (min 8)"
          placeholderTextColor={colors.muted}
          secureTextEntry
        />
        <Pressable style={styles.btn} onPress={onCreate}>
          <Text style={styles.btnText}>Create</Text>
        </Pressable>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}
      {notice ? <Text style={styles.success}>{notice}</Text> : null}

      {admins.map((a) => (
        <View key={a.id} style={styles.card}>
          <Text style={[styles.h2, { marginTop: 0 }]}>{a.email}</Text>
          <Text style={styles.muted}>
            Created {new Date(a.createdAt).toLocaleString()} · {a.disabled ? 'disabled' : 'active'}
          </Text>
          <View style={styles.row}>
            <Pressable style={[styles.btn, styles.btnGhost]} onPress={() => onReset(a.id)}>
              <Text style={styles.btnTextGhost}>Reset password</Text>
            </Pressable>
            <Pressable
              style={[styles.btn, a.disabled ? undefined : styles.btnDanger]}
              onPress={() => onToggle(a)}
            >
              <Text style={styles.btnText}>{a.disabled ? 'Enable' : 'Disable'}</Text>
            </Pressable>
          </View>
        </View>
      ))}
    </ScrollView>
  );
}
