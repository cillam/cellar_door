import { createClient } from '@supabase/supabase-js';

/**
 * The one Supabase client for the app -- auth (step 2) and Storage upload
 * (step 4) both go through this instance. Values come from EXPO_PUBLIC_*
 * env vars resolved by app.config.ts; never hardcode them here.
 *
 * No session-persistence config yet (would need
 * @react-native-async-storage/async-storage, a new dependency -- proposed
 * alongside step 2, which is what actually needs it).
 */

const supabaseUrl = process.env.EXPO_PUBLIC_SUPABASE_URL;
const supabasePublishableKey = process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

if (!supabaseUrl || !supabasePublishableKey) {
  throw new Error(
    'Missing EXPO_PUBLIC_SUPABASE_URL / EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY. ' +
      'Set CELLAR_DOOR_MOBILE_ENV_FILE to your env file, or create mobile/.env -- see .env.example.',
  );
}

export const supabase = createClient(supabaseUrl, supabasePublishableKey);
