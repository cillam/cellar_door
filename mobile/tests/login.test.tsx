import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { act } from 'react';

import LoginScreen from '../app/(auth)/login';
import { useAuth } from '../lib/auth-context';

// Screen-level test: mock the auth hook rather than exercising real
// Supabase/SecureStore calls -- matches the backend convention of
// mocking the ModelProvider boundary and asserting the component's own
// behavior (conditional rendering, submit gating, error display).
jest.mock('../lib/auth-context', () => ({
  useAuth: jest.fn(),
}));

const mockUseAuth = useAuth as jest.Mock;

describe('LoginScreen', () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
  });

  it('disables sign-in until both fields have a value', async () => {
    mockUseAuth.mockReturnValue({ signIn: jest.fn() });
    await render(<LoginScreen />);

    const button = screen.getByTestId('sign-in-submit');
    expect(button.props.accessibilityState?.disabled).toBe(true);

    await fireEvent.changeText(screen.getByPlaceholderText('Email'), 'test-user-a@cellar-door.dev');
    expect(button.props.accessibilityState?.disabled).toBe(true);

    await fireEvent.changeText(screen.getByPlaceholderText('Password'), 'password123');
    expect(button.props.accessibilityState?.disabled).toBe(false);
  });

  it('shows the error returned by signIn on failure', async () => {
    const signIn = jest.fn().mockResolvedValue({ error: 'Invalid login credentials' });
    mockUseAuth.mockReturnValue({ signIn });

    await render(<LoginScreen />);
    await fireEvent.changeText(screen.getByPlaceholderText('Email'), 'test-user-a@cellar-door.dev');
    await fireEvent.changeText(screen.getByPlaceholderText('Password'), 'wrong-password');
    await fireEvent.press(screen.getByTestId('sign-in-submit'));

    await waitFor(() => {
      expect(screen.getByText('Invalid login credentials')).toBeTruthy();
    });
    expect(signIn).toHaveBeenCalledWith('test-user-a@cellar-door.dev', 'wrong-password');
  });

  it('shows a loading indicator while the sign-in call is in flight', async () => {
    let resolveSignIn: (result: { error: string | null }) => void = () => {};
    const signIn = jest.fn(
      () =>
        new Promise<{ error: string | null }>((resolve) => {
          resolveSignIn = resolve;
        }),
    );
    mockUseAuth.mockReturnValue({ signIn });

    await render(<LoginScreen />);
    await fireEvent.changeText(screen.getByPlaceholderText('Email'), 'test-user-a@cellar-door.dev');
    await fireEvent.changeText(screen.getByPlaceholderText('Password'), 'password123');
    // Deliberately not awaited: fireEvent.press's internal act() wrapping
    // waits for the whole async onPress handler to settle, which here
    // waits on this very promise's resolve -- awaiting it would deadlock.
    // Capture it and await it below, after resolveSignIn() fires.
    const pressPromise = fireEvent.press(screen.getByTestId('sign-in-submit'));

    // Button label is swapped for an ActivityIndicator while submitting.
    await waitFor(() => expect(screen.queryByText('Sign In')).toBeNull());

    // resolveSignIn() triggers LoginScreen's post-await setIsSubmitting(false)
    // outside of any fireEvent/render call. The async act() overload is
    // needed (not the sync one) so it actually waits for that microtask-
    // deferred update to flush before returning.
    await act(async () => {
      resolveSignIn({ error: null });
    });
    await pressPromise;
    await waitFor(() => expect(screen.getByText('Sign In')).toBeTruthy());
  });
});
