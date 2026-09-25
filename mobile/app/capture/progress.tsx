import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { useAuth } from '../../lib/auth-context';
import { uploadPhoto } from '../../lib/storage';

type UploadState =
  | { status: 'uploading' }
  | { status: 'error'; message: string }
  | { status: 'done'; storagePath: string };

/**
 * Upload phase of the add-item flow (step 4), then a placeholder for the
 * pipeline progress phase (real SSE UI lands in step 5, using this
 * screen's resulting storagePath to call POST /items/from-photo).
 */
export default function CaptureProgressScreen() {
  const { photoUri } = useLocalSearchParams<{ photoUri: string }>();
  const router = useRouter();
  const { session } = useAuth();
  const [state, setState] = useState<UploadState>({ status: 'uploading' });

  const runUpload = useCallback(async () => {
    if (!photoUri || !session) {
      setState({ status: 'error', message: 'Missing photo or session.' });
      return;
    }
    setState({ status: 'uploading' });
    try {
      const { storagePath } = await uploadPhoto(session.user.id, photoUri);
      setState({ status: 'done', storagePath });
    } catch (err) {
      setState({
        status: 'error',
        message: err instanceof Error ? err.message : 'Upload failed. Try again.',
      });
    }
  }, [photoUri, session]);

  useEffect(() => {
    void runUpload();
  }, [runUpload]);

  if (state.status === 'uploading') {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
        <Text style={styles.statusText}>Uploading photo...</Text>
      </View>
    );
  }

  if (state.status === 'error') {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorText}>{state.message}</Text>
        {/* Back to the add screen, not an in-place retry: the photo is
            still there with Retake/Confirm. */}
        <Pressable style={styles.button} onPress={() => router.back()} testID="try-again-button">
          <Text style={styles.buttonText}>Try Again</Text>
        </Pressable>
      </View>
    );
  }

  // status === 'done' -- placeholder until step 5 wires the real SSE
  // pipeline UI using this storagePath.
  return (
    <View style={styles.centered}>
      <Text style={styles.statusText}>Photo uploaded.</Text>
      <Text style={styles.pathText} testID="uploaded-storage-path">
        {state.storagePath}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 12,
  },
  statusText: {
    fontSize: 16,
    fontWeight: '600',
  },
  pathText: {
    fontSize: 12,
    color: '#555',
    textAlign: 'center',
  },
  errorText: {
    fontSize: 16,
    color: '#c0392b',
    textAlign: 'center',
  },
  button: {
    backgroundColor: '#6b2d5c',
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 28,
    alignItems: 'center',
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
});
