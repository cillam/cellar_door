import type { Session } from '@supabase/supabase-js';
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { supabase } from './supabase';

type AuthResult = { error: string | null };
/** signUp() additionally reports whether the account needs email
 * confirmation before it has a session -- Supabase returns success with
 * no session in that case, which sign-up.tsx needs to tell apart from
 * "signed up and already signed in" to know whether to show a
 * confirm-your-email message. */
type SignUpResult = AuthResult & { needsEmailConfirmation: boolean };

type AuthContextValue = {
  session: Session | null;
  /** True until the initial getSession() call resolves. Distinct from
   * per-action loading state (that lives in each screen, per field). */
  isLoading: boolean;
  signIn: (email: string, password: string) => Promise<AuthResult>;
  signUp: (email: string, password: string) => Promise<SignUpResult>;
  signOut: () => Promise<AuthResult>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

/**
 * Wraps the app, exposing the current Supabase session and the three auth
 * actions the (auth) screens and settings' sign-out button need. Session
 * persistence itself (surviving app restarts) is handled by lib/supabase.ts's
 * SecureStore-backed storage adapter -- this provider's job is just to read
 * that state into React and keep it live via onAuthStateChange.
 *
 * Navigation on auth state change (redirecting between (auth) and (tabs))
 * lives in app/_layout.tsx, not here -- this module knows nothing about
 * routes.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setIsLoading(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
    });

    return () => listener.subscription.unsubscribe();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isLoading,
      signIn: async (email: string, password: string) => {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        return { error: error?.message ?? null };
      },
      signUp: async (email: string, password: string) => {
        const { data, error } = await supabase.auth.signUp({ email, password });
        return {
          error: error?.message ?? null,
          // Supabase returns success with data.session === null when the
          // project requires email confirmation -- that's the only signal
          // available to tell "needs confirmation" apart from "signed up
          // and already has a session" (email-confirmation-disabled case).
          needsEmailConfirmation: !error && data.session === null,
        };
      },
      signOut: async () => {
        const { error } = await supabase.auth.signOut();
        return { error: error?.message ?? null };
      },
    }),
    [session, isLoading],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
