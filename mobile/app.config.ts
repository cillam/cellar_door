/**
 * Dynamic Expo config (replaces app.json) so we can resolve env vars
 * from a path outside the repo before Expo/Metro read them.
 *
 * Mirrors backend/app/config.py's pattern exactly: CELLAR_DOOR_MOBILE_ENV_FILE
 * points at the real secrets file (kept outside the repo); if unset, falls
 * back to mobile/.env for local convenience. A missing file is not an error
 * -- EAS builds set EXPO_PUBLIC_* directly via `eas secret:create` and never
 * go through a file at all, so this loader has nothing to do there and must
 * not fail just because no .env exists.
 *
 * This file runs in Node, once, before Metro starts bundling -- so mutating
 * process.env here (via dotenv) is visible to the EXPO_PUBLIC_* inlining
 * that babel-preset-expo performs later when it transforms app code. See
 * https://docs.expo.dev/guides/environment-variables/ ("Using app config").
 *
 * Never hardcode EXPO_PUBLIC_BACKEND_URL / SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY
 * here or anywhere else -- see CLAUDE.md's "Never commit secrets" convention.
 */

import path from 'node:path';

import { config as loadEnv } from 'dotenv';
import type { ConfigContext, ExpoConfig } from 'expo/config';

const envPath = process.env.CELLAR_DOOR_MOBILE_ENV_FILE ?? path.resolve(__dirname, '.env');

// quiet: true -- a missing file (neither var set, nor mobile/.env present)
// is the expected case in CI and in EAS builds; don't log about it.
loadEnv({ path: envPath, quiet: true });

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: 'Cellar Door',
  slug: 'cellar-door',
  scheme: 'cellardoor',
  version: '1.0.0',
  orientation: 'portrait',
  icon: './assets/icon.png',
  userInterfaceStyle: 'light',
  // No newArchEnabled flag -- RN 0.86 (this SDK) dropped the old
  // architecture entirely, so the config-types schema no longer has it.
  ios: {
    supportsTablet: true,
  },
  android: {
    adaptiveIcon: {
      backgroundColor: '#E6F4FE',
      foregroundImage: './assets/android-icon-foreground.png',
      backgroundImage: './assets/android-icon-background.png',
      monochromeImage: './assets/android-icon-monochrome.png',
    },
    predictiveBackGestureEnabled: false,
  },
  web: {
    favicon: './assets/favicon.png',
  },
  plugins: [
    'expo-router',
    [
      'expo-camera',
      {
        cameraPermission: 'Cellar Door uses the camera to photograph items for your inventory.',
      },
    ],
    'expo-secure-store',
  ],
  experiments: {
    typedRoutes: true,
  },
});
