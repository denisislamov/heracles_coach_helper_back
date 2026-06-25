import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { AuthProvider } from '../lib/auth';
import { colors } from '../lib/ui';

export default function RootLayout() {
  return (
    <AuthProvider>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.card },
          headerTintColor: colors.text,
          contentStyle: { backgroundColor: colors.bg },
        }}
      >
        <Stack.Screen name="index" options={{ title: 'Heracles Admin — Login' }} />
        <Stack.Screen name="config" options={{ title: 'Remote config' }} />
        <Stack.Screen name="admins" options={{ title: 'Admins' }} />
      </Stack>
    </AuthProvider>
  );
}
