import { Link } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { useAuth } from '../../lib/auth-context';

export default function SignUpScreen() {
  const { signUp } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmationMessage, setConfirmationMessage] = useState<string | null>(null);

  const canSubmit =
    email.length > 0 && password.length > 0 && confirmPassword.length > 0 && !isSubmitting;

  const handleSignUp = async () => {
    setError(null);
    setConfirmationMessage(null);

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setIsSubmitting(true);
    const { error: signUpError, needsEmailConfirmation } = await signUp(email, password);
    setIsSubmitting(false);

    if (signUpError) {
      setError(signUpError);
      return;
    }

    // Only relevant when the Supabase project requires email confirmation
    // -- signUp() then succeeds without producing an active session, and
    // app/_layout.tsx's redirect effect only fires once a session exists,
    // so without this message the user would be left looking at an
    // unchanged sign-up form with no explanation of what to do next. When
    // email confirmation is disabled, signUp() already has a session and
    // that same redirect effect takes over immediately -- showing this
    // message in that case would be actively wrong, not just redundant.
    if (needsEmailConfirmation) {
      setConfirmationMessage('Check your email to confirm your account, then sign in.');
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Create Account</Text>

      <TextInput
        style={styles.input}
        placeholder="Email"
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="email-address"
        textContentType="emailAddress"
        value={email}
        onChangeText={setEmail}
        editable={!isSubmitting}
      />
      <TextInput
        style={styles.input}
        placeholder="Password"
        secureTextEntry
        textContentType="newPassword"
        value={password}
        onChangeText={setPassword}
        editable={!isSubmitting}
      />
      <TextInput
        style={styles.input}
        placeholder="Confirm password"
        secureTextEntry
        textContentType="newPassword"
        value={confirmPassword}
        onChangeText={setConfirmPassword}
        editable={!isSubmitting}
      />

      {error ? <Text style={styles.error}>{error}</Text> : null}
      {confirmationMessage ? (
        <Text style={styles.confirmation}>{confirmationMessage}</Text>
      ) : null}

      <Pressable
        testID="sign-up-submit"
        style={[styles.button, !canSubmit && styles.buttonDisabled]}
        onPress={handleSignUp}
        disabled={!canSubmit}
      >
        {isSubmitting ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.buttonText}>Sign Up</Text>
        )}
      </Pressable>

      <Link href="/(auth)/login" style={styles.link}>
        <Text style={styles.linkText}>Already have an account? Sign in</Text>
      </Link>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    padding: 24,
    gap: 12,
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    textAlign: 'center',
    marginBottom: 24,
  },
  input: {
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
  },
  error: {
    color: '#c0392b',
    textAlign: 'center',
  },
  confirmation: {
    color: '#1e7e34',
    textAlign: 'center',
  },
  button: {
    backgroundColor: '#6b2d5c',
    borderRadius: 8,
    padding: 14,
    alignItems: 'center',
    marginTop: 8,
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  link: {
    marginTop: 16,
    alignItems: 'center',
  },
  linkText: {
    color: '#6b2d5c',
    fontSize: 14,
  },
});
