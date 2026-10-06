import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { PipelineProgress } from '../../components/PipelineProgress';
import { useAuth } from '../../lib/auth-context';
import { uploadPhoto } from '../../lib/storage';

type UploadState =
  | { status: 'uploading' }
  | { status: 'error'; message: string }
  | { status: 'done'; storagePath: string };

/**
 * Upload phase of the add-item flow (step 4), then the pipeline progress
 * phase (step 5), which takes this screen's resulting storagePath to
 * POST /items/from-photo.
 */
export default function CaptureProgressScreen() {
  const { photoUri } = useLocalSearchParams<{ photoUri: string }>();
  const router = useRouter();
  const { session } = useAuth();
  // Depend on the id, not the session object: Supabase hands back a new
  // session object on every token refresh, which would re-run the upload.
  const userId = session?.user.id;
  const [state, setState] = useState<UploadState>({ status: 'uploading' });

  const runUpload = useCallback(async () => {
    if (!photoUri || !userId) {
      setState({ status: 'error', message: 'Missing photo or session.' });
      return;
    }
    setState({ status: 'uploading' });
    try {
      const { storagePath } = await uploadPhoto(userId, photoUri);
      setState({ status: 'done', storagePath });
    } catch (err) {
      setState({
        status: 'error',
        message: err instanceof Error ? err.message : 'Upload failed. Try again.',
      });
    }
  }, [photoUri, userId]);

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

  // status === 'done' -- keyed by path so a different upload gets a
  // fresh pipeline run rather than inheriting the previous one's state.
  return <PipelineProgress key={state.storagePath} storagePath={state.storagePath} />;
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
