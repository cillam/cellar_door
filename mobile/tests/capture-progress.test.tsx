import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import CaptureProgressScreen from '../app/capture/progress';
import { streamFromPhoto } from '../lib/api';
import { useAuth } from '../lib/auth-context';
import { uploadPhoto } from '../lib/storage';

jest.mock('../lib/auth-context', () => ({
  useAuth: jest.fn(),
}));

jest.mock('../lib/storage', () => ({
  uploadPhoto: jest.fn(),
}));

jest.mock('../lib/supabase', () => ({ supabase: {} }));
jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));

// The pipeline phase that follows the upload has its own tests
// (pipeline-progress.test.tsx); here it only matters that it starts once,
// with the uploaded path. lib/api.ts throws at import without its env var.
jest.mock('../lib/api', () => {
  process.env.EXPO_PUBLIC_BACKEND_URL = 'https://backend.test';
  return {
    ...jest.requireActual('../lib/api'),
    streamFromPhoto: jest.fn(),
    streamResume: jest.fn(),
  };
});

const mockBack = jest.fn();
jest.mock('expo-router', () => ({
  useLocalSearchParams: () => ({ photoUri: 'file:///resized-photo.jpg' }),
  useRouter: () => ({ back: mockBack, replace: jest.fn() }),
}));

const mockUseAuth = useAuth as jest.Mock;
const mockUploadPhoto = uploadPhoto as jest.Mock;
const mockStreamFromPhoto = streamFromPhoto as jest.Mock;

describe('CaptureProgressScreen', () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
    mockUploadPhoto.mockReset();
    mockBack.mockReset();
    mockStreamFromPhoto.mockReset();
    // Never settles: the screen stays in the pipeline's first phase.
    mockStreamFromPhoto.mockReturnValue(new Promise(() => {}));
    mockUseAuth.mockReturnValue({ session: { user: { id: 'user-a-id' } } });
  });

  it('shows an uploading spinner, then starts the pipeline with the uploaded storage path', async () => {
    let resolveUpload: (result: { storagePath: string }) => void = () => {};
    mockUploadPhoto.mockReturnValue(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );

    await render(<CaptureProgressScreen />);

    expect(screen.getByText('Uploading photo...')).toBeTruthy();
    expect(mockUploadPhoto).toHaveBeenCalledWith('user-a-id', 'file:///resized-photo.jpg');
    expect(mockStreamFromPhoto).not.toHaveBeenCalled();

    resolveUpload({ storagePath: 'photos/user-a-id/some-uuid.jpg' });
    await waitFor(() => expect(screen.getByText('Identifying category...')).toBeTruthy());
    expect(mockStreamFromPhoto).toHaveBeenCalledTimes(1);
    expect(mockStreamFromPhoto.mock.calls[0][0]).toBe('photos/user-a-id/some-uuid.jpg');
  });

  it('shows an error on failure, and Try Again goes back without re-uploading', async () => {
    mockUploadPhoto.mockRejectedValueOnce(new Error('Network request failed'));

    await render(<CaptureProgressScreen />);
    await waitFor(() => {
      expect(screen.getByText('Network request failed')).toBeTruthy();
    });

    await fireEvent.press(screen.getByTestId('try-again-button'));

    expect(mockBack).toHaveBeenCalledTimes(1);
    expect(mockUploadPhoto).toHaveBeenCalledTimes(1);
    expect(mockStreamFromPhoto).not.toHaveBeenCalled();
  });

  it('neither re-uploads nor starts a second pipeline run when a token refresh hands back a new session object for the same user', async () => {
    mockUploadPhoto.mockResolvedValue({ storagePath: 'photos/user-a-id/some-uuid.jpg' });

    await render(<CaptureProgressScreen />);
    await waitFor(() => expect(screen.getByText('Identifying category...')).toBeTruthy());

    // Supabase emits a fresh session object on every token refresh
    // (including on app foreground) -- same user, new identity.
    mockUseAuth.mockReturnValue({ session: { user: { id: 'user-a-id' } } });
    await screen.rerender(<CaptureProgressScreen />);

    expect(screen.getByText('Identifying category...')).toBeTruthy();
    expect(mockUploadPhoto).toHaveBeenCalledTimes(1);
    expect(mockStreamFromPhoto).toHaveBeenCalledTimes(1);
  });

  it('shows an error without calling uploadPhoto when there is no session', async () => {
    mockUseAuth.mockReturnValue({ session: null });

    await render(<CaptureProgressScreen />);

    await waitFor(() => {
      expect(screen.getByText('Missing photo or session.')).toBeTruthy();
    });
    expect(mockUploadPhoto).not.toHaveBeenCalled();
  });
});
