import { createClient } from '@supabase/supabase-js';
import * as SecureStore from 'expo-secure-store';
import { AppState } from 'react-native';

/**
 * The one Supabase client for the app -- auth (step 2) and Storage upload
 * (step 4) both go through this instance. Values come from EXPO_PUBLIC_*
 * env vars resolved by app.config.ts; never hardcode them here.
 *
 * Session storage is backed by expo-secure-store (iOS Keychain / Android
 * Keystore) rather than plain AsyncStorage -- what's persisted here is a
 * full Supabase session, including the long-lived refresh_token, which
 * grants ongoing account access if read by anything else with access to
 * the device. The old ~2KB per-value ceiling some guides warn about was
 * an artifact of expo-secure-store's legacy RSA-wrapping path (Android
 * SDK <23 only, per its own source); current versions use a symmetric-AES
 * path with no such limit, so storing the whole session object is safe.
 */

const supabaseUrl = process.env.EXPO_PUBLIC_SUPABASE_URL;
const supabasePublishableKey = process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

if (!supabaseUrl || !supabasePublishableKey) {
  throw new Error(
    'Missing EXPO_PUBLIC_SUPABASE_URL / EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY. ' +
      'Set CELLAR_DOOR_MOBILE_ENV_FILE to your env file, or create mobile/.env -- see .env.example.',
  );
}

const SecureStoreAdapter = {
  getItem: (key: string) => SecureStore.getItemAsync(key),
  setItem: (key: string, value: string) => SecureStore.setItemAsync(key, value),
  removeItem: (key: string) => SecureStore.deleteItemAsync(key),
};

export const supabase = createClient(supabaseUrl, supabasePublishableKey, {
  auth: {
    storage: SecureStoreAdapter,
    autoRefreshToken: true,
    persistSession: true,
    // This is a native app, not a web redirect flow -- there's no URL to
    // parse a session out of.
    detectSessionInUrl: false,
  },
});

// Supabase's recommended React Native pattern: only run the token
// auto-refresh timer while the app is in the foreground, so a
// backgrounded app doesn't keep waking the device to refresh a token
// nobody's using.
AppState.addEventListener('change', (state) => {
  if (state === 'active') {
    void supabase.auth.startAutoRefresh();
  } else {
    void supabase.auth.stopAutoRefresh();
  }
});
