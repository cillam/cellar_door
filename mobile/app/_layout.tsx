import { Stack } from 'expo-router';

/**
 * Root layout. Step 1 is a navigation shell only -- no auth-gating yet.
 * Step 2 adds the redirect logic between (auth) and (tabs) based on
 * Supabase session state; for now both groups are directly reachable so
 * routing itself can be verified.
 */
export default function RootLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="(auth)" />
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="item/[id]" options={{ headerShown: true, title: 'Item' }} />
    </Stack>
  );
}
