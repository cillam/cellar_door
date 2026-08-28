import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Linking } from 'react-native';

import AddItemScreen from '../app/(tabs)/add';

const mockTakePictureAsync = jest.fn();
const mockUseCameraPermissions = jest.fn();
const mockRequestPermission = jest.fn();

// CameraView is a native-backed class component -- mock it as a simple
// forwardRef stub exposing just the imperative method add.tsx actually
// calls (takePictureAsync), matching how the real ref would be used
// without needing the native module itself.
jest.mock('expo-camera', () => {
  const React = require('react');
  return {
    CameraView: React.forwardRef((_props: unknown, ref: React.Ref<unknown>) => {
      React.useImperativeHandle(ref, () => ({
        takePictureAsync: mockTakePictureAsync,
      }));
      return null;
    }),
    useCameraPermissions: () => mockUseCameraPermissions(),
  };
});

const mockManipulateResult = { uri: 'file:///resized-photo.jpg', width: 1600, height: 1200 };
const mockRenderAsync = jest.fn().mockResolvedValue({
  saveAsync: jest.fn().mockResolvedValue(mockManipulateResult),
});
const mockResize = jest.fn((_size: { width?: number; height?: number }) => ({
  renderAsync: mockRenderAsync,
}));
const mockManipulate = jest.fn((_uri: string) => ({ resize: mockResize }));

jest.mock('expo-image-manipulator', () => ({
  ImageManipulator: { manipulate: (uri: string) => mockManipulate(uri) },
  SaveFormat: { JPEG: 'jpeg' },
}));

const mockPush = jest.fn();
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush }),
}));

describe('AddItemScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows a request-access button when permission is undetermined and re-askable', async () => {
    mockUseCameraPermissions.mockReturnValue([
      { granted: false, canAskAgain: true, status: 'undetermined', expires: 'never' },
      mockRequestPermission,
    ]);

    await render(<AddItemScreen />);

    expect(screen.getByText('Camera access required')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('request-permission-button'));
    expect(mockRequestPermission).toHaveBeenCalled();
  });

  it('shows an open-settings button when permission is denied and cannot be re-asked', async () => {
    mockUseCameraPermissions.mockReturnValue([
      { granted: false, canAskAgain: false, status: 'denied', expires: 'never' },
      mockRequestPermission,
    ]);
    const openSettingsSpy = jest.spyOn(Linking, 'openSettings').mockImplementation(async () => {});

    await render(<AddItemScreen />);

    expect(screen.getByTestId('open-settings-button')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('open-settings-button'));
    expect(openSettingsSpy).toHaveBeenCalled();

    openSettingsSpy.mockRestore();
  });

  it('goes from capture to preview to confirm, resizing and navigating with the result', async () => {
    mockUseCameraPermissions.mockReturnValue([
      { granted: true, canAskAgain: true, status: 'granted', expires: 'never' },
      mockRequestPermission,
    ]);
    mockTakePictureAsync.mockResolvedValue({
      uri: 'file:///raw-photo.jpg',
      width: 4000,
      height: 3000,
    });

    await render(<AddItemScreen />);

    await fireEvent.press(screen.getByTestId('capture-button'));
    await waitFor(() => expect(screen.getByTestId('confirm-button')).toBeTruthy());
    expect(screen.getByTestId('retake-button')).toBeTruthy();

    await fireEvent.press(screen.getByTestId('confirm-button'));

    await waitFor(() => expect(mockPush).toHaveBeenCalled());
    expect(mockManipulate).toHaveBeenCalledWith('file:///raw-photo.jpg');
    expect(mockResize).toHaveBeenCalledWith({ width: 1600 });
    expect(mockPush).toHaveBeenCalledWith({
      pathname: '/capture/progress',
      params: { photoUri: mockManipulateResult.uri },
    });
  });

  it('returns to the camera view on retake', async () => {
    mockUseCameraPermissions.mockReturnValue([
      { granted: true, canAskAgain: true, status: 'granted', expires: 'never' },
      mockRequestPermission,
    ]);
    mockTakePictureAsync.mockResolvedValue({
      uri: 'file:///raw-photo.jpg',
      width: 4000,
      height: 3000,
    });

    await render(<AddItemScreen />);

    await fireEvent.press(screen.getByTestId('capture-button'));
    await waitFor(() => expect(screen.getByTestId('retake-button')).toBeTruthy());

    await fireEvent.press(screen.getByTestId('retake-button'));
    await waitFor(() => expect(screen.getByTestId('capture-button')).toBeTruthy());
    expect(screen.queryByTestId('confirm-button')).toBeNull();
  });

  it('shows an error and stays on the camera view when capture fails', async () => {
    mockUseCameraPermissions.mockReturnValue([
      { granted: true, canAskAgain: true, status: 'granted', expires: 'never' },
      mockRequestPermission,
    ]);
    mockTakePictureAsync.mockRejectedValue(new Error('native capture failure'));

    await render(<AddItemScreen />);
    await fireEvent.press(screen.getByTestId('capture-button'));

    await waitFor(() => {
      expect(screen.getByText('Could not take photo. Try again.')).toBeTruthy();
    });
    expect(screen.getByTestId('capture-button')).toBeTruthy();
  });
});
