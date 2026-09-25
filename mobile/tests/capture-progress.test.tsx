import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import CaptureProgressScreen from '../app/capture/progress';
import { useAuth } from '../lib/auth-context';
import { uploadPhoto } from '../lib/storage';

jest.mock('../lib/auth-context', () => ({
  useAuth: jest.fn(),
}));

jest.mock('../lib/storage', () => ({
  uploadPhoto: jest.fn(),
}));

const mockBack = jest.fn();
jest.mock('expo-router', () => ({
  useLocalSearchParams: () => ({ photoUri: 'file:///resized-photo.jpg' }),
  useRouter: () => ({ back: mockBack }),
}));

const mockUseAuth = useAuth as jest.Mock;
const mockUploadPhoto = uploadPhoto as jest.Mock;

describe('CaptureProgressScreen', () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
    mockUploadPhoto.mockReset();
    mockBack.mockReset();
    mockUseAuth.mockReturnValue({ session: { user: { id: 'user-a-id' } } });
  });

  it('shows an uploading spinner, then the resulting storage path on success', async () => {
    let resolveUpload: (result: { storagePath: string }) => void = () => {};
    mockUploadPhoto.mockReturnValue(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );

    await render(<CaptureProgressScreen />);

    expect(screen.getByText('Uploading photo...')).toBeTruthy();
    expect(mockUploadPhoto).toHaveBeenCalledWith('user-a-id', 'file:///resized-photo.jpg');

    resolveUpload({ storagePath: 'photos/user-a-id/some-uuid.jpg' });
    await waitFor(() => expect(screen.getByText('Photo uploaded.')).toBeTruthy());
    expect(screen.getByTestId('uploaded-storage-path').props.children).toBe(
      'photos/user-a-id/some-uuid.jpg',
    );
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
