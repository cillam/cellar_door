import { CameraView, useCameraPermissions } from 'expo-camera';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import { useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

// Resize target: max dimension 1600px, JPEG quality 0.8 -- lands reliably
// in the ~2-4MB range the kickoff prompt targets, regardless of the
// source device's raw sensor resolution (which can otherwise produce
// 8-12MB+ files even at high JPEG compression). Tuned empirically, not
// derived -- revisit against real devices in step 9.
const MAX_DIMENSION = 1600;
const JPEG_QUALITY = 0.8;

type CapturedPhoto = { uri: string; width: number; height: number };

export default function AddItemScreen() {
  const router = useRouter();
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView>(null);
  const [capturedPhoto, setCapturedPhoto] = useState<CapturedPhoto | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCapture = async () => {
    setError(null);
    try {
      const photo = await cameraRef.current?.takePictureAsync({ quality: 0.9 });
      if (photo) {
        setCapturedPhoto({ uri: photo.uri, width: photo.width, height: photo.height });
      }
    } catch {
      setError('Could not take photo. Try again.');
    }
  };

  const handleRetake = () => {
    setCapturedPhoto(null);
    setError(null);
  };

  const handleConfirm = async () => {
    if (!capturedPhoto) return;
    setError(null);
    setIsProcessing(true);
    try {
      // resize({width}) alone scales height to match the source aspect
      // ratio rather than capping it -- for a portrait photo (the common
      // case here: bottles and figures held upright, taller than wide),
      // that leaves height as the larger, unconstrained dimension. Resize
      // on whichever side is actually longest so MAX_DIMENSION is a real
      // cap on both axes, not just width.
      const resizeOptions =
        capturedPhoto.height >= capturedPhoto.width
          ? { height: MAX_DIMENSION }
          : { width: MAX_DIMENSION };
      const context = ImageManipulator.manipulate(capturedPhoto.uri).resize(resizeOptions);
      const rendered = await context.renderAsync();
      const result = await rendered.saveAsync({
        compress: JPEG_QUALITY,
        format: SaveFormat.JPEG,
      });
      router.push({ pathname: '/capture/progress', params: { photoUri: result.uri } });
    } catch {
      setError('Could not process photo. Try again.');
    } finally {
      setIsProcessing(false);
    }
  };

  if (!permission) {
    // Still resolving the initial permission check.
    return (
      <View style={styles.centered}>
        <ActivityIndicator />
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View style={styles.centered}>
        <Text style={styles.permissionTitle}>Camera access required</Text>
        <Text style={styles.permissionBody}>
          Cellar Door needs your camera to photograph items for your inventory.
        </Text>
        {permission.canAskAgain ? (
          <Pressable
            style={styles.button}
            onPress={requestPermission}
            testID="request-permission-button"
          >
            <Text style={styles.buttonText}>Grant Camera Access</Text>
          </Pressable>
        ) : (
          <Pressable
            style={styles.button}
            onPress={() => Linking.openSettings()}
            testID="open-settings-button"
          >
            <Text style={styles.buttonText}>Open Settings</Text>
          </Pressable>
        )}
      </View>
    );
  }

  if (capturedPhoto) {
    return (
      <View style={styles.container}>
        <Image source={{ uri: capturedPhoto.uri }} style={styles.preview} />
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <View style={styles.previewActions}>
          <Pressable
            style={[styles.button, styles.secondaryButton]}
            onPress={handleRetake}
            disabled={isProcessing}
            testID="retake-button"
          >
            <Text style={styles.buttonText}>Retake</Text>
          </Pressable>
          <Pressable
            style={styles.button}
            onPress={handleConfirm}
            disabled={isProcessing}
            testID="confirm-button"
          >
            {isProcessing ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.buttonText}>Confirm</Text>
            )}
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <CameraView ref={cameraRef} style={styles.camera} facing="back" />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <View style={styles.captureRow}>
        <Pressable style={styles.captureButton} onPress={handleCapture} testID="capture-button" />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#000',
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 12,
  },
  camera: {
    flex: 1,
  },
  preview: {
    flex: 1,
  },
  captureRow: {
    position: 'absolute',
    bottom: 40,
    left: 0,
    right: 0,
    alignItems: 'center',
  },
  captureButton: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: '#fff',
    borderWidth: 4,
    borderColor: '#ccc',
  },
  previewActions: {
    position: 'absolute',
    bottom: 40,
    left: 0,
    right: 0,
    flexDirection: 'row',
    justifyContent: 'space-evenly',
  },
  permissionTitle: {
    fontSize: 20,
    fontWeight: '700',
    textAlign: 'center',
  },
  permissionBody: {
    fontSize: 14,
    textAlign: 'center',
    color: '#555',
  },
  error: {
    position: 'absolute',
    top: 60,
    left: 24,
    right: 24,
    textAlign: 'center',
    color: '#fff',
    backgroundColor: 'rgba(192, 57, 43, 0.9)',
    padding: 8,
    borderRadius: 8,
  },
  button: {
    backgroundColor: '#6b2d5c',
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 28,
    alignItems: 'center',
    minWidth: 120,
  },
  secondaryButton: {
    backgroundColor: '#555',
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
});
