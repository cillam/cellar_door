import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import SettingsScreen from '../app/(tabs)/settings';
import { useAuth } from '../lib/auth-context';

jest.mock('../lib/auth-context', () => ({
  useAuth: jest.fn(),
}));

const mockUseAuth = useAuth as jest.Mock;

describe('SettingsScreen', () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
  });

  it('re-enables the sign-out button and shows an error on failure', async () => {
    // Regression case: signOut() used to swallow its error and never
    // reset isSigningOut, permanently disabling the button with no
    // feedback if the call failed.
    const signOut = jest.fn().mockResolvedValue({ error: 'Network request failed' });
    mockUseAuth.mockReturnValue({ signOut });

    await render(<SettingsScreen />);
    const button = screen.getByTestId('sign-out-button');
    await fireEvent.press(button);

    await waitFor(() => {
      expect(screen.getByText('Network request failed')).toBeTruthy();
    });
    expect(button.props.accessibilityState?.disabled).toBe(false);
  });

  it('shows no error on a successful sign-out', async () => {
    const signOut = jest.fn().mockResolvedValue({ error: null });
    mockUseAuth.mockReturnValue({ signOut });

    await render(<SettingsScreen />);
    await fireEvent.press(screen.getByTestId('sign-out-button'));

    await waitFor(() => expect(signOut).toHaveBeenCalled());
    expect(screen.queryByText('Network request failed')).toBeNull();
  });
});
