import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { useAuth } from '../../lib/auth-context';

export default function SettingsScreen() {
  const { signOut } = useAuth();
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSignOut = async () => {
    setError(null);
    setIsSigningOut(true);
    const { error: signOutError } = await signOut();
    // Always reset, success or failure -- on success app/_layout.tsx's
    // redirect effect unmounts this screen anyway once session becomes
    // null, but on failure leaving isSigningOut true would permanently
    // disable the button with no way to retry.
    setIsSigningOut(false);
    if (signOutError) {
      setError(signOutError);
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Settings</Text>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable
        testID="sign-out-button"
        style={styles.button}
        onPress={handleSignOut}
        disabled={isSigningOut}
      >
        {isSigningOut ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.buttonText}>Sign Out</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 24,
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
  },
  error: {
    color: '#c0392b',
    textAlign: 'center',
  },
  button: {
    backgroundColor: '#c0392b',
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 24,
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
});
