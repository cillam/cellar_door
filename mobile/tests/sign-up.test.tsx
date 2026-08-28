import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import SignUpScreen from '../app/(auth)/sign-up';
import { useAuth } from '../lib/auth-context';

jest.mock('../lib/auth-context', () => ({
  useAuth: jest.fn(),
}));

const mockUseAuth = useAuth as jest.Mock;

describe('SignUpScreen', () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
  });

  it('rejects submission client-side when passwords do not match, without calling signUp', async () => {
    const signUp = jest.fn();
    mockUseAuth.mockReturnValue({ signUp });

    await render(<SignUpScreen />);
    await fireEvent.changeText(screen.getByPlaceholderText('Email'), 'new-user@cellar-door.dev');
    await fireEvent.changeText(screen.getByPlaceholderText('Password'), 'password123');
    await fireEvent.changeText(screen.getByPlaceholderText('Confirm password'), 'password456');
    await fireEvent.press(screen.getByTestId('sign-up-submit'));

    await waitFor(() => {
      expect(screen.getByText('Passwords do not match.')).toBeTruthy();
    });
    expect(signUp).not.toHaveBeenCalled();
  });

  it('shows the email-confirmation message when the project requires it', async () => {
    const signUp = jest.fn().mockResolvedValue({ error: null, needsEmailConfirmation: true });
    mockUseAuth.mockReturnValue({ signUp });

    await render(<SignUpScreen />);
    await fireEvent.changeText(screen.getByPlaceholderText('Email'), 'new-user@cellar-door.dev');
    await fireEvent.changeText(screen.getByPlaceholderText('Password'), 'password123');
    await fireEvent.changeText(screen.getByPlaceholderText('Confirm password'), 'password123');
    await fireEvent.press(screen.getByTestId('sign-up-submit'));

    await waitFor(() => {
      expect(
        screen.getByText('Check your email to confirm your account, then sign in.'),
      ).toBeTruthy();
    });
    expect(signUp).toHaveBeenCalledWith('new-user@cellar-door.dev', 'password123');
  });

  it('does not show the email-confirmation message when signUp already produced a session', async () => {
    // Regression case: a project with email confirmation disabled gets a
    // session immediately, and app/_layout.tsx's redirect effect takes
    // over -- showing "check your email" here would be actively wrong,
    // not just redundant.
    const signUp = jest.fn().mockResolvedValue({ error: null, needsEmailConfirmation: false });
    mockUseAuth.mockReturnValue({ signUp });

    await render(<SignUpScreen />);
    await fireEvent.changeText(screen.getByPlaceholderText('Email'), 'new-user@cellar-door.dev');
    await fireEvent.changeText(screen.getByPlaceholderText('Password'), 'password123');
    await fireEvent.changeText(screen.getByPlaceholderText('Confirm password'), 'password123');
    await fireEvent.press(screen.getByTestId('sign-up-submit'));

    await waitFor(() => expect(signUp).toHaveBeenCalled());
    expect(
      screen.queryByText('Check your email to confirm your account, then sign in.'),
    ).toBeNull();
  });

  it('shows the error returned by signUp on failure', async () => {
    const signUp = jest.fn().mockResolvedValue({ error: 'User already registered' });
    mockUseAuth.mockReturnValue({ signUp });

    await render(<SignUpScreen />);
    await fireEvent.changeText(screen.getByPlaceholderText('Email'), 'existing@cellar-door.dev');
    await fireEvent.changeText(screen.getByPlaceholderText('Password'), 'password123');
    await fireEvent.changeText(screen.getByPlaceholderText('Confirm password'), 'password123');
    await fireEvent.press(screen.getByTestId('sign-up-submit'));

    await waitFor(() => {
      expect(screen.getByText('User already registered')).toBeTruthy();
    });
  });
});
